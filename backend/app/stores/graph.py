"""图存储抽象：local（开发/单机回退）| neo4j（生产）。

实体/关系是图谱侧权限过滤的基础：所有节点/边都带 kb_id，
subgraph 遍历只允许在 allowed_kb_ids 范围内展开。
"""
from __future__ import annotations

import json
import threading
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from ..config import Settings

Entity = dict
Relation = dict


class GraphStore(ABC):
    @abstractmethod
    def upsert_entity(self, kb_id: int, name: str, etype: str,
                      properties: dict, source_doc_id: int | None,
                      source_chunk_id: int | None) -> str: ...

    @abstractmethod
    def upsert_relation(self, kb_id: int, src_name: str, tgt_name: str,
                        rel_type: str, properties: dict,
                        source_doc_id: int | None, source_chunk_id: int | None) -> str: ...

    @abstractmethod
    def find_entity(self, kb_id: int, name: str) -> Entity | None: ...

    @abstractmethod
    def get_entity(self, entity_id: str) -> Entity | None: ...

    @abstractmethod
    def subgraph(self, allowed_kb_ids: list[int], seed_names: list[str],
                 depth: int, relation_types: list[str] | None = None,
                 max_nodes: int = 200) -> tuple[list[Entity], list[Relation]]: ...

    @abstractmethod
    def list_entities(self, kb_id: int, limit: int, offset: int) -> tuple[list[Entity], int]: ...

    @abstractmethod
    def list_relations(self, kb_id: int, limit: int, offset: int) -> tuple[list[Relation], int]: ...

    @abstractmethod
    def update_entity(self, entity_id: str, fields: dict) -> None: ...

    @abstractmethod
    def update_relation(self, relation_id: str, fields: dict) -> None: ...

    @abstractmethod
    def delete_entity(self, entity_id: str) -> None: ...

    @abstractmethod
    def merge_entities(self, from_id: str, into_id: str) -> None: ...

    @abstractmethod
    def delete_relation(self, relation_id: str) -> None: ...

    @abstractmethod
    def delete_by_doc(self, doc_id: int) -> None: ...

    @abstractmethod
    def delete_by_kb(self, kb_id: int) -> None: ...

    @abstractmethod
    def count(self) -> tuple[int, int]: ...

    @abstractmethod
    def close(self) -> None: ...


