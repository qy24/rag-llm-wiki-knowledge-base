"""视觉 RAG：带图提问 → 图片理解 → 检索内部数据 + 内部相关图片 → 视觉生成回答。

数据流（方案 A，内部图片"被问到才外发"）：
1. 用户附图（data URL / http(s) URL）→ 校验/压缩 → 视觉模型理解成文字描述
2. 描述 + 问题文本 → 现有 search_knowledge 混合检索（文本 + 图谱，权限过滤不变）
3. 从检索结果收集知识库内部相关图片（图片占位块 doc_id + 图谱"图片"实体 image_doc_id，
   且仅限密钥授权 kb 内）→ 本地读图 → 压缩为 base64 data URL
4. 用户原图 + 内部图片 + 检索文字上下文 → 视觉模型生成带来源标注的回答
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Document
from ..schemas import ChatMessage, content_text, content_to_parts
from . import llm as llm_svc
from .rag import DEFAULT_ANSWER_SYSTEM
from .retrieval import format_graph_context, search_knowledge

# 单次请求最多接收的用户附图数量
MAX_USER_IMAGES = 4
# 生成回答时最多附带的知识库内部图片数量
MAX_INTERNAL_IMAGES = 4
# 单张图片原始字节上限（超过直接拒绝，防止超大 base64 拖垮请求/云端成本）
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# 发往云端前统一压缩到的最长边（像素），显著降低视觉 token 成本与延迟
IMAGE_MAX_SIDE = 1024

_MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}


def prepare_content_parts(content: str | list) -> list[dict]:
    """把 ChatMessage.content 转成 dict 片段，校验/压缩用户附图。

    返回完整片段列表（text 原样、image_url 经压缩或透传）。
    校验失败抛 ValueError（调用方转 400）。
    """
    parts = content_to_parts(content)
    out: list[dict] = []
    user_img_count = 0
    for p in parts:
        if p.get("type") == "text":
            out.append(p)
        elif p.get("type") == "image_url":
            url = (p.get("image_url") or {}).get("url") or ""
            if not url:
                raise ValueError("图片片段缺少 image_url.url")
            if url.startswith("http://") or url.startswith("https://"):
                out.append(p)  # 远程 URL 直接透传（由云端模型拉取）
                user_img_count += 1
            elif url.startswith("data:image/"):
                out.append(_compress_data_url_part(p))
                user_img_count += 1
            else:
                raise ValueError("image_url.url 仅支持 data:image/... 或 http(s) 图片地址")
        else:
            raise ValueError(f"不支持的内容片段类型: {p.get('type')}")
    if user_img_count == 0:
        raise ValueError("图片消息必须至少包含一张图片")
    if user_img_count > MAX_USER_IMAGES:
        raise ValueError(f"单次请求最多 {MAX_USER_IMAGES} 张图片")
    return out


def visual_chat(db: Session, settings: Settings, kb_ids: list[int],
                messages: list[ChatMessage], top_k: int = 8,
                graph_depth: int = 1, llm=None, prompt: str | None = None) -> dict:
    """视觉 RAG 主流程（调用方已确认末条消息含图片且 llm 支持视觉）。

    prompt 为回答系统提示词（已按 密钥>全局>内置 解析）；None 时用内置默认。
    返回 {"answer", "search_query", "internal_images", "sources", "graph", "prompt"}。
    """
    if llm is None:
        llm = llm_svc.resolve_llm(settings)
    last = messages[-1]
    parts = prepare_content_parts(last.content)
    user_images = [p for p in parts if p.get("type") == "image_url"]
    text_query = content_text(last.content)

    # 1) 图片理解 → 检索查询（失败回退纯文本，不阻塞回答）
    search_query = text_query
    if user_images:
        try:
            desc = llm_svc.describe_images(llm, user_images, text_query)
            if desc.strip():
                search_query = f"{text_query} {desc}".strip()
        except Exception:
            pass

    # 2) 混合检索（权限过滤与文本路径完全一致）
    result = search_knowledge(
        db, settings, search_query, kb_ids,
        top_k=top_k, graph_depth=graph_depth, enable_graph=True,
    )

    # 3) 收集知识库内部相关图片（仅授权 kb 内）
    internal = _collect_internal_images(db, kb_ids, result)

    # 4) 组装文字上下文（文本块 + 图谱命中，纯图谱库也能回答"有哪些数据"）
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
    template = prompt or DEFAULT_ANSWER_SYSTEM
    system = template + "\n\n【参考知识】\n" + context

    # 5) 视觉生成：历史消息原样转发 + 末条消息（已压缩的用户附图）追加内部图片
    llm_messages: list[dict] = [{"role": "system", "content": system}]
    for m in messages[:-1]:
        llm_messages.append({"role": m.role, "content": content_to_parts(m.content)})
    last_parts = parts  # prepare_content_parts 已压缩用户附图
    if internal:
        internal_parts: list[dict] = [
            {"type": "text", "text": "（以下为本地知识库检索到的相关图片，请结合看图回答）"}
        ]
        for img in internal:
            internal_parts.append({"type": "image_url",
                                   "image_url": {"url": img["data_url"]}})
        last_parts = last_parts + internal_parts
    llm_messages.append({"role": last.role, "content": last_parts})

    answer = llm.chat(llm_messages, temperature=0.2)
    return {
        "answer": answer,
        "search_query": search_query,
        "internal_images": [{"doc_id": i["doc_id"], "filename": i["filename"]}
                            for i in internal],
        "sources": result["chunks"],
        "graph": result["graph"],
        "prompt": template,
    }


def _collect_internal_images(db: Session, kb_ids: list[int], result: dict) -> list[dict]:
    """从检索结果收集知识库内部图片：
    - 切分块 meta.image=True（图片占位块）的 doc_id
    - 图谱中 type=图片 的实体（properties.image_doc_id）
    仅取 Document.kb_id 在授权 kb_ids 内的记录，保持租户隔离。
    """
    doc_ids: set[int] = set()
    for c in result["chunks"]:
        if c.get("metadata", {}).get("image") and c.get("doc_id"):
            doc_ids.add(c["doc_id"])
    for e in result["graph"].get("entities", []):
        if str(e.get("type", "")) == "图片":
            pid = (e.get("properties") or {}).get("image_doc_id")
            if pid:
                try:
                    doc_ids.add(int(pid))
                except (TypeError, ValueError):
                    pass
    if not doc_ids:
        return []
    docs = db.query(Document).filter(
        Document.id.in_(doc_ids), Document.kb_id.in_(kb_ids)).all()
    out: list[dict] = []
    for d in docs:
        if not d.file_path or not Path(d.file_path).exists():
            continue
        try:
            data_url = _file_to_data_url(d.file_path, d.filename)
        except Exception:
            continue
        out.append({"doc_id": d.id, "filename": d.filename, "data_url": data_url})
        if len(out) >= MAX_INTERNAL_IMAGES:
            break
    return out


def _compress_data_url_part(part: dict) -> dict:
    """用户附图（data URL）：解码 → 压缩 → 重编码 JPEG；失败则原样透传。"""
    url = part["image_url"]["url"]
    b64 = url.split(",", 1)[1] if "," in url else ""
    if not b64 or len(b64) > int(MAX_IMAGE_BYTES * 4 / 3) + 1024:
        raise ValueError("图片过大（单张上限 8MB）")
    raw = base64.b64decode(b64)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("图片过大（单张上限 8MB）")
    try:
        return {"type": "image_url",
                "image_url": {"url": _bytes_to_data_url(raw, "image/jpeg")}}
    except Exception:
        return part  # 非标准图像数据 → 原样透传，交给模型端处理


def _file_to_data_url(file_path: str, filename: str) -> str:
    raw = Path(file_path).read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"图片过大（{filename}）")
    mime = _MIME_BY_EXT.get(Path(filename).suffix.lower(), "image/jpeg")
    try:
        return _bytes_to_data_url(raw, mime)
    except Exception:
        return "data:" + mime + ";base64," + base64.b64encode(raw).decode()


def _bytes_to_data_url(raw: bytes, mime: str) -> str:
    """Pillow 压缩（最长边 IMAGE_MAX_SIDE，JPEG q85）；Pillow 不可用则原样 base64。"""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > IMAGE_MAX_SIDE:
            img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        return "data:" + mime + ";base64," + base64.b64encode(raw).decode()
