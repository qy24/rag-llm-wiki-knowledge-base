"""RAG 聚合生成服务：文本/视觉统一入口（API 密钥端点与 admin 对话测试台共用）。

流程：检索授权 kb 内知识（文本 + 图谱）→ 组装【参考知识】上下文（含图谱命中）→ 云端模型生成。
"""
from __future__ import annotations

import re

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


def _text_similarity(a: str, b: str) -> float:
    """字符二元组集合 Jaccard 相似度（中英混排通用）。"""
    def bigrams(s: str):
        s = s.lower()
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}
    A, B = bigrams(a), bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def fetch_good_examples(db, query: str, limit: int = 3, min_sim: float = 0.12) -> list[dict]:
    """进化学习：从审计日志取人工标记 good 且与当前问题相似的问答，作为回复风格参考。"""
    from ..models import AuditLog
    rows = db.query(AuditLog).filter(
        AuditLog.rating == "good",
        AuditLog.action.in_(["chat.completions", "chat.completions.vision", "chat.test"]),
    ).order_by(AuditLog.id.desc()).limit(200).all()
    scored = []
    for r in rows:
        q = (r.query or "").strip()
        ans = ((r.result_summary or {}).get("answer") or "").strip()
        if not q or not ans:
            continue
        sim = _text_similarity(query, q)
        if sim >= min_sim:
            scored.append((sim, q, ans))
    scored.sort(key=lambda x: -x[0])
    return [{"query": q, "answer": a} for _, q, a in scored[:limit]]


# 内置默认回答提示词（全局/密钥未配置提示词时使用）
DEFAULT_ANSWER_SYSTEM = (
    "你是企业客服助手。请以专业、自然、口语化的真人客服口吻回答。\n"
    "【回答原则】\n"
    "0. 语言：用客户消息所使用的语言回复（客户写英文就用英文，写西班牙语就用西班牙语，"
    "写中文就用中文），不要自动换成其他语言；\n"
    "1. 先解决客户当下的问题：仔细阅读客户消息，判断客户已经提供的信息"
    "（订单号、照片、视频、问题描述等），已提供的直接使用，绝不再重复索要；\n"
    "2. 严格基于【参考知识】回答，不编造；与客户问题相关的要点要尽量都用上，不遗漏；\n"
    "3. 客户已提供的信息优先用于推进处理（如已有订单号就跳过确认步骤，直接给方案）；\n"
    "4. 只有确实缺少关键信息时才礼貌索要，且一次说清需要什么；\n"
    "5. 回答中不要出现[1][2]之类的来源编号或引用标记，不要提及'参考知识/检索'等内部机制；\n"
    "6. 如参考知识不足以回答，请礼貌说明并给出可操作的后续建议；\n"
    "7. 用纯文本书写，像真人客服发送的邮件/站内信一样自然——"
    "严禁使用任何 Markdown 符号（如 **、*、- 列表、#、`、~、> 等）和表情符号（emoji）；\n"
    "8. 不要使用省略号（……、...、...... 等）；表达简洁清楚，不啰嗦、不重复；\n"
    "9. 【证据真实性，最高优先】只承认客户消息中实际提供的内容：客户说'已上传/正在附上"
    "图片、视频'但消息里并没有附件时，一律视为尚未收到——绝不声称自己看到了图片/视频"
    "内容或基于不存在的图片下结论；此时应礼貌说明'未收到您的图片/视频'并引导客户重新"
    "发送（如通过售后邮箱），同时可先按文字描述给出排查建议；\n"
    "10. 【回复职责边界，最高优先】区分两类问题："
    "①知识指导类（如何使用、如何安装、故障排查步骤、保养、产品咨询、物流查询解释等）："
    "基于检索知识直接给出详细可操作的回答；"
    "②售后决策类（补发、退货、退款、换货、补偿、包裹丢失索赔等涉及处理决定的诉求）："
    "回复中绝不做任何决定或承诺（不说'已为您补发/退款'），也绝不向客户透露内部流程"
    "（不提'负责人/主管/审批'等字眼）；应先安抚稳住客户——表达理解与歉意、告知"
    "'已收到您的反馈，正在为您核实/跟进处理'、给合理的回复时限；处理决定由内部作出后"
    "再告知客户最终结果。"
)