class LocalGraphStore(GraphStore):
    """内存 dict + JSON 持久化。适合单机中小规模。"""

    def __init__(self, settings: Settings):
        self._path = settings.data_dir_path / "graph.json"
        self._lock = threading.Lock()
        self._entities: dict[str, Entity] = {}
        self._relations: dict[str, Relation] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._entities = data.get("entities", {})
            self._relations = data.get("relations", {})

    def _save(self) -> None:
        with self._lock:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"entities": self._entities, "relations": self._relations},
                          f, ensure_ascii=False)

    def _entity_id(self, kb_id: int, name: str) -> str | None:
        for eid, e in self._entities.items():
            if e["kb_id"] == kb_id and e["name"] == name:
                return eid
        return None

    def upsert_entity(self, kb_id: int, name: str, etype: str,
                      properties: dict, source_doc_id: int | None,
                      source_chunk_id: int | None) -> str:
        with self._lock:
            eid = self._entity_id(kb_id, name)
            if eid is None:
                eid = uuid.uuid4().hex
                self._entities[eid] = {
                    "id": eid, "kb_id": kb_id, "name": name, "type": etype,
                    "properties": properties or {}, "source_doc_id": source_doc_id,
                    "source_chunk_id": source_chunk_id, "verified": False,
                    "created_at": self._now(),
                }
            else:
                self._entities[eid].setdefault("source_doc_id", source_doc_id)
        self._save()
        return eid

    def upsert_relation(self, kb_id: int, src_name: str, tgt_name: str,
                        rel_type: str, properties: dict,
                        source_doc_id: int | None, source_chunk_id: int | None) -> str:
        """同一对实体之间只保留一条关系：已存在则更新关系类型（编辑语义），不再新增重复边。"""
        with self._lock:
            src = self._entity_id(kb_id, src_name)
            tgt = self._entity_id(kb_id, tgt_name)
            if src is None or tgt is None:
                raise ValueError(f"实体不存在: {src_name} -> {tgt_name}")
            for rid, r in self._relations.items():
                if r["source_entity_id"] == src and r["target_entity_id"] == tgt \
                        and r["kb_id"] == kb_id:
                    # 同对实体已有关联：更新关系类型（覆盖旧类型），保留来源信息
                    r["relation_type"] = rel_type
                    if properties:
                        r.setdefault("properties", {}).update(properties)
                    r.setdefault("source_doc_id", source_doc_id)
                    r.setdefault("source_chunk_id", source_chunk_id)
                    break
            else:
                rid = uuid.uuid4().hex
                self._relations[rid] = {
                    "id": rid, "kb_id": kb_id, "source_entity_id": src,
                    "target_entity_id": tgt, "relation_type": rel_type,
                    "properties": properties or {}, "source_doc_id": source_doc_id,
                    "source_chunk_id": source_chunk_id, "verified": False,
                    "created_at": self._now(),
                }
        self._save()
        return rid

    @staticmethod
    def _now() -> str:
        import datetime
        return datetime.datetime.now().isoformat()

    def find_entity(self, kb_id: int, name: str) -> Entity | None:
        eid = self._entity_id(kb_id, name)
        return self._entities.get(eid)

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def subgraph(self, allowed_kb_ids: list[int], seed_names: list[str],
                 depth: int, relation_types: list[str] | None = None,
                 max_nodes: int = 200) -> tuple[list[Entity], list[Relation]]:
        allowed = set(allowed_kb_ids)
        seeds = {
            eid for eid, e in self._entities.items()
            if e["kb_id"] in allowed and e["name"] in set(seed_names)
        }
        nodes: set[str] = set(seeds)
        frontier = set(seeds)
        for _ in range(depth):  # depth=0 时不扩展，只返回种子实体
            if not frontier:
                break
            nxt: set[str] = set()
            for rid, r in self._relations.items():
                if r["kb_id"] not in allowed:
                    continue
                if relation_types and r["relation_type"] not in relation_types:
                    continue
                if r["source_entity_id"] in frontier and r["target_entity_id"] not in nodes:
                    if len(nodes) < max_nodes:
                        nxt.add(r["target_entity_id"])
                if r["target_entity_id"] in frontier and r["source_entity_id"] not in nodes:
                    if len(nodes) < max_nodes:
                        nxt.add(r["source_entity_id"])
            nodes |= nxt
            frontier = nxt
        entities = [self._entities[eid] for eid in nodes]
        rels = [
            r for r in self._relations.values()
            if r["kb_id"] in allowed
            and r["source_entity_id"] in nodes and r["target_entity_id"] in nodes
            and (not relation_types or r["relation_type"] in relation_types)
        ]
        return entities, rels

    def list_entities(self, kb_id: int, limit: int, offset: int) -> tuple[list[Entity], int]:
        rows = [e for e in self._entities.values() if e["kb_id"] == kb_id]
        rows.sort(key=lambda e: e["name"])
        return rows[offset:offset + limit], len(rows)

    def list_relations(self, kb_id: int, limit: int, offset: int) -> tuple[list[Relation], int]:
        rows = [r for r in self._relations.values() if r["kb_id"] == kb_id]
        # 按 (起点名, 关系类型, 终点名) 排序，保证展示顺序稳定
        name_of = {eid: str(e.get("name", "")) for eid, e in self._entities.items()}
        rows.sort(key=lambda r: (name_of.get(r.get("source_entity_id"), ""),
                                 str(r.get("relation_type", "")),
                                 name_of.get(r.get("target_entity_id"), "")))
        return rows[offset:offset + limit], len(rows)

    def update_entity(self, entity_id: str, fields: dict) -> None:
        with self._lock:
            if entity_id in self._entities:
                self._entities[entity_id].update(fields)
            else:
                raise KeyError(entity_id)
        self._save()

    def update_relation(self, relation_id: str, fields: dict) -> None:
        with self._lock:
            if relation_id in self._relations:
                self._relations[relation_id].update(fields)
            else:
                raise KeyError(relation_id)
        self._save()

    def delete_entity(self, entity_id: str) -> None:
        with self._lock:
            self._entities.pop(entity_id, None)
            self._relations = {
                rid: r for rid, r in self._relations.items()
                if r["source_entity_id"] != entity_id and r["target_entity_id"] != entity_id
            }
        self._save()

    def merge_entities(self, from_id: str, into_id: str) -> None:
        """把 from_id 合并进 into_id：关系改指，属性合并，删除 from。"""
        with self._lock:
            if from_id not in self._entities or into_id not in self._entities:
                raise KeyError(f"实体不存在: {from_id} / {into_id}")
            src = self._entities[from_id]
            dst = self._entities[into_id]
            dst.setdefault("properties", {}).update(src.get("properties", {}))
            if not dst.get("verified") and src.get("verified"):
                dst["verified"] = True
            for rid, r in self._relations.items():
                if r["source_entity_id"] == from_id:
                    r["source_entity_id"] = into_id
                if r["target_entity_id"] == from_id:
                    r["target_entity_id"] = into_id
            # 自环清理 + 同起点终点同类型去重
            seen: set[tuple] = set()
            keep: dict[str, Relation] = {}
            for rid, r in self._relations.items():
                key = (r["source_entity_id"], r["target_entity_id"], r["relation_type"])
                if r["source_entity_id"] == r["target_entity_id"] or key in seen:
                    continue
                seen.add(key)
                keep[rid] = r
            self._relations = keep
            self._entities.pop(from_id, None)
        self._save()

    def delete_relation(self, relation_id: str) -> None:
        with self._lock:
            self._relations.pop(relation_id, None)
        self._save()

    def delete_by_doc(self, doc_id: int) -> None:
        with self._lock:
            self._entities = {
                eid: e for eid, e in self._entities.items()
                if e.get("source_doc_id") != doc_id
            }
            self._relations = {
                rid: r for rid, r in self._relations.items()
                if r.get("source_doc_id") != doc_id
            }
        self._save()

    def delete_by_kb(self, kb_id: int) -> None:
        with self._lock:
            self._entities = {eid: e for eid, e in self._entities.items() if e["kb_id"] != kb_id}
            self._relations = {rid: r for rid, r in self._relations.items() if r["kb_id"] != kb_id}
        self._save()

    def count(self) -> tuple[int, int]:
        with self._lock:
            return len(self._entities), len(self._relations)

    def close(self) -> None:
        self._save()


