#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""图谱分层布局（与前端 GraphView.layeredPositions 算法一致）：
对有保存坐标的历史知识库批量重排实体坐标并保存（PATCH），让图谱打开即整齐。

用法: python graph_layout.py [kb_id ...]   # 缺省处理全部知识库
"""
import os
import sys

os.environ["NO_PROXY"] = "*"

import httpx

BASE = "http://127.0.0.1:8002"


def layered_positions(nodes, edges, w=1200, h=700):
    id_set = {n["id"] for n in nodes}
    label_of = {n["id"]: n.get("name", "") for n in nodes}
    out = {n["id"]: [] for n in nodes}
    in_deg = {n["id"]: 0 for n in nodes}
    for e in edges:
        if e["source"] not in id_set or e["target"] not in id_set:
            continue
        out[e["source"]].append(e["target"])
        in_deg[e["target"]] += 1

    roots = [n["id"] for n in nodes if in_deg[n["id"]] == 0]
    if not roots:
        deg = {}
        for e in edges:
            if e["source"] in id_set and e["target"] in id_set:
                deg[e["source"]] = deg.get(e["source"], 0) + 1
                deg[e["target"]] = deg.get(e["target"], 0) + 1
        mx = -1
        for n in nodes:
            if deg.get(n["id"], 0) > mx:
                mx = deg[n["id"]]
                roots = [n["id"]]

    level = {}
    frontier = list(roots)
    for n in frontier:
        level[n] = 0
    lv = 0
    while frontier:
        lv += 1
        nxt = []
        for node in frontier:
            for t in out.get(node, []):
                if t not in level:
                    level[t] = lv
                    nxt.append(t)
        frontier = nxt
    for n in nodes:
        if n["id"] not in level:
            level[n["id"]] = max(lv, 1)

    by_level = {}
    for n in nodes:
        by_level.setdefault(level[n["id"]], []).append(n["id"])
    levels = sorted(by_level.keys())

    # 父节点位置优先排序（同一父节点的子节点相邻，父子连线不交叉）+ 名称兜底
    index_in = {l: {i: k for k, i in enumerate(by_level[l])} for l in levels}

    def parent_rank(node_id, l):
        best = None
        for e in edges:
            other = None
            if e["source"] == node_id and e["target"] in id_set:
                other = e["target"]
            if e["target"] == node_id and e["source"] in id_set:
                other = e["source"]
            if other is None:
                continue
            nl = level.get(other)
            if nl is not None and nl < l:
                idx = index_in.get(nl, {}).get(other)
                if idx is not None and (best is None or idx < best):
                    best = idx
        return best

    for l in levels:
        by_level[l].sort(key=lambda x: (
            parent_rank(x, l) if parent_rank(x, l) is not None else 10**9,
            label_of.get(x, "")))
        index_in[l] = {i: k for k, i in enumerate(by_level[l])}

    # Barycenter 减交叉（迭代 5 次）
    for _ in range(5):
        for l in levels:
            ids = by_level[l]

            def center(node_id):
                neigh = set()
                for e in edges:
                    if e["source"] == node_id and e["target"] in id_set:
                        neigh.add(e["target"])
                    if e["target"] == node_id and e["source"] in id_set:
                        neigh.add(e["source"])
                s, c = 0, 0
                for nid in neigh:
                    nl = level.get(nid)
                    idx = index_in.get(nl, {}).get(nid)
                    if nl is not None and nl != l and idx is not None:
                        s += idx
                        c += 1
                # fallback：无跨层邻居时用当前层序号（map 查询，避免排序中 index 失效）
                return s / c if c else index_in[l].get(node_id, 0)

            ids.sort(key=center)
            index_in[l] = {i: k for k, i in enumerate(ids)}

    max_label = max((len(label_of.get(n["id"], "")) for n in nodes), default=2)
    node_w = min(max(max_label * 13 + 40, 110), 190)
    layer_h = 170
    # 宽层自动折行（每行最多 10 个，父子尽量同排不拆散，减少交叉）；子行间距 80px
    max_per_row = 10
    row_gap = 80
    pos = {}
    for l in levels:
        ids = by_level[l]
        row_count = max(1, -(-len(ids) // max_per_row))  # ceil
        per_row = -(-len(ids) // row_count)
        rows = [ids[r * per_row:(r + 1) * per_row] for r in range(row_count)]
        max_row_w = max((len(r) * node_w for r in rows), default=0)
        x0 = 10 if max_row_w > w - 20 else (w - max_row_w) / 2
        for ri, row in enumerate(rows):
            row_w = len(row) * node_w
            row_x0 = x0 + (max_row_w - row_w) / 2
            for i, nid in enumerate(row):
                pos[nid] = {"x": row_x0 + node_w / 2 + i * node_w,
                            "y": 60 + l * layer_h + ri * row_gap}
    return pos


def main():
    tok = httpx.post(f"{BASE}/api/admin/login",
                     json={"username": "admin", "password": "admin123"},
                     timeout=10, trust_env=False).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    kbs = httpx.get(f"{BASE}/api/admin/kbs", headers=h, timeout=10, trust_env=False).json()
    targets = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [kb["id"] for kb in kbs]
    for kb in kbs:
        if kb["id"] not in targets:
            continue
        ents = httpx.get(f"{BASE}/api/admin/kbs/{kb['id']}/entities",
                         params={"limit": 500}, headers=h, timeout=20, trust_env=False).json()["items"]
        rels = httpx.get(f"{BASE}/api/admin/kbs/{kb['id']}/relations",
                         params={"limit": 500}, headers=h, timeout=20, trust_env=False).json()["items"]
        if not ents:
            print(f"kb{kb['id']}：无实体，跳过")
            continue
        edges = [{"source": r["source_entity_id"], "target": r["target_entity_id"]} for r in rels]
        pos = layered_positions(ents, edges)
        n = 0
        for e in ents:
            p = pos.get(e["id"])
            if not p:
                continue
            props = dict(e.get("properties") or {})
            props["x"] = int(p["x"])
            props["y"] = int(p["y"])
            r = httpx.patch(f"{BASE}/api/admin/entities/{e['id']}",
                            json={"properties": props}, headers=h, timeout=15, trust_env=False)
            if r.status_code == 200:
                n += 1
        print(f"kb{kb['id']}「{kb['name']}」：{len(ents)} 实体已布局保存 {n} 个")


if __name__ == "__main__":
    main()