def _looks_like_multi_turn(text: str) -> bool:
    """启发式判断一段客户消息是否包含多轮往来（多封邮件/平台转达）。
    命中任意一条即视为对话文本，交给模型分析未回复的问题。"""
    t = (text or "").lower()
    greetings = sum(t.count(x) for x in [
        "dear customer", "dear seller", "dear sir", "dear madam",
        "dear amazon", "hello customer", "hi there",
    ])
    signoffs = sum(t.count(x) for x in [
        "best regards", "sincerely", "thanks for your", "thank you for your",
        "kind regards", "looking forward",
    ])
    platform = ("amazon's customer service" in t) or ("amazon customer service" in t
                                                       and "order number" in t)
    # 邮件式往来：至少 2 个问候/落款组合，或含平台转达特征
    if platform:
        return True
    if greetings >= 2 and signoffs >= 1:
        return True
    if greetings >= 1 and signoffs >= 2:
        return True
    # 中英文多段往来兜底：出现多个客服式致歉/致谢标志（说明转述了多轮内容）
    return False


def clean_answer(text: str) -> str:
    """回答后处理清洗：兜底去除 AI 痕迹（Markdown 符号、省略号、来源编号），确保像真人客服文本。

    提示词已约束模型，但不同模型/服务商有时不听话，这里用规则强制清理。
    """
    if not text:
        return text
    # 省略号 / 连续点 → 中文句号
    text = re.sub(r"\.{2,}", "。", text)
    text = re.sub(r"…{1,}", "。", text)
    text = re.sub(r"\.\s*。", "。", text)
    # Markdown 符号
    text = text.replace("**", "")
    text = re.sub(r"^[#>*]\s*", "", text, flags=re.M)  # 行首 #/*/>/=
    text = re.sub(r"`", "", text)
    text = re.sub(r"~{1,}", "", text)
    text = re.sub(r"\n\s*[-•◦]\s+", "\n", text)  # 列表符号
    # 残留来源编号 [1][2]
    text = re.sub(r"\[\d+\]", "", text)
    # 压缩多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def resolve_answer_prompt(settings: Settings, key_prompt: str = "") -> str:
    """回答提示词三级解析：密钥级 > 全局默认 > 代码内置。"""
    return key_prompt.strip() or settings.prompt_answer_system.strip() or DEFAULT_ANSWER_SYSTEM


