"""混合检索：向量 + 图谱，融合排序；强制 allowed_kb_ids 权限过滤。

权限模型：所有检索方法唯一接受 allowed_kb_ids 作为数据范围，
由服务端从 API 密钥解析注入，客户端无法扩大。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Chunk, KnowledgeBase
from ..stores import get_graph_store, get_vector_store
from .embedding import get_embedder
from . import llm as llm_svc


def search_knowledge(
    db: Session,
    settings: Settings,
    query: str,
    allowed_kb_ids: list[int],
    top_k: int = 8,
    graph_depth: int = 1,
    enable_graph: bool = True,
) -> dict:
    top_k = max(1, min(top_k, 50))
    graph_depth = max(0, min(graph_depth, 3))
    allowed = list(dict.fromkeys(allowed_kb_ids))

    embedder = get_embedder(settings)
    vstore = get_vector_store(settings)
    gstore = get_graph_store(settings)

    # 1) 向量检索（服务端强制 kb 过滤）
    query_vec = embedder.embed_queries([query])[0]
    hits = vstore.search(query_vec, allowed, top_k * 2)

    # 2) 图谱检索：查询实体 + 子图扩展
    graph: dict = {"entities": [], "relations": []}
    graph_chunk_ids: set[int] = set()
    verified_chunk_ids: set[int] = set()
    if enable_graph and allowed:
        # 2a) 种子匹配分三类：实体名 / 实体类型 / 关系类型
        name_seeds: list[str] = []
        type_seeds: list[str] = []
        rel_seeds: list[str] = []
        matched_rel_types: list[str] = []
        ids_by_name: dict[str, list[str]] = {}  # 实体名 -> [实体id]，用于邻域约束
        for kb_id in allowed:
            entities, _ = gstore.list_entities(kb_id, limit=1000, offset=0)
            for e in entities:
                name = str(e.get("name", ""))
                ids_by_name.setdefault(name, []).append(e["id"])
                if name and name in query:
                    name_seeds.append(name)
            type_names = {str(e.get("type", "")) for e in entities if e.get("type")}
            for t in type_names:
                # 查询包含类型全名或类型名前两字（如"店铺名称"→"店铺"），召回该类型全部实体
                if (t and t in query) or (len(t) >= 2 and t[:2] in query):
                    type_seeds.extend(
                        str(e["name"]) for e in entities
                        if str(e.get("type", "")) == t and str(e.get("name", ""))
                    )
            rels, _ = gstore.list_relations(kb_id, limit=1000, offset=0)
            for r in rels:
                rt = str(r.get("relation_type", ""))
                if not rt:
                    continue
                if (rt in query) or (len(rt) >= 2 and rt[:2] in query):
                    matched_rel_types.append(rt)
                    src = gstore.get_entity(str(r.get("source_entity_id", "")))
                    tgt = gstore.get_entity(str(r.get("target_entity_id", "")))
                    if src and str(src.get("name", "")):
                        rel_seeds.append(str(src["name"]))
                    if tgt and str(tgt.get("name", "")):
                        rel_seeds.append(str(tgt["name"]))
        # 2a-邻域约束：查询同时点名实体与类型/关系类型词时（如"美国站的ASIN""加拿大的品牌"），
        # 类型实体与关系类型两端都必须与点名实体相连（1 跳内），避免跨站/跨主题误召回
        if name_seeds and (type_seeds or rel_seeds):
            name_seed_unique = list(dict.fromkeys(name_seeds))
            nbr_entities, _ = gstore.subgraph(
                allowed, name_seed_unique, max(graph_depth, 1), None)
            nbr_ids = {e["id"] for e in nbr_entities}
            for n in name_seed_unique:
                nbr_ids.update(ids_by_name.get(n, []))
            type_seeds = [
                s for s in type_seeds
                if set(ids_by_name.get(s, [])) & nbr_ids
            ]
            rel_seeds = [
                s for s in rel_seeds
                if set(ids_by_name.get(s, [])) & nbr_ids
            ]
        # 2b) LLM 提取查询实体（有配置时）
        llm = llm_svc.resolve_llm(settings)
        if llm.configured():
            try:
                name_seeds.extend(llm_svc.query_entities(llm, query))
            except Exception:
                pass
        seed_names = list(dict.fromkeys(n for n in (name_seeds + type_seeds + rel_seeds) if n))
        if seed_names:
            # ===== 检索精度规则（持久生效，数据再多也按真实关系收紧）=====
            # 1) 只有"点名实体"（实体名命中）是扩展源：
            #    - 按 graph_depth 扩展，且只沿查询中提到的关系类型展开；查询未提关系类型则不扩展
            # 2) 类型/关系类型召回的实体只是"叶子"，纳入结果但不继续扩散邻居
            #    （避免"美国站的ASIN"把加拿大站ASIN带进来、"加拿大的品牌"把美国带进来）
            # 3) 纯"列举"查询（仅类型/关系类型命中，如"站点有哪些""产品"）→ 不扩展，只返回命中实体与其之间的关系
            if name_seeds:
                depth_eff = graph_depth if matched_rel_types else 0
                rel_filter = list(dict.fromkeys(matched_rel_types)) or None
                exp_entities, exp_rels = gstore.subgraph(
                    allowed, list(dict.fromkeys(name_seeds)), depth_eff, rel_filter)
            else:
                exp_entities, exp_rels = [], []
            leaf_entities, leaf_rels = gstore.subgraph(allowed, seed_names, 0, None)
            # 合并去重：扩展结果 + 叶子种子
            merged: dict[str, dict] = {e["id"]: e for e in exp_entities}
            for e in leaf_entities:
                merged[e["id"]] = e
            merged_rels: dict[str, dict] = {r["id"]: r for r in exp_rels}
            for r in leaf_rels:
                merged_rels[r["id"]] = r
            entities = list(merged.values())
            relations = list(merged_rels.values())
            # 4) 多条件交集：查询点名多个实体时（如"加拿大遥控器的所有产品"），
            #    每个返回实体必须与【每一个】点名实体都相连，否则排除
            #    （J01 只连加拿大不连遥控器 → 被排除）
            if name_seeds:
                name_seed_unique = list(dict.fromkeys(name_seeds))
                reach_sets: list[set[str]] = []
                for n in name_seed_unique:
                    # LLM 提到的名字在图谱中不存在（已合并/删除/幻觉）→ 不参与交集约束，避免误清空结果
                    if n not in ids_by_name:
                        continue
                    ents, _ = gstore.subgraph(
                        allowed, [n], min(max(graph_depth, 1) + 1, 3), None)
                    ids = {e["id"] for e in ents}
                    ids.update(ids_by_name.get(n, []))
                    reach_sets.append(ids)
                if reach_sets:
                    common = set.intersection(*reach_sets)
                    entities = [e for e in entities if e["id"] in common]
                    kept_ids = {e["id"] for e in entities}
                    relations = [r for r in relations
                                 if r["source_entity_id"] in kept_ids
                                 and r["target_entity_id"] in kept_ids]
            graph = {"entities": entities, "relations": relations}
            for e in entities:
                if e.get("source_chunk_id"):
                    graph_chunk_ids.add(e["source_chunk_id"])
                    if e.get("verified"):
                        verified_chunk_ids.add(e["source_chunk_id"])
            for r in relations:
                if r.get("source_chunk_id"):
                    graph_chunk_ids.add(r["source_chunk_id"])
                    if r.get("verified"):
                        verified_chunk_ids.add(r["source_chunk_id"])

    # 3) 融合：图谱命中块优先（已确认实体的命中加权），其余按向量分数
    fused: list[dict] = []
    seen: set[int] = set()
    for cid in graph_chunk_ids:
        if cid in seen:
            continue
        seen.add(cid)
        chunk = db.get(Chunk, cid)
        if chunk is None or chunk.kb_id not in allowed:
            continue
        score = 1.1 if cid in verified_chunk_ids else 1.0
        fused.append({
            "chunk_id": chunk.id, "kb_id": chunk.kb_id, "doc_id": chunk.doc_id,
            "content": chunk.content, "metadata": chunk.meta,
            "score": score, "source": "graph",
        })
    for hit in hits:
        cid = hit["chunk_id"]
        if cid in seen:
            continue
        seen.add(cid)
        p = hit["payload"]
        chunk = db.get(Chunk, cid)
        fused.append({
            "chunk_id": cid, "kb_id": p.get("kb_id"), "doc_id": p.get("doc_id"),
            "content": chunk.content if chunk else "",
            "metadata": chunk.meta if chunk else {},
            "score": round(hit["score"], 4), "source": "vector",
        })

    # 4) 补充文档名（批量查询，供引用展示）
    doc_ids = list({c["doc_id"] for c in fused if c.get("doc_id")})
    doc_names: dict[int, str] = {}
    if doc_ids:
        from ..models import Document
        rows = db.query(Document).filter(Document.id.in_(doc_ids)).all()
        doc_names = {d.id: d.filename for d in rows}
    for c in fused:
        c["doc_name"] = doc_names.get(c.get("doc_id"), "")

    fused = fused[:top_k]
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(allowed)).all()
    return {
        "query": query,
        "chunks": fused,
        "graph": graph,
        "permission_scope": {"kb_ids": allowed},
        "kb_names": {kb.id: kb.name for kb in kbs},
    }


def graph_query(db: Session, settings: Settings, allowed_kb_ids: list[int],
                entity: str, relation_types: list[str] | None = None,
                depth: int = 2) -> dict:
    gstore = get_graph_store(settings)
    entities, relations = gstore.subgraph(
        allowed_kb_ids, [entity], depth=depth, relation_types=relation_types,
    )
    return {"entities": entities, "relations": relations,
            "permission_scope": {"kb_ids": list(dict.fromkeys(allowed_kb_ids))}}
