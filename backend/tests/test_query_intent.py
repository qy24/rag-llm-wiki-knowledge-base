# -*- coding: utf-8 -*-
"""排除语义回归测试：查询理解层解析出 exclude 后，结果剔除排除对象及其相连实体"""
import os
import shutil

os.environ["DATA_DIR"] = "./test_intent_data"
os.environ["DATABASE_URL"] = "sqlite:///./test_intent.db"
os.environ["EMBEDDING_MODE"] = "dummy"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["GRAPH_BACKEND"] = "local"

for p in ("test_intent_data", "test_intent.db", "test_intent.db-wal", "test_intent.db-shm"):
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
    elif os.path.exists(p):
        os.remove(p)

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.services import llm as llm_svc
from app.services.retrieval import search_knowledge
from app.stores import get_graph_store


def test_exclude_intent(monkeypatch):
    init_db()
    settings = get_settings()
    g = get_graph_store(settings)
    # 加拿大：产品 J01(跑步机) / J02(遥控器) / J03(遥控器)
    g.upsert_entity(1, "加拿大", "站点", {}, None, None)
    g.upsert_entity(1, "遥控器", "产品类型", {}, None, None)
    g.upsert_entity(1, "跑步机", "产品类型", {}, None, None)
    g.upsert_entity(1, "J01", "ASIN", {}, None, None)
    g.upsert_entity(1, "J02", "ASIN", {}, None, None)
    g.upsert_entity(1, "J03", "ASIN", {}, None, None)
    g.upsert_relation(1, "加拿大", "J01", "产品", {}, None, None)
    g.upsert_relation(1, "加拿大", "J02", "产品", {}, None, None)
    g.upsert_relation(1, "加拿大", "J03", "产品", {}, None, None)
    g.upsert_relation(1, "J01", "跑步机", "产品类型", {}, None, None)
    g.upsert_relation(1, "J02", "遥控器", "产品类型", {}, None, None)
    g.upsert_relation(1, "J03", "遥控器", "产品类型", {}, None, None)

    # 模拟理解层：识别 anchors=加拿大、exclude=遥控器
    monkeypatch.setattr(
        llm_svc, "parse_query_intent",
        lambda llm, q: {"anchors": ["加拿大"], "relation_types": [], "entity_types": [], "exclude": ["遥控器"]},
    )

    db = SessionLocal()
    try:
        r = search_knowledge(db, settings, "给我加拿大除了遥控器的所有产品",
                             [1], top_k=10, graph_depth=1, enable_graph=True)
        names = {e["name"] for e in r["graph"]["entities"]}
        assert "加拿大" in names, names
        assert "J01" in names, names          # 跑步机产品应保留
        assert "J02" not in names, names      # 遥控器产品应排除
        assert "J03" not in names, names
        assert "遥控器" not in names, names
    finally:
        db.close()
        from app.database import engine
        engine.dispose()
        shutil.rmtree("test_intent_data", ignore_errors=True)
        for p in ("test_intent.db", "test_intent.db-wal", "test_intent.db-shm"):
            if os.path.exists(p):
                os.remove(p)