def rag_chat(db: Session, settings: Settings, kb_ids: list[int],
             messages: list[ChatMessage], top_k: int = 8,
             graph_depth: int = 1, temperature: float = 0.2,
             prompt: str | None = None,
             consult_type: str = "aftersale",
             conversation: str | list[str] | None = None) -> dict:
    """RAG 聚合生成：检索授权 kb 内知识 → 组装上下文 → 云端模型生成。

    consult_type: presale=售前咨询 / aftersale=售后（默认）。
    售前：只按问题给介绍/建议，不涉售后流程、不索要订单号；
    售后：默认订单已存在，直接按问题给解决方案、不因缺订单号卡流程。
    （知识库手册数据已同步含该规则）
    conversation: 调用方传入的多方对话上下文（无角色、按时间顺序，str 或 list[str]），
    用于针对"最新一条未回复的问题"结合整段往来记录作答；None=普通回答。

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
                consult_type=consult_type,
            )
        except ValueError as e:
            raise LLMError(str(e), 400)  # 图片数量/格式校验失败
        return {
            "answer": clean_answer(result["answer"]),
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

    try:
        result = search_knowledge(
            db, settings, user_msg, kb_ids,
            top_k=top_k, graph_depth=graph_depth, enable_graph=True,
        )
    except Exception as e:
        # 检索失败（常见：本地嵌入服务 Ollama 未运行）→ 返回明确原因而非 500
        print(f"[检索] search_knowledge 失败：{type(e).__name__}: {e}", flush=True)
        raise LLMError(f"检索失败：{type(e).__name__}：{str(e)[:150]}"
                       "（若为连接错误，请检查本地嵌入服务 Ollama 是否运行）", 502)
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
    # 售前/售后场景说明（随 API 变量注入；手册数据已含同规则，双重生效）
    if (consult_type or "aftersale") == "presale":
        scene_note = ("【当前客户阶段：售前咨询】直接根据问题提供产品介绍、参数、功能、"
                      "购买建议等回复；不涉及售后流程，不要索要订单号。")
    else:
        scene_note = ("【当前客户阶段：售后处理】默认该客户订单已存在，直接根据问题给出"
                      "解决方案，不因缺少订单号而索要或卡住流程；确需收货地址等补发信息时"
                      "一次性询问即可。")
    # 方案A：附件事实注入（系统可验证的事实，防"声称看到图片"幻觉）——
    # 走到文本分支说明本次消息不含任何图片/视频附件，把这一事实明确告知模型
    evidence_note = ("【附件事实（系统检测，必须遵守）】本次对话的消息均为纯文本，"
                     "不包含任何图片或视频附件。如果客户在文字中说【已上传/正在附上图片】"
                     "等，说明附件实际未收到：不要声称看到了图片/视频内容，应礼貌告知"
                     "尚未收到并引导客户重新发送，同时可按文字描述先给排查建议。")
    # 对话上下文：优先用调用方显式传入的 conversation；未传时若本条 message
    # 明显是多轮往来（含多封邮件特征/平台转达），自动按"对话分析"模式处理
    conv_note = ""
    if conversation:
        conv_items = conversation if isinstance(conversation, list) else [conversation]
        conv_lines = []
        for i, t in enumerate(conv_items, 1):
            t = str(t or "").strip()[:1500]
            if t:
                conv_lines.append(f"[{i}] {t}")
        if conv_lines:
            conv_note = ("【对话上下文（调用方传入，按时间顺序排列的多方往来消息，"
                         "可能包含客户/客服/平台，未标注角色，请自行分辨）】\n"
                         + "\n".join(conv_lines[:20])
                         + "\n\n请通读以上整段对话，理解事情的来龙去脉和已推进到的步骤；"
                           "针对客户最新一条消息回复。回复必须与上下文连贯衔接："
                           "不要重复询问上下文中已经确认或已让客户做过的内容，"
                           "应基于上下文继续推进处理；若上下文显示此事已多次沟通仍无进展，"
                           "回复要体现重视与明确的下一步安排。")
    else:
        # 自动对话检测：客户消息里可能一次性带来多封往来文本（邮件历史/平台转达）
        auto_conv = _looks_like_multi_turn(user_msg)
        if auto_conv:
            conv_note = ("【注意：本条客户消息可能包含一段多方往来对话（客户此前的邮件/"
                         "消息、客服回复、平台转达等，按出现顺序）】请通读分析这段内容："
                         "分辨哪些是问题、哪些已经被回复过；针对其中【尚未被回复的问题】"
                         "给出连贯回复，不要重复询问消息中已经提到过的内容。"
                         "如果这些内容只是客户的一条普通单一问题，按正常情况直接回答即可。")
    system = (template + "\n\n" + scene_note + "\n\n" + evidence_note
              + (("\n\n" + conv_note) if conv_note else "")
              + "\n\n【参考知识】\n" + context)
    # 进化学习：注入相似的历史优质回复作为风格参考（仅参考语气/结构，内容以参考知识为准）
    examples = fetch_good_examples(db, user_msg)
    if examples:
        ex_text = "\n\n".join(
            f"客户问：{e['query']}\n参考回复：{e['answer']}" for e in examples)
        system += ("\n\n【历史优质回复参考】（仅参考语气与结构，不要照抄，"
                   "内容一律以【参考知识】为准）\n" + ex_text)
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
        "answer": clean_answer(answer),
        "sources": result["chunks"],
        "graph": result["graph"],
        "internal_images": [],
        "search_query": user_msg,
        "model": model_name,
        "prompt": template,
    }
