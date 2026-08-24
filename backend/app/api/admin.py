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
from ..deps import get_current_user
from ..models import ApiKey, AppSetting, Chunk, Document, KnowledgeBase, Task, User
from ..schemas import (
    AdminChatIn,
    ChunkOut,
    ChunkUpdateIn,
    DocumentOut,
    EntityCreateIn,
    EntityMergeIn,
    EntityUpdateIn,
    KBIn,
    KBOut,
    KeyIn,
    KeyOut,
    RelationCreateIn,
    RelationUpdateIn,
    SearchIn,
    SettingsIn,
    SettingsOut,
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
def create_kb(body: KBIn, user: User = Depends(get_current_user),
              db: Session = Depends(get_db), request: Request = None):
    kb = KnowledgeBase(owner_user_id=user.id, **body.model_dump())
    db.add(kb)
    db.commit()
    db.refresh(kb)
    _audit(db, user, "create_kb", summary={"kb_id": kb.id, "name": kb.name}, request=request)
    return kb


@router.patch("/kbs/{kb_id}", response_model=KBOut)
def update_kb(kb_id: int, body: KBIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user), request: Request = None):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    for k, v in body.model_dump().items():
        setattr(kb, k, v)
    db.commit()
    db.refresh(kb)
    _audit(db, user, "update_kb", summary={"kb_id": kb_id}, request=request)
    return kb


@router.delete("/kbs/{kb_id}")
def delete_kb(kb_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user), request: Request = None):
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
                          user: User = Depends(get_current_user),
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
                    user: User = Depends(get_current_user), request: Request = None):
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


@router.post("/documents/{doc_id}/reparse", response_model=DocumentOut)
def reparse_document(doc_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user), request: Request = None):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    doc.status = "排队中"
    doc.error_msg = ""
    db.commit()
    db.add(Task(type="process_document", params={"doc_id": doc_id}))
    db.commit()
    start_worker()
    _audit(db, user, "reparse_document", summary={"doc_id": doc_id}, request=request)
    return doc


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
                 user: User = Depends(get_current_user), request: Request = None):
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
                  user: User = Depends(get_current_user), request: Request = None):
    eid = get_graph_store(settings).upsert_entity(
        kb_id=kb_id, name=body.name, etype=body.type, properties=body.properties,
        source_doc_id=None, source_chunk_id=None)
    _audit(db, user, "create_entity", summary={"kb_id": kb_id, "entity_id": eid}, request=request)
    return {"id": eid}


@router.patch("/entities/{entity_id}")
def update_entity(entity_id: str, body: EntityUpdateIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user), request: Request = None):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    get_graph_store(settings).update_entity(entity_id, fields)
    _audit(db, user, "update_entity", summary={"entity_id": entity_id}, request=request)
    return {"ok": True}


@router.delete("/entities/{entity_id}")
def delete_entity(entity_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user), request: Request = None):
    get_graph_store(settings).delete_entity(entity_id)
    _audit(db, user, "delete_entity", summary={"entity_id": entity_id}, request=request)
    return {"ok": True}


@router.post("/entities/merge")
def merge_entities(body: EntityMergeIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user), request: Request = None):
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
                    user: User = Depends(get_current_user), request: Request = None):
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
    _audit(db, user, "create_relation", summary={"kb_id": kb_id, "relation_id": rid}, request=request)
    return {"id": rid}


@router.patch("/relations/{relation_id}")
def update_relation(relation_id: str, body: RelationUpdateIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user), request: Request = None):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    get_graph_store(settings).update_relation(relation_id, fields)
    _audit(db, user, "update_relation", summary={"relation_id": relation_id}, request=request)
    return {"ok": True}


@router.delete("/relations/{relation_id}")
def delete_relation(relation_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user), request: Request = None):
    get_graph_store(settings).delete_relation(relation_id)
    _audit(db, user, "delete_relation", summary={"relation_id": relation_id}, request=request)
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
               user: User = Depends(get_current_user), request: Request = None):
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
               user: User = Depends(get_current_user), request: Request = None):
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
               user: User = Depends(get_current_user), request: Request = None):
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "密钥不存在")
    key.revoked = True
    db.commit()
    _audit(db, user, "revoke_key", summary={"key_id": key_id}, request=request)
    return {"ok": True}


# ---------- 检索调试（管理员视角，指定知识库） ----------
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
    _audit(db, user, "debug.search", body.query,
           {"hits": len(result["chunks"])}, request=request)
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
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ], "total": total}


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
    """对话测试台：选 API 密钥 → 检索范围=密钥绑定 KB（不越权）、提示词=密钥配置。"""
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
        )
    except LLMError as e:
        raise HTTPException(e.status_code, str(e))
    _audit(db, user, "chat.test",
           content_text(body.messages[-1].content)[:500],
           {"api_key_id": key.id, "kb_ids": list(key.allowed_kb_ids),
            "hits": len(result["sources"]), "answer_len": len(result["answer"])},
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
                        user: User = Depends(get_current_user), request: Request = None):
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
