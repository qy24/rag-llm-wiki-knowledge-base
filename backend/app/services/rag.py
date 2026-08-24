"""RAG 聚合生成服务：文本/视觉统一入口（API 密钥端点与 admin 对话测试台共用）。

流程：检索授权 kb 内知识（文本 + 图谱）→ 组装【参考知识】上下文（含图谱命中）→ 云端模型生成。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import KnowledgeBase
from ..schemas import ChatMessage, content_has_images, content_text, content_to_parts
from . import llm as llm_svc
from .retrieval import format_graph_context, search_knowledge


class LLMError(Exception):
    """LLM 调用相关业务错误（携带 HTTP 状态码）。"""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


# 内置默认回答提示词（全局/密钥未配置提示词时使用）
DEFAULT_ANSWER_SYSTEM = (
    "你是企业客服助手。请以专业、自然、口语化的真人客服口吻回答，严格基于【参考知识】，不要编造。"
    "回答中不要出现[1][2]之类的来源编号或引用标记，不要提及'参考知识''检索'等内部机制。"
    "如参考知识不足以回答，请礼貌说明并给出可操作的后续建议。"
)


def resolve_answer_prompt(settings: Settings, key_prompt: str = "") -> str:
    """回答提示词三级解析：密钥级 > 全局默认 > 代码内置。"""
    return key_prompt.strip() or settings.prompt_answer_system.strip() or DEFAULT_ANSWER_SYSTEM


def rag_chat(db: Session, settings: Settings, kb_ids: list[int],
             messages: list[ChatMessage], top_k: int = 8,
             graph_depth: int = 1, temperature: float = 0.2,
             prompt: str | None = None) -> dict:
    """RAG 聚合生成：检索授权 kb 内知识 → 组装上下文 → 云端模型生成。

    prompt 为回答系统提示词（已按 密钥>全局>内置 解析后的最终值）。
    末条消息含图片时自动走视觉 RAG。返回
    {"answer", "sources", "graph", "internal_images", "search_query", "model", "prompt"}。
    """
    from ..services import vision as vision_svc  # 延迟导入避免循环引用

    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(kb_ids)).all()
    llm = llm_svc.resolve_llm(settings, kbs[0] if kbs else None)
    model_name = llm.model if isinstance(llm, llm_svc.OpenAICompatLLM) else "local"
    last = messages[-1]

    # ===== 视觉 RAG 分支（末条消息带图）=====
    if content_has_images(last.content):
        if isinstance(llm, llm_svc.DummyLLM):
            raise LLMError("未配置云端大模型（请在系统设置中配置 OpenAI 兼容端点）", 503)
        if not llm.supports_vision:
            raise LLMError("当前配置的大模型不支持图片输入（需配置支持视觉的云端模型，如 gpt-4o 系列）", 400)
        try:
            result = vision_svc.visual_chat(
                db, settings, kb_ids, messages,
                top_k=top_k, graph_depth=graph_depth, llm=llm, prompt=prompt,
            )
        except ValueError as e:
            raise LLMError(str(e), 400)  # 图片数量/格式校验失败
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "graph": result.get("graph", {"entities": [], "relations": []}),
            "internal_images": result.get("internal_images", []),
            "search_query": result.get("search_query", ""),
            "model": model_name,
            "prompt": result.get("prompt", "") or "",
        }

    # ===== 文本 RAG 分支 =====
    user_msg = content_text(last.content)
    if not user_msg:
        raise LLMError("消息内容为空", 400)
    if not llm.configured():
        raise LLMError("未配置云端大模型（请在系统设置中配置 OpenAI 兼容端点）", 503)

    result = search_knowledge(
        db, settings, user_msg, kb_ids,
        top_k=top_k, graph_depth=graph_depth, enable_graph=True,
    )
    context_parts = []
    for i, c in enumerate(result["chunks"], 1):
        doc_name = c["metadata"].get("doc_name") or ""
        page = c["metadata"].get("page", "")
        ref = f"{doc_name}" + (f" 第{page}页" if page else "")
        context_parts.append(f"[{i}] {c['content']}\n来源: {ref}")
    context = "\n\n".join(context_parts) if context_parts else "（未检索到相关内容）"
    graph_ctx = format_graph_context(result["graph"])
    if graph_ctx:
        context = context + "\n\n" + graph_ctx

    template = prompt or resolve_answer_prompt(settings)
    system = template + "\n\n【参考知识】\n" + context
    llm_messages: list[dict] = [{"role": "system", "content": system}] + [
        {"role": m.role,
         "content": m.content if isinstance(m.content, str) else content_to_parts(m.content)}
        for m in messages
    ]
    try:
        answer = llm.chat(llm_messages, temperature=temperature)
    except Exception as e:
        print(f"[LLM] chat 生成失败：{type(e).__name__}: {e}", flush=True)
        raise LLMError(f"云端大模型调用失败：{type(e).__name__}（请检查模型配置与账户余额）", 502)

    return {
        "answer": answer,
        "sources": result["chunks"],
        "graph": result["graph"],
        "internal_images": [],
        "search_query": user_msg,
        "model": model_name,
        "prompt": template,
    }
