"""混合检索：向量 + 图谱，融合排序；强制 allowed_kb_ids 权限过滤。

权限模型：所有检索方法唯一接受 allowed_kb_ids 作为数据范围，
由服务端从 API 密钥解析注入，客户端无法扩大。
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Chunk, KnowledgeBase
from ..stores import get_graph_store, get_vector_store
from .embedding import get_embedder
from . import llm as llm_svc

# "X的所有/全部数据" 类枚举查询：沿任意关系类型扩展（配合排除语义返回完整数据）
_ENUMERATE_MARKERS = ("所有", "全部", "一切")
# LLM 意图解析不可用时的中文排除词规则兜底（如"除了X/排除X/不要X"）
_EXCLUDE_MARKERS = ("除了", "除外", "排除", "不包括", "剔除", "去掉", "不要", "除去", "不含")


def _is_enumerate_query(query: str) -> bool:
    return any(m in query for m in _ENUMERATE_MARKERS)


def _rule_exclude_terms(query: str) -> list[str]:
    """轻量中文规则兜底：从查询中提取"除了X"等表达中的排除对象（LLM 失败/未配置时保底）。"""
    terms: list[str] = []
    for m in re.finditer(
        r"(?:%s)\s*([^，。？?,.、\s]{1,12})" % "|".join(_EXCLUDE_MARKERS), query
    ):
        t = m.group(1).strip()
        if t and t not in terms:
            terms.append(t)
    return terms


def _graph_levels(entities: list[dict], relations: list[dict],
                  seed_ids: set[str]) -> dict[str, int]:
    """从种子（锚点）实体出发 BFS，返回 {实体id: 层级}；种子=0，不连通实体取大层级。

    用于结果排序：锚点实体（如"斑笔科技"）排最上，逐级向下，同级再按名称。
    """
    adj: dict[str, set[str]] = {}
    for r in relations:
        s = str(r.get("source_entity_id", ""))
        t = str(r.get("target_entity_id", ""))
        adj.setdefault(s, set()).add(t)
        adj.setdefault(t, set()).add(s)
    levels: dict[str, int] = {}
    frontier: list[str] = []
    for n in seed_ids:
        if n and n not in levels:
            levels[n] = 0
            frontier.append(n)
    level = 0
    while frontier:
        level += 1
        nxt: list[str] = []
        for node in frontier:
            for nb in adj.get(node, ()):
                if nb not in levels:
                    levels[nb] = level
                    nxt.append(nb)
        frontier = nxt
    return levels


def format_graph_context(graph: dict, max_items: int = 50) -> str:
    """把图谱命中的实体/关系格式化为可读文本，供 RAG 回答上下文使用。

    kb2 这类纯图谱库（无文档文本块）也能据此回答"有哪些数据"类问题。
    """
    entities = graph.get("entities", [])
    relations = graph.get("relations", [])
    if not entities and not relations:
        return ""
    lines = ["【知识图谱命中】"]
    eid2name = {e.get("id"): e.get("name", "") for e in entities}
    for e in entities[:max_items]:
        mark = "（已确认）" if e.get("verified") else ""
        lines.append(f"- 实体：{e.get('name', '')}[{e.get('type', '')}]{mark}")
    for r in relations[:max_items]:
        src = eid2name.get(r.get("source_entity_id")) or r.get("source_entity_id", "")
        tgt = eid2name.get(r.get("target_entity_id")) or r.get("target_entity_id", "")
        lines.append(f"- 关系：{src} -{r.get('relation_type', '')}-> {tgt}")
    return "\n".join(lines)


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
    enumerate_query = _is_enumerate_query(query)

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
        # 2b) 查询意图解析（LLM）：识别点名实体、排除等复合语义（"除了遥控器"→排除）
        llm = llm_svc.resolve_llm(settings)
        intent: dict = {}
        if llm.configured():
            try:
                intent = llm_svc.parse_query_intent(llm, query)
            except Exception as e:
                # 失败可见性：云端模型调用失败（网络/余额/超时）时输出到服务日志，便于排查
                print(f"[LLM] parse_query_intent 失败，排除语义走规则兜底："
                      f"{type(e).__name__}: {e}", flush=True)
                intent = {}
        # 清洗意图：只保留与查询/图谱相关的项（防止模型幻觉或英文干扰）
        intent_anchors = [a for a in intent.get("anchors", [])
                          if a and (a in query or a in ids_by_name)]
        intent_reltypes = [rt for rt in intent.get("relation_types", []) if rt and rt in query]
        exclude_terms = [t for t in intent.get("exclude", []) if t and t in query]
        if not exclude_terms:
            # LLM 未给出排除（未配置/调用失败/漏识别）→ 中文规则兜底："除了X/排除X/不要X"
            exclude_terms = [t for t in _rule_exclude_terms(query) if t]
        if exclude_terms:
            # 排除对象不应作为正向锚点（"除了遥控器"的"遥控器"不是要查的，而是要剔除的）
            def _excl_hit(text: str) -> bool:
                return any(t in text or text in t for t in exclude_terms)
            name_seeds = [n for n in name_seeds if not _excl_hit(n)]
            type_seeds = [s for s in type_seeds if not _excl_hit(s)]
            rel_seeds = [s for s in rel_seeds if not _excl_hit(s)]
        for a in intent_anchors:
            if a and a not in name_seeds:
                name_seeds.append(a)
        for rt in intent_reltypes:
            if rt and rt not in matched_rel_types:
                matched_rel_types.append(rt)
        seed_names = list(dict.fromkeys(n for n in (name_seeds + type_seeds + rel_seeds) if n))
        if seed_names:
            # ===== 检索精度规则（持久生效，数据再多也按真实关系收紧）=====
            # 1) 只有"点名实体"（实体名命中）是扩展源：
            #    - 按 graph_depth 扩展，且只沿查询中提到的关系类型展开；查询未提关系类型则不扩展
            # 2) 类型/关系类型召回的实体只是"叶子"，纳入结果但不继续扩散邻居
            #    （避免"美国站的ASIN"把加拿大站ASIN带进来、"加拿大的品牌"把美国带进来）
            # 3) 纯"列举"查询（仅类型/关系类型命中，如"站点有哪些""产品"）→ 不扩展，只返回命中实体与其之间的关系
            # 4) "X的所有/全部数据"枚举查询（如"斑笔科技除了美国站的所有数据"）→
            #    沿任意关系类型扩展（至多 3 跳），再配合排除语义剔除排除对象及其 1 跳邻居
            if name_seeds:
                if matched_rel_types:
                    depth_eff = graph_depth
                    rel_filter = list(dict.fromkeys(matched_rel_types)) or None
                elif enumerate_query:
                    depth_eff = 3
                    rel_filter = None
                else:
                    depth_eff = 0
                    rel_filter = None
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
                reach_depth = 3 if enumerate_query else min(max(graph_depth, 1) + 1, 3)
                for n in name_seed_unique:
                    # LLM 提到的名字在图谱中不存在（已合并/删除/幻觉）→ 不参与交集约束，避免误清空结果
                    if n not in ids_by_name:
                        continue
                    ents, _ = gstore.subgraph(allowed, [n], reach_depth, None)
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
            # 5) 排除语义：查询明确排除的对象（"除了遥控器"）→ 剔除该对象及其 1 跳相连的实体
            if exclude_terms:
                # 双向包含匹配：排除词含实体名（"美国站"→实体"美国"）或实体名含排除词（"遥控器图片"）
                excl_names = [n for n in ids_by_name
                              if any(t in n or n in t for t in exclude_terms)]
                excl_ids: set[str] = {i for n in excl_names for i in ids_by_name[n]}
                for e in entities:
                    if any(t in str(e.get("type", "")) for t in exclude_terms):
                        excl_ids.add(e["id"])
                if excl_names:
                    nb, _ = gstore.subgraph(allowed, excl_names, 1, None)
                    excl_ids.update(e["id"] for e in nb)
                # 锚点（点名实体）即使与排除对象相连也要保留：
                # "斑笔科技除了美国站" → 斑笔科技不能被当作"美国站的1跳邻居"误删
                keep_ids: set[str] = {i for n in name_seeds for i in ids_by_name.get(n, [])}
                excl_ids -= keep_ids
                entities = [e for e in entities if e["id"] not in excl_ids]
                kept_ids = {e["id"] for e in entities}
                relations = [r for r in relations
                             if r["source_entity_id"] in kept_ids
                             and r["target_entity_id"] in kept_ids]
            # 6) 结果排序：按图谱层级（锚点实体最上，逐级向下），同级按名称——
            #    "斑笔科技除了美国站"→ 斑笔科技(0) > 站点(1) > ASIN/品牌(2) > 产品类型(3)
            _eid2name = {e["id"]: str(e.get("name", "")) for e in entities}
            _seed_ids = {i for n in name_seeds for i in ids_by_name.get(n, [])}
            _levels = _graph_levels(entities, relations, _seed_ids)
            _FAR = 999
            graph = {
                "entities": sorted(entities, key=lambda e: (
                    _levels.get(str(e["id"]), _FAR), str(e.get("name", "")))),
                "relations": sorted(relations, key=lambda r: (
                    _levels.get(str(r.get("source_entity_id")), _FAR),
                    _eid2name.get(str(r.get("source_entity_id")), ""),
                    str(r.get("relation_type", "")),
                    _eid2name.get(str(r.get("target_entity_id")), ""),
                )),
            }
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
