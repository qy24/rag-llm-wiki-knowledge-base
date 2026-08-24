"""对外知识接口（API 密钥鉴权，服务端强制权限过滤）：

- POST /v1/knowledge/search         混合检索
- POST /v1/knowledge/graph/query    图谱定向查询
- POST /v1/chat/completions         OpenAI 兼容聚合生成端点

权限：所有请求解析 Bearer 密钥 → allowed_kb_ids 注入检索服务，
客户端传参无法扩大范围；每次调用落审计日志。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import KeyScope, get_key_scope
from ..models import AuditLog, KnowledgeBase
from ..schemas import ChatIn, GraphQueryIn, SearchIn, content_has_images, content_text
from ..services import llm as llm_svc
from ..services.rag import LLMError, rag_chat
from ..services.retrieval import graph_query, search_knowledge

router = APIRouter()
settings = get_settings()


def _log(scope: KeyScope, action: str, query: str, summary: dict, request: Request):
    db = next(get_db())
    try:
        db.add(AuditLog(
            api_key_id=scope.api_key.id, user_id=scope.user.id if scope.user else None,
            action=action, query=query, result_summary=summary,
            ip=request.client.host if request.client else "",
        ))
        db.commit()
    finally:
        db.close()


@router.post("/knowledge/search")
def search(body: SearchIn, request: Request,
           scope: KeyScope = Depends(get_key_scope),
           db: Session = Depends(get_db)):
    if not scope.allowed_kb_ids:
        raise HTTPException(403, "该密钥未绑定任何知识库")
    result = search_knowledge(
        db, settings, body.query, scope.allowed_kb_ids,
        top_k=body.top_k, graph_depth=body.graph_depth,
        enable_graph=body.enable_graph,
    )
    _log(scope, "knowledge.search", body.query,
         {"hits": len(result["chunks"]), "entities": len(result["graph"]["entities"])},
         request)
    return result


@router.post("/knowledge/graph/query")
def graph_search(body: GraphQueryIn, request: Request,
                 scope: KeyScope = Depends(get_key_scope),
                 db: Session = Depends(get_db)):
    if not scope.allowed_kb_ids:
        raise HTTPException(403, "该密钥未绑定任何知识库")
    result = graph_query(db, settings, scope.allowed_kb_ids,
                         entity=body.entity, relation_types=body.relation_types,
                         depth=body.depth)
    _log(scope, "knowledge.graph_query", body.entity,
         {"entities": len(result["entities"]), "relations": len(result["relations"])},
         request)
    return result


@router.post("/chat/completions")
def chat_completions(body: ChatIn, request: Request,
                     scope: KeyScope = Depends(get_key_scope),
                     db: Session = Depends(get_db)):
    """OpenAI 兼容聚合端点：检索该密钥授权范围内的知识 → 组装上下文 → 调云端模型生成。

    末条消息携带图片（OpenAI 视觉 content 格式）时走视觉 RAG：
    图片理解 → 检索内部数据 + 内部相关图片 → 视觉模型生成回答。
    """
    if not scope.allowed_kb_ids:
        raise HTTPException(403, "该密钥未绑定任何知识库")
    last_msg = body.messages[-1]
    kb_ids = scope.allowed_kb_ids
    try:
        result = rag_chat(
            db, settings, kb_ids, body.messages,
            top_k=body.top_k, graph_depth=body.graph_depth,
            temperature=body.temperature,
            prompt=scope.api_key.prompt_template or None,
        )
    except LLMError as e:
        raise HTTPException(e.status_code, str(e))
    answer = result["answer"]
    _log(scope,
         "chat.completions.vision" if content_has_images(last_msg.content) else "chat.completions",
         content_text(last_msg.content)[:500],
         {"hits": len(result["sources"]),
          "internal_images": len(result["internal_images"]),
          "answer_len": len(answer)}, request)
    return {
        "id": "chatcmpl-kb-local",
        "object": "chat.completion",
        "model": body.model or result["model"],
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "sources": result["sources"],
        "internal_images": result["internal_images"],
    }
