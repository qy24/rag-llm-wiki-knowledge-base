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
from ..models import AuditLog, ChatSession, KnowledgeBase
from ..schemas import (ChatIn, ChatMessage, GraphQueryIn, SearchIn, content_has_images,
                       content_text, resolve_consult_type)
from ..services import llm as llm_svc
from ..services.rag import LLMError, rag_chat
from ..services.retrieval import graph_query, search_knowledge

router = APIRouter()
settings = get_settings()

# 每个会话最多保留的轮数（一轮 = 一问一答），超出截断最旧的，避免上下文无限膨胀
MAX_SESSION_TURNS = 10


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

    多客户会话记忆：传入 session_id（客户唯一 ID）时，服务端自动恢复该客户
    上次对话上下文并接着处理，回答后把本轮问答存回该客户会话；不同客户/
    不同密钥之间完全隔离（按 api_key_id + session_id 双键隔离）。
    """
    if not scope.allowed_kb_ids:
        raise HTTPException(403, "该密钥未绑定任何知识库")

    # ===== 会话记忆：加载该客户的历史上下文 =====
    session_obj = None
    history_msgs: list[ChatMessage] = []
    sid = (body.session_id or "").strip()
    if sid:
        session_obj = db.query(ChatSession).filter(
            ChatSession.api_key_id == scope.api_key.id,
            ChatSession.session_id == sid,
        ).first()
        if session_obj is None:
            session_obj = ChatSession(api_key_id=scope.api_key.id, session_id=sid, messages=[])
            db.add(session_obj)
            db.commit()
            db.refresh(session_obj)
        for h in (session_obj.messages or []):
            try:
                history_msgs.append(ChatMessage(role=h["role"], content=h["content"]))
            except Exception:
                continue
    # 历史 + 当前消息 → 完整上下文；last 为当前这条（视觉判断/检索用）
    full_messages = history_msgs + body.messages
    last_msg = full_messages[-1]

    kb_ids = scope.allowed_kb_ids
    try:
        result = rag_chat(
            db, settings, kb_ids, full_messages,
            top_k=body.top_k, graph_depth=body.graph_depth,
            temperature=body.temperature,
            prompt=scope.api_key.prompt_template or None,
            consult_type=resolve_consult_type(body.consult_type, body.is_after_sale),
            conversation=body.context,
        )
    except LLMError as e:
        raise HTTPException(e.status_code, str(e))
    answer = result["answer"]

    # ===== 会话记忆：把本轮问答存回该客户（历史只存纯文本，图片仅当次有效）=====
    session_turns = 0
    if session_obj is not None:
        def _text(m: ChatMessage) -> str:
            return m.content if isinstance(m.content, str) else content_text(m.content)
        new_history: list[dict] = [
            {"role": h.role, "content": _text(h)} for h in history_msgs
        ] + [{"role": m.role, "content": _text(m)} for m in body.messages]
        new_history.append({"role": "assistant", "content": answer})
        # 截断：只保留最近 MAX_SESSION_TURNS 轮
        max_msgs = MAX_SESSION_TURNS * 2
        if len(new_history) > max_msgs:
            new_history = new_history[-max_msgs:]
        session_obj.messages = new_history
        db.commit()
        session_turns = len(new_history) // 2

    _log(scope,
         "chat.completions.vision" if content_has_images(last_msg.content) else "chat.completions",
         content_text(last_msg.content)[:500],
         {"hits": len(result["sources"]),
          "internal_images": len(result["internal_images"]),
          "answer_len": len(answer),
          "answer": answer[:800]}, request)  # 回复内容留痕（截断800字），与测试台一致
    resp = {
        "id": "chatcmpl-kb-local",
        "object": "chat.completion",
        "model": body.model or result["model"],
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "sources": result["sources"],
        "internal_images": result["internal_images"],
    }
    if session_obj is not None:
        resp["session"] = {"session_id": sid, "turns": session_turns}
    return resp
