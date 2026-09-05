"""管理端 API（管理员 JWT 鉴权）：知识库/文档/切分块/实体关系/密钥/审计/设置/统计。"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import ApiKey, AppSetting, Chunk, Document, KnowledgeBase, Task, User
from ..schemas import (
    AdminChatIn,
    AuditUpdateIn,
    ChunkOut,
    ChunkUpdateIn,
    DocumentOut,
    EntityCreateIn,
    EntityMergeIn,
    EntityUpdateIn,
    KBIn,
    KBOut,
    KBUpdateIn,
    KeyIn,
    KeyOut,
    RelationCreateIn,
    RelationUpdateIn,
    SearchIn,
    SettingsIn,
    SettingsOut,
    resolve_consult_type,
    content_text,
)
from ..security import generate_api_key, hash_api_key
from ..services import parsing
from ..services.rag import LLMError, rag_chat
from ..stores import get_graph_store, get_vector_store
from ..workers import start_worker

router = APIRouter(dependencies=[Depends(get_current_user)])
settings = get_settings()


def _audit(db: Session, user: User, action: str, query: str = "", summary: dict | None = None,
           api_key_id: int | None = None, request: Request | None = None):
    # 只保留"对话类"审计（含客户问题与回复，供进化学习参考）；
    # 管理操作（密钥/知识库/文档/设置/图谱编辑等）不再写审计——
    # 它们没有 query/answer，会刷出大量空白记录（用户反馈"空余消息"）
    if action != "chat.test":
        return
    from ..models import AuditLog
    db.add(AuditLog(
        api_key_id=api_key_id, user_id=user.id, action=action, query=query,
        result_summary=summary or {}, ip=request.client.host if request else "",
    ))
    db.commit()


# ---------- 知识库 ----------
@router.get("/kbs", response_model=list[KBOut])
def list_kbs(db: Session = Depends(get_db)):
    return db.query(KnowledgeBase).order_by(KnowledgeBase.id).all()


@router.post("/kbs", response_model=KBOut)
def create_kb(body: KBIn, user: User = Depends(require_admin),
              db: Session = Depends(get_db), request: Request = None):
    kb = KnowledgeBase(owner_user_id=user.id, **body.model_dump())
    db.add(kb)
    db.commit()
    db.refresh(kb)
    _audit(db, user, "create_kb", summary={"kb_id": kb.id, "name": kb.name}, request=request)
    return kb


@router.patch("/kbs/{kb_id}", response_model=KBOut)
def update_kb(kb_id: int, body: KBUpdateIn, db: Session = Depends(get_db),
              user: User = Depends(require_admin), request: Request = None):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    # 只更新调用方传入的字段（如图谱页仅传 layout_type 切换布局）
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(kb, k, v)
    db.commit()
    db.refresh(kb)
    _audit(db, user, "update_kb", summary={"kb_id": kb_id}, request=request)
    return kb


@router.delete("/kbs/{kb_id}")
def delete_kb(kb_id: int, db: Session = Depends(get_db),
              user: User = Depends(require_admin), request: Request = None):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    get_vector_store(settings).delete_by_kb(kb_id)
    get_graph_store(settings).delete_by_kb(kb_id)
    db.query(Chunk).filter(Chunk.kb_id == kb_id).delete()
    db.query(Document).filter(Document.kb_id == kb_id).delete()
    db.delete(kb)
    db.commit()
    _audit(db, user, "delete_kb", summary={"kb_id": kb_id}, request=request)
    return {"ok": True}


# ---------- 文档 ----------
@router.post("/kbs/{kb_id}/documents", response_model=DocumentOut)
async def upload_document(kb_id: int, file: UploadFile = File(...),
                          db: Session = Depends(get_db),
                          user: User = Depends(require_admin),
                          request: Request = None):
    if db.get(KnowledgeBase, kb_id) is None:
        raise HTTPException(404, "知识库不存在")
    if not parsing.is_supported(file.filename or ""):
        raise HTTPException(400, f"不支持的文件类型: {(file.filename or '').rsplit('.', 1)[-1]}")
    doc_dir = settings.data_dir_path / "documents" / str(kb_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in (file.filename or "file") if c not in '\\/:*?"<>|') or "file"
    target = doc_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{safe_name}"
    content = await file.read()
    target.write_bytes(content)
    doc = Document(
        kb_id=kb_id, filename=safe_name, file_path=str(target),
        file_size=len(content),
        file_type=safe_name.rsplit(".", 1)[-1].lower(),
        status="排队中",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    db.add(Task(type="process_document", params={"doc_id": doc.id}))
    db.commit()
    start_worker()
    _audit(db, user, "upload_document", summary={"doc_id": doc.id, "filename": safe_name},
           request=request)
    return doc


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(kb_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Document)
    if kb_id is not None:
        q = q.filter(Document.kb_id == kb_id)
    return q.order_by(Document.id.desc()).limit(500).all()


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    return doc


@router.get("/documents/{doc_id}/file")
def get_document_file(doc_id: int, db: Session = Depends(get_db)):
    """返回文档原件（图片/表格等），供前端图谱查看原图。"""
    doc = db.get(Document, doc_id)
    if doc is None or not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(doc.file_path, filename=doc.filename)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_admin), request: Request = None):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    get_vector_store(settings).delete_by_doc(doc_id)
    get_graph_store(settings).delete_by_doc(doc_id)
    db.query(Chunk).filter(Chunk.doc_id == doc_id).delete()
    db.query(Task).filter(Task.params.contains({"doc_id": doc_id})).delete()
    path = doc.file_path
    db.delete(doc)
    db.commit()
    try:
        shutil.rmtree(str(path), ignore_errors=True)
        if path and path != str(doc.file_path):
            pass
    except Exception:
        pass
    _audit(db, user, "delete_document", summary={"doc_id": doc_id}, request=request)
    return {"ok": True}


# ---------- 切分块 ----------
@router.get("/kbs/{kb_id}/chunks", response_model=list[ChunkOut])
def list_chunks(kb_id: int, doc_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Chunk).filter(Chunk.kb_id == kb_id)
    if doc_id is not None:
        q = q.filter(Chunk.doc_id == doc_id)
    return q.order_by(Chunk.doc_id, Chunk.seq).limit(2000).all()


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
def get_chunk(chunk_id: int, db: Session = Depends(get_db)):
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(404, "切分块不存在")
    return chunk


@router.patch("/chunks/{chunk_id}", response_model=ChunkOut)
def update_chunk(chunk_id: int, body: ChunkUpdateIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin), request: Request = None):
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(404, "切分块不存在")
    chunk.content = body.content
    chunk.embedding_status = "pending"
    db.commit()
    db.refresh(chunk)
    db.add(Task(type="reembed_chunk", params={"chunk_id": chunk_id}))
    db.commit()
    start_worker()
    _audit(db, user, "update_chunk", summary={"chunk_id": chunk_id}, request=request)
    return chunk


# ---------- 实体 / 关系（图存储） ----------
@router.get("/kbs/{kb_id}/entities")
def list_entities(kb_id: int, limit: int = 100, offset: int = 0,
                  db: Session = Depends(get_db)):
    entities, total = get_graph_store(settings).list_entities(kb_id, min(limit, 500), offset)
    return {"items": entities, "total": total}


@router.post("/kbs/{kb_id}/entities")
def create_entity(kb_id: int, body: EntityCreateIn, db: Session = Depends(get_db),
                  user: User = Depends(require_admin), request: Request = None):
    # 图谱实体/关系增删不写审计：图谱内容以 graph 存储本身为准，
    # 批量建图/手工整理会逐条刷屏（曾占审计 60%+）
    eid = get_graph_store(settings).upsert_entity(
        kb_id=kb_id, name=body.name, etype=body.type, properties=body.properties,
        source_doc_id=None, source_chunk_id=None)
    return {"id": eid}


@router.patch("/entities/{entity_id}")
def update_entity(entity_id: str, body: EntityUpdateIn, db: Session = Depends(get_db),
                  user: User = Depends(require_admin), request: Request = None):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    get_graph_store(settings).update_entity(entity_id, fields)
    # 纯坐标更新（图谱画布拖拽/自动布局产生的 x/y）不写审计——高频噪音，会刷屏审计日志
    props = fields.get("properties") or {}
    is_pure_position = set(fields.keys()) <= {"properties"} and set(props.keys()) <= {"x", "y"}
    if not is_pure_position:
        _audit(db, user, "update_entity", summary={"entity_id": entity_id}, request=request)
    return {"ok": True}


@router.delete("/entities/{entity_id}")
def delete_entity(entity_id: str, db: Session = Depends(get_db),
                  user: User = Depends(require_admin), request: Request = None):
    get_graph_store(settings).delete_entity(entity_id)
    return {"ok": True}


@router.post("/entities/merge")
def merge_entities(body: EntityMergeIn, db: Session = Depends(get_db),
                   user: User = Depends(require_admin), request: Request = None):
    if body.source_id == body.target_id:
        raise HTTPException(400, "不能合并到自身")
    try:
        get_graph_store(settings).merge_entities(body.source_id, body.target_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    _audit(db, user, "merge_entities",
           summary={"source_id": body.source_id, "target_id": body.target_id}, request=request)
    return {"ok": True}


@router.get("/kbs/{kb_id}/relations")
def list_relations(kb_id: int, limit: int = 100, offset: int = 0,
                   db: Session = Depends(get_db)):
    relations, total = get_graph_store(settings).list_relations(kb_id, min(limit, 500), offset)
    return {"items": relations, "total": total}


@router.post("/kbs/{kb_id}/relations")
def create_relation(kb_id: int, body: RelationCreateIn, db: Session = Depends(get_db),
                    user: User = Depends(require_admin), request: Request = None):
    """前端按实体 ID 建关系：先按 ID 解析实体，再按名称写入图库（图库存按名称去重）。"""
    gstore = get_graph_store(settings)
    src = gstore.get_entity(body.source_entity_id)
    tgt = gstore.get_entity(body.target_entity_id)
    if src is None or tgt is None:
        raise HTTPException(404, "实体不存在，可能已被删除，请刷新图谱后重试")
    if src.get("kb_id") != kb_id or tgt.get("kb_id") != kb_id:
        raise HTTPException(400, "关系两端实体必须属于当前知识库")
    try:
        rid = gstore.upsert_relation(
            kb_id=kb_id, src_name=src["name"], tgt_name=tgt["name"],
            rel_type=body.relation_type, properties=body.properties,
            source_doc_id=None, source_chunk_id=None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": rid}


@router.patch("/relations/{relation_id}")
def update_relation(relation_id: str, body: RelationUpdateIn, db: Session = Depends(get_db),
                    user: User = Depends(require_admin), request: Request = None):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    get_graph_store(settings).update_relation(relation_id, fields)
    _audit(db, user, "update_relation", summary={"relation_id": relation_id}, request=request)
    return {"ok": True}


@router.delete("/relations/{relation_id}")
def delete_relation(relation_id: str, db: Session = Depends(get_db),
                    user: User = Depends(require_admin), request: Request = None):
    get_graph_store(settings).delete_relation(relation_id)
    return {"ok": True}


# ---------- API 密钥 ----------
@router.get("/keys", response_model=list[KeyOut])
def list_keys(db: Session = Depends(get_db)):
    keys = db.query(ApiKey).order_by(ApiKey.id).all()
    out = []
    for k in keys:
        item = KeyOut.model_validate(k)
        out.append(item)
    return out


@router.post("/keys", response_model=KeyOut)
def create_key(body: KeyIn, db: Session = Depends(get_db),
               user: User = Depends(require_admin), request: Request = None):
    if body.key_type not in ("search", "ingest", "full"):
        raise HTTPException(400, "key_type 只能是 search/ingest/full")
    plain = generate_api_key()
    key = ApiKey(
        user_id=user.id, name=body.name, key_type=body.key_type,
        key_hash=hash_api_key(plain), allowed_kb_ids=body.allowed_kb_ids,
        expires_at=body.expires_at, prompt_template=body.prompt_template,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    out = KeyOut.model_validate(key)
    out.key = plain  # 明文仅此一次
    _audit(db, user, "create_key", summary={"key_id": key.id, "name": key.name}, request=request)
    return out


@router.patch("/keys/{key_id}", response_model=KeyOut)
def update_key(key_id: int, body: KeyIn, db: Session = Depends(get_db),
               user: User = Depends(require_admin), request: Request = None):
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "密钥不存在")
    key.name = body.name
    key.allowed_kb_ids = body.allowed_kb_ids
    key.expires_at = body.expires_at
    key.prompt_template = body.prompt_template
    db.commit()
    db.refresh(key)
    _audit(db, user, "update_key", summary={"key_id": key_id}, request=request)
    return key


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_admin), request: Request = None):
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "密钥不存在")
    key.revoked = True
    db.commit()
    _audit(db, user, "revoke_key", summary={"key_id": key_id}, request=request)
    return {"ok": True}


@router.post("/keys/{key_id}/restore")
def restore_key(key_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_admin), request: Request = None):
    """恢复已吊销的密钥（吊销可逆）。"""
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "密钥不存在")
    key.revoked = False
    db.commit()
    _audit(db, user, "restore_key", summary={"key_id": key_id}, request=request)
    return {"ok": True}


@router.delete("/keys/{key_id}")
def delete_key(key_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_admin), request: Request = None):
    """物理删除密钥：审计记录保留但解除该密钥归属；该密钥的会话记忆一并清除。"""
    from ..models import AuditLog, ChatSession
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "密钥不存在")
    db.query(AuditLog).filter(AuditLog.api_key_id == key_id).update(
        {AuditLog.api_key_id: None})
    db.query(ChatSession).filter(ChatSession.api_key_id == key_id).delete()
    db.delete(key)
    db.commit()
    _audit(db, user, "delete_key", summary={"key_id": key_id}, request=request)
    return {"ok": True}


# ---------- 检索调试（管理员视角，指定知识库；纯查看，只读账号可用） ----------
@router.post("/kbs/{kb_id}/debug-search")
def debug_search(kb_id: int, body: SearchIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user), request: Request = None):
    if db.get(KnowledgeBase, kb_id) is None:
        raise HTTPException(404, "知识库不存在")
    from ..services.retrieval import search_knowledge
    result = search_knowledge(
        db, settings, body.query, [kb_id], top_k=body.top_k,
        graph_depth=body.graph_depth, enable_graph=body.enable_graph,
    )
    # 调试台检索不写审计（管理员自查噪音，曾占审计 26%）
    return result


# ---------- 审计 / 任务 / 统计 / 设置 ----------
@router.get("/audit")
def list_audit(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    from ..models import AuditLog
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).offset(offset).limit(min(limit, 500)).all()
    total = db.query(AuditLog).count()
    return {"items": [
        {"id": r.id, "action": r.action, "query": r.query,
         "result_summary": r.result_summary, "ip": r.ip,
         "rating": r.rating or "", "note": r.note or "",
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ], "total": total}


@router.patch("/audit/{audit_id}")
def update_audit(audit_id: int, body: AuditUpdateIn, db: Session = Depends(get_db),
                 user: User = Depends(require_admin), request: Request = None):
    """审计记录打标（进化学习）：rating=good（回复好可学习）/bad（回复差需复盘）/''；
    note 记录备注。打标不写审计（避免自我刷屏）。"""
    from ..models import AuditLog
    row = db.get(AuditLog, audit_id)
    if row is None:
        raise HTTPException(404, "审计记录不存在")
    if body.rating is not None:
        if body.rating not in ("good", "bad", ""):
            raise HTTPException(400, "rating 只能是 good/bad/空")
        row.rating = body.rating
    if body.note is not None:
        row.note = body.note
    db.commit()
    return {"ok": True}


SELFLEARN_KB_ID = 4  # 「自我学习」库：投喂回复范例 + 中文处理经验


@router.post("/selflearn/case")
def selflearn_case(body: dict, db: Session = Depends(get_db),
                   user: User = Depends(require_admin), request: Request = None):
    """把审计中打标 good 的对话沉淀进「自我学习」库（kb4）：
    自动提炼中文处理经验 → 生成案例文档 → 走 pipeline 切分/向量入库。
    body: {"audit_id": 123}；幂等（同一条审计只入库一次）。"""
    from ..models import AuditLog, Document, Task as TaskModel
    audit_id = int((body or {}).get("audit_id") or 0)
    if audit_id <= 0:
        raise HTTPException(400, "缺少 audit_id")
    row = db.get(AuditLog, audit_id)
    if row is None:
        raise HTTPException(404, "审计记录不存在")
    if row.rating != "good":
        raise HTTPException(400, "只有标记为「好·可学习」的记录才能存入学习库")
    summary = row.result_summary or {}
    query = (row.query or "").strip()
    answer = (summary.get("answer") or "").strip()
    note = (row.note or "").strip()
    if not query or not answer:
        raise HTTPException(400, "该记录没有客户问题或回复内容，无法入库")

    # 幂等：同一审计已入库则跳过
    existing = db.query(Document).filter(
        Document.kb_id == SELFLEARN_KB_ID,
        Document.filename.like(f"%audit{audit_id}-%"),
    ).first()
    if existing is not None:
        return {"ok": True, "skipped": True, "doc_id": existing.id}

    # 用云端 LLM 提炼中文处理经验（失败则占位，不影响入库）
    zh_experience = ""
    try:
        from ..services import llm as llm_svc
        llm = llm_svc.resolve_llm(settings)
        if llm.configured():
            prompt = (
                "你是售后客服经验总结助手。根据下面的客户问题与客服回复，"
                "用简洁中文总结【处理经验】：这是什么类型的问题、核心处理逻辑与步骤、"
                "话术要点。100字以内，只输出总结内容。\n\n"
                f"客户问题：{query}\n客服回复：{answer[:1500]}"
            )
            zh = (llm.chat([{"role": "user", "content": prompt}],
                           temperature=0.1, max_tokens=300, timeout=90) or "").strip()
            zh_experience = zh if zh else ""
    except Exception as exc:
        print(f"[selflearn] 经验提炼失败（仍入库）: {str(exc)[:100]}", flush=True)
        zh_experience = ""
    if not zh_experience:
        zh_experience = "（自动提炼失败，请人工补充中文处理经验；参考下方原文）"

    doc_md = (
        f"# 自动沉淀案例（审计 #{audit_id}）\n\n"
        f"> 来源：审计日志标记「好·可学习」（{row.created_at}）｜自动沉淀到「自我学习」库\n\n"
        f"## 问题类型：{query[:60]}\n\n"
        f"### 中文处理经验\n\n{zh_experience}\n\n"
        f"### 客户问题\n\n{query}\n\n"
        f"### 参考回复（原文）\n\n{answer}\n"
    )
    if note:
        doc_md += f"\n### 备注\n\n{note}\n"

    # 写入 kb4 文档目录并排队入库（复用 upload 流程）
    kb = db.get(KnowledgeBase, SELFLEARN_KB_ID)
    if kb is None:
        raise HTTPException(404, "「自我学习」知识库不存在")
    doc_dir = settings.data_dir_path / "documents" / str(SELFLEARN_KB_ID)
    doc_dir.mkdir(parents=True, exist_ok=True)
    fname = f"audit{audit_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.md"
    target = doc_dir / fname
    target.write_text(doc_md, encoding="utf-8")
    doc = Document(
        kb_id=SELFLEARN_KB_ID, filename=fname, file_path=str(target),
        file_size=len(doc_md.encode("utf-8")), file_type="md", status="排队中",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    db.add(TaskModel(type="process_document", params={"doc_id": doc.id}))
    db.commit()
    from ..workers import start_worker
    start_worker()
    return {"ok": True, "skipped": False, "doc_id": doc.id}


@router.get("/sessions")
def list_sessions(api_key_id: int | None = None, limit: int = 100,
                  db: Session = Depends(get_db)):
    """多客户会话记忆列表（按密钥过滤可选；仅查看）。"""
    from ..models import ChatSession
    q = db.query(ChatSession)
    if api_key_id is not None:
        q = q.filter(ChatSession.api_key_id == api_key_id)
    rows = q.order_by(ChatSession.updated_at.desc()).limit(min(limit, 500)).all()
    items = []
    for s in rows:
        msgs = s.messages or []
        last_user = next((m.get("content", "") for m in reversed(msgs)
                          if m.get("role") == "user"), "")
        items.append({
            "id": s.id, "api_key_id": s.api_key_id,
            "session_id": s.session_id,
            "turns": len(msgs) // 2,
            "last_query": str(last_user)[:200],
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })
    return {"items": items, "total": len(items)}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_admin), request: Request = None):
    """删除某客户的会话记忆（清空后该客户重新开始，无历史上下文）。"""
    from ..models import ChatSession
    s = db.get(ChatSession, session_id)
    if s is None:
        raise HTTPException(404, "会话不存在")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/tasks")
def list_tasks(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(Task).order_by(Task.id.desc()).limit(min(limit, 500)).all()
    return [{"id": t.id, "type": t.type, "status": t.status, "progress": t.progress,
             "params": t.params, "error_msg": t.error_msg,
             "created_at": t.created_at.isoformat() if t.created_at else None}
            for t in rows]


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    gstore = get_graph_store(settings)
    vstore = get_vector_store(settings)
    entities, relations = gstore.count()
    doc_status = {}
    for status, count in db.query(Document.status, __import__("sqlalchemy").func.count()).group_by(Document.status).all():
        doc_status[status] = count
    return {
        "kb_count": db.query(KnowledgeBase).count(),
        "doc_count": db.query(Document).count(),
        "chunk_count": db.query(Chunk).count(),
        "vector_count": vstore.count(),
        "entity_count": entities,
        "relation_count": relations,
        "doc_status": doc_status,
        "pending_tasks": db.query(Task).filter(Task.status.in_(["pending", "running"])).count(),
    }


@router.post("/chat")
def admin_chat(body: AdminChatIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user), request: Request = None):
    """对话测试台：选 API 密钥 → 检索范围=密钥绑定 KB（不越权）、提示词=密钥配置。
    只读账号（viewer）也可用（纯问答体验，无数据修改）；调用会记入审计 chat.test。"""
    key = db.get(ApiKey, body.api_key_id)
    if key is None:
        raise HTTPException(404, "密钥不存在")
    if key.revoked:
        raise HTTPException(400, "该密钥已吊销")
    if key.expires_at is not None and key.expires_at < datetime.now():
        raise HTTPException(400, "该密钥已过期")
    if not key.allowed_kb_ids:
        raise HTTPException(400, "该密钥未绑定任何知识库，无法检索")
    try:
        result = rag_chat(
            db, settings, list(key.allowed_kb_ids), body.messages,
            top_k=body.top_k, graph_depth=body.graph_depth,
            temperature=body.temperature,
            prompt=key.prompt_template or None,
            consult_type=resolve_consult_type(body.consult_type, body.is_after_sale),
            conversation=body.context,
        )
    except LLMError as e:
        raise HTTPException(e.status_code, str(e))
    _audit(db, user, "chat.test",
           content_text(body.messages[-1].content)[:500],
           {"api_key_id": key.id, "key_name": key.name, "kb_ids": list(key.allowed_kb_ids),
            "hits": len(result["sources"]), "answer_len": len(result["answer"]),
            "answer": result["answer"][:800]},
           api_key_id=key.id, request=request)
    result["api_key_id"] = key.id
    result["scope_kb_ids"] = list(key.allowed_kb_ids)
    if key.prompt_template.strip():
        result["prompt_source"] = "key"
    elif settings.prompt_answer_system.strip():
        result["prompt_source"] = "global"
    else:
        result["prompt_source"] = "builtin"
    return result


@router.post("/settings/test")
def test_settings_api(db: Session = Depends(get_db),
                      user: User = Depends(require_admin), request: Request = None):
    """测试当前嵌入/大模型配置连通性（前端系统设置页「测试连接」按钮）。"""
    import time as _time
    results: dict = {}

    # 嵌入测试
    from ..services.embedding import get_embedder
    try:
        embedder = get_embedder(settings)
        t0 = _time.time()
        vec = embedder.embed_documents(["连接测试"])[0]
        results["embedding"] = {
            "ok": True, "ms": round((_time.time() - t0) * 1000),
            "dim": len(vec), "model": settings.embedding_model,
        }
    except Exception as e:
        hint = ""
        if "11434" in settings.embedding_base_url or "localhost" in settings.embedding_base_url:
            hint = "；本地嵌入服务（Ollama）未运行？已配置开机自启，可先手动启动 ollama serve"
        results["embedding"] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:150]}{hint}",
            "model": settings.embedding_model,
        }

    # 大模型测试
    from ..services import llm as llm_svc
    try:
        llm = llm_svc.resolve_llm(settings)
        t0 = _time.time()
        ans = llm.chat([{"role": "user", "content": "你好"}], max_tokens=512, timeout=120)
        results["llm"] = {
            "ok": True, "ms": round((_time.time() - t0) * 1000),
            "model": llm.model, "reply": (ans or "（回复为空）")[:30],
        }
    except Exception as e:
        results["llm"] = {
            "ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}",
            "model": settings.llm_model,
        }
    _audit(db, user, "test_settings",
           summary={"embedding_ok": results["embedding"]["ok"], "llm_ok": results["llm"]["ok"]},
           request=request)
    return results


@router.get("/settings", response_model=SettingsOut)
def get_settings_api(db: Session = Depends(get_db)):
    mask = lambda s: (s[:4] + "****" + s[-4:]) if len(s) > 10 else "****"
    return SettingsOut(
        embedding_mode=settings.embedding_mode,
        embedding_base_url=settings.embedding_base_url,
        embedding_model=settings.embedding_model,
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        graph_extraction_enabled=settings.graph_extraction_enabled,
        prompt_answer_system=settings.prompt_answer_system,
        embedding_api_key_masked=mask(settings.embedding_api_key) if settings.embedding_api_key else "",
        llm_api_key_masked=mask(settings.llm_api_key) if settings.llm_api_key else "",
    )


@router.put("/settings", response_model=SettingsOut)
def update_settings_api(body: SettingsIn, db: Session = Depends(get_db),
                        user: User = Depends(require_admin), request: Request = None):
    for k, v in body.model_dump(exclude_none=True).items():
        if hasattr(settings, k):
            setattr(settings, k, v)
    # 持久化到 app_settings 表（重启后由 main 加载）
    row = db.get(AppSetting, "runtime")
    if row is None:
        row = AppSetting(key="runtime", value={})
        db.add(row)
    row.value = {k: getattr(settings, k) for k in (
        "embedding_mode", "embedding_base_url", "embedding_api_key", "embedding_model",
        "llm_base_url", "llm_api_key", "llm_model", "graph_extraction_enabled",
        "prompt_answer_system",
    )}
    db.commit()
    _audit(db, user, "update_settings", request=request)
    return get_settings_api(db)