class Neo4jGraphStore(GraphStore):
    """生产实现：Neo4j Community。所有节点/边带 kb_id，遍历时过滤。"""

    def __init__(self, settings: Settings):
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def _run(self, query: str, **params):
        with self._driver.session() as session:
            return session.run(query, **params)

    def upsert_entity(self, kb_id: int, name: str, etype: str,
                      properties: dict, source_doc_id: int | None,
                      source_chunk_id: int | None) -> str:
        from uuid import uuid4
        result = self._run(
            """MERGE (e:Entity {kb_id: $kb_id, name: $name})
               ON CREATE SET e.id = $eid, e.type = $etype,
                             e.source_doc_id = $source_doc_id,
                             e.source_chunk_id = $source_chunk_id,
                             e.verified = false, e.created_at = datetime()
               ON MATCH SET e.type = coalesce(e.type, $etype)
               RETURN e.id AS id""",
            kb_id=kb_id, name=name, eid=uuid4().hex, etype=etype,
            source_doc_id=source_doc_id, source_chunk_id=source_chunk_id,
        )
        return result.single()["id"]

    def upsert_relation(self, kb_id: int, src_name: str, tgt_name: str,
                        rel_type: str, properties: dict,
                        source_doc_id: int | None, source_chunk_id: int | None) -> str:
        """同一对实体之间只保留一条关系：已存在则更新关系类型（覆盖旧类型），不新增重复边。"""
        from uuid import uuid4
        result = self._run(
            """MATCH (s:Entity {kb_id: $kb_id, name: $src}),
                      (t:Entity {kb_id: $kb_id, name: $tgt})
               OPTIONAL MATCH (s)-[r:REL]->(t)
               FOREACH (_ IN CASE WHEN r IS NULL THEN [1] ELSE [] END |
                   CREATE (s)-[r2:REL {id: $rid, kb_id: $kb_id,
                       source_doc_id: $source_doc_id, source_chunk_id: $source_chunk_id,
                       verified: false, created_at: datetime()}]->(t)
               )
               FOREACH (_ IN CASE WHEN r IS NOT NULL THEN [1] ELSE [] END |
                   SET r.type = $rel_type
               )
               RETURN coalesce(r.id, $rid) AS id""",
            kb_id=kb_id, src=src_name, tgt=tgt_name, rel_type=rel_type,
            rid=uuid4().hex, source_doc_id=source_doc_id, source_chunk_id=source_chunk_id,
        )
        record = result.single()
        if record is None:
            raise ValueError(f"实体不存在: {src_name} -> {tgt_name}")
        return record["id"]

    def find_entity(self, kb_id: int, name: str) -> Entity | None:
        result = self._run(
            "MATCH (e:Entity {kb_id: $kb_id, name: $name}) RETURN e LIMIT 1",
            kb_id=kb_id, name=name,
        )
        record = result.single()
        return dict(record["e"]) if record else None

    def get_entity(self, entity_id: str) -> Entity | None:
        result = self._run(
            "MATCH (e:Entity {id: $id}) RETURN e LIMIT 1", id=entity_id,
        )
        record = result.single()
        return dict(record["e"]) if record else None

    def subgraph(self, allowed_kb_ids: list[int], seed_names: list[str],
                 depth: int, relation_types: list[str] | None = None,
                 max_nodes: int = 200) -> tuple[list[Entity], list[Relation]]:
        rel_filter = (
            "AND r.type IN $relation_types" if relation_types else ""
        )
        query = f"""
            MATCH (e:Entity)
            WHERE e.kb_id IN $allowed AND e.name IN $seed_names
            CALL {{
                WITH e
                MATCH (e)-[r:REL*1..$depth]->(n:Entity)
                WHERE ALL(x IN r WHERE x.kb_id IN $allowed {rel_filter})
                RETURN n, r
                UNION
                WITH e
                MATCH (e)<-[r:REL*1..$depth]-(n:Entity)
                WHERE ALL(x IN r WHERE x.kb_id IN $allowed {rel_filter})
                RETURN n, r
            }}
            RETURN n, r LIMIT $max_nodes
        """
        entities, rels = [], []
        with self._driver.session() as session:
            for record in session.run(
                query, allowed=list(allowed_kb_ids), seed_names=seed_names,
                depth=int(depth), max_nodes=int(max_nodes),
                relation_types=relation_types or [],
            ):
                if record["n"]:
                    node = dict(record["n"])
                    node["id"] = node.get("id") or node.get("name")
                    entities.append(node)
                if record["r"]:
                    rels.append(dict(record["r"]))
        # 去重
        seen_e, seen_r = set(), set()
        entities_u, rels_u = [], []
        for e in entities:
            key = (e.get("kb_id"), e.get("name"))
            if key not in seen_e:
                seen_e.add(key)
                entities_u.append(e)
        for r in rels:
            key = r.get("id") or str(r)
            if key not in seen_r:
                seen_r.add(key)
                rels_u.append(r)
        return entities_u, rels_u

    def list_entities(self, kb_id: int, limit: int, offset: int) -> tuple[list[Entity], int]:
        result = self._run(
            "MATCH (e:Entity {kb_id: $kb_id}) RETURN e ORDER BY e.name "
            "SKIP $offset LIMIT $limit", kb_id=kb_id, offset=offset, limit=limit)
        rows = [dict(r["e"]) for r in result]
        count = self._run("MATCH (e:Entity {kb_id: $kb_id}) RETURN count(e) AS c",
                          kb_id=kb_id).single()["c"]
        return rows, count

    def list_relations(self, kb_id: int, limit: int, offset: int) -> tuple[list[Relation], int]:
        result = self._run(
            "MATCH (s:Entity {kb_id: $kb_id})-[r:REL]->(t:Entity) "
            "RETURN r, s.name AS src, t.name AS tgt ORDER BY r.created_at "
            "SKIP $offset LIMIT $limit", kb_id=kb_id, offset=offset, limit=limit)
        rows = []
        for rec in result:
            r = dict(rec["r"])
            r["source_name"] = rec["src"]
            r["target_name"] = rec["tgt"]
            rows.append(r)
        count = self._run(
            "MATCH ()-[r:REL {kb_id: $kb_id}]->() RETURN count(r) AS c",
            kb_id=kb_id).single()["c"]
        return rows, count

    def update_entity(self, entity_id: str, fields: dict) -> None:
        self._run("MATCH (e:Entity {id: $id}) SET e += $fields",
                  id=entity_id, fields=fields)

    def update_relation(self, relation_id: str, fields: dict) -> None:
        self._run("MATCH ()-[r:REL {id: $id}]->() SET r += $fields",
                  id=relation_id, fields=fields)

    def delete_entity(self, entity_id: str) -> None:
        self._run("MATCH (e:Entity {id: $id}) DETACH DELETE e", id=entity_id)

    def merge_entities(self, from_id: str, into_id: str) -> None:
        """把 from_id 合并进 into_id（无 APOC 的多步实现）。"""
        # 入边改指
        self._run(
            """MATCH (x:Entity)-[r:REL]->(a:Entity {id: $from_id}),
                      (b:Entity {id: $into_id})
               MERGE (x)-[r2:REL {type: r.type}]->(b)
               ON CREATE SET r2.kb_id = r.kb_id, r2.verified = r.verified
               DELETE r""",
            from_id=from_id, into_id=into_id,
        )
        # 出边改指
        self._run(
            """MATCH (a:Entity {id: $from_id})-[r:REL]->(x:Entity),
                      (b:Entity {id: $into_id})
               MERGE (b)-[r2:REL {type: r.type}]->(x)
               ON CREATE SET r2.kb_id = r.kb_id, r2.verified = r.verified
               DELETE r""",
            from_id=from_id, into_id=into_id,
        )
        # 删除被合并节点
        self._run("MATCH (e:Entity {id: $id}) DETACH DELETE e", id=from_id)

    def delete_relation(self, relation_id: str) -> None:
        self._run("MATCH ()-[r:REL {id: $id}]->() DELETE r", id=relation_id)

    def delete_by_doc(self, doc_id: int) -> None:
        self._run(
            "MATCH (e:Entity {source_doc_id: $doc_id}) DETACH DELETE e "
            "WITH count(*) AS c "
            "MATCH ()-[r:REL {source_doc_id: $doc_id}]->() DELETE r",
            doc_id=doc_id)

    def delete_by_kb(self, kb_id: int) -> None:
        self._run("MATCH (e:Entity {kb_id: $kb_id}) DETACH DELETE e", kb_id=kb_id)

    def count(self) -> tuple[int, int]:
        ec = self._run("MATCH (e:Entity) RETURN count(e) AS c").single()["c"]
        rc = self._run("MATCH ()-[r:REL]->() RETURN count(r) AS c").single()["c"]
        return ec, rc

    def close(self) -> None:
        self._driver.close()
