"""云端集成测试（真实 OpenAI 兼容代码路径）+ MCP + 10 并发压测。

启动两个真实服务器：
- fake OpenAI（8100 动态端口）：embedding + chat（含图谱抽取 JSON）
- 主应用（8101 动态端口）：EMBEDDING_MODE=openai 指向 fake

验证：
1. 上传 → 云端 embedding 入库 → LLM 图谱抽取 → 实体/关系落图库
2. 密钥检索（真实 embedding 分数、doc_name、permission_scope）
3. 图谱定向查询
4. OpenAI 兼容 /chat/completions 聚合端点
5. MCP：initialize / tools/list / tools/call（search_knowledge_base），无效密钥拒绝
6. 10 并发 × 20 次检索压测，P95 < 2s
7. 租户隔离：key2 检索不得返回 key1 知识库数据
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# 环境必须在导入 app 前设置
os.environ["EMBEDDING_MODE"] = "openai"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["GRAPH_BACKEND"] = "local"
os.environ["DATABASE_URL"] = "sqlite:///./test_live.db"
os.environ["DATA_DIR"] = "./test_live_data"
# 测试进程直连本机服务，禁用任何代理（CI/沙箱环境常见干扰源）
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
# fake 服务器是 OpenAI 兼容接口，固定风格避免读取真实 .env 的 ollama_native
os.environ["LLM_API_STYLE"] = "openai"

for _p in ("test_live.db", "test_live_data"):
    if os.path.isdir(_p):
        shutil.rmtree(_p, ignore_errors=True)
    elif os.path.exists(_p):
        os.remove(_p)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout: float = 20.0) -> None:
    import socket as sk
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with sk.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"端口 {port} 未就绪")


def _serve(app, port: int) -> None:
    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


FAKE_PORT = _free_port()
APP_PORT = _free_port()

os.environ["EMBEDDING_BASE_URL"] = f"http://127.0.0.1:{FAKE_PORT}/v1"
os.environ["EMBEDDING_API_KEY"] = "fake-key"
os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{FAKE_PORT}/v1"
os.environ["LLM_API_KEY"] = "fake-key"
os.environ["LLM_MODEL"] = "fake-model"

import httpx  # noqa: E402
from fake_openai_server import app as fake_app  # noqa: E402
from app.main import app as main_app  # noqa: E402

_threads = [
    threading.Thread(target=_serve, args=(fake_app, FAKE_PORT), daemon=True),
    threading.Thread(target=_serve, args=(main_app, APP_PORT), daemon=True),
]
for t in _threads:
    t.start()
for p in (FAKE_PORT, APP_PORT):
    _wait_port(p)

BASE = f"http://127.0.0.1:{APP_PORT}"


def _post(path: str, json_body: dict | None = None, token: str | None = None,
          files: dict | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=60, trust_env=False) as c:
        if files:
            return c.post(BASE + path, headers=headers, files=files)
        return c.post(BASE + path, headers=headers, json=json_body)


def _get(path: str, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=60, trust_env=False) as c:
        return c.get(BASE + path, headers=headers)


def _delete(path: str, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=60, trust_env=False) as c:
        return c.delete(BASE + path, headers=headers)


def _wait_doc_done(token: str, doc_id: int, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = _get(f"/api/admin/documents/{doc_id}", token).json()
        if doc["status"] == "完成":
            return doc
        if doc["status"] == "失败":
            raise AssertionError(f"处理失败: {doc['error_msg']}")
        time.sleep(0.5)
    raise TimeoutError("文档处理超时")


def _upload_md(token: str, kb_id: int, name: str, content: str) -> int:
    files = {"file": (name, content.encode("utf-8"), "text/markdown")}
    r = _post(f"/api/admin/kbs/{kb_id}/documents", files=files, token=token)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_cloud_pipeline_mcp_and_concurrency():
    # 登录
    r = _post("/api/admin/login", {"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    # 建两个租户知识库
    kb1 = _post("/api/admin/kbs", {"name": "设备维护", "description": ""}, token).json()["id"]
    kb2 = _post("/api/admin/kbs", {"name": "财务制度", "description": ""}, token).json()["id"]

    doc1 = _upload_md(token, kb1, "维护手册.md", (
        "# 设备维护手册\n\n## 日常维护周期\n\n"
        "设备A的日常维护周期为每周一次，内容包括润滑、清洁与紧固检查。\n\n"
        "## 故障处理\n\n设备A出现异响时应停止运行并联系维修工程师。\n\n"
        "## 备件\n\n常用备件包括轴承与密封圈。\n"
    ))
    doc2 = _upload_md(token, kb2, "报销制度.md", (
        "# 差旅报销制度\n\n## 报销标准\n\n"
        "住宿费上限每晚400元，市内交通费实报实销。\n\n"
        "## 审批流程\n\n报销单需先经部门主管审批，再交财务部复核。\n"
    ))

    d1 = _wait_doc_done(token, doc1)
    d2 = _wait_doc_done(token, doc2)
    assert d1["status"] == "完成" and d2["status"] == "完成"

    # 云端 LLM 图谱抽取已入库（fake LLM 返回固定实体）
    ents = _get(f"/api/admin/kbs/{kb1}/entities", token).json()
    names = {e["name"] for e in ents["items"]}
    assert "设备A" in names and "维护周期" in names, names
    rels = _get(f"/api/admin/kbs/{kb1}/relations", token).json()
    assert any(r["relation_type"] == "具有" for r in rels["items"])

    # 按实体 ID 创建关系（复现已修复 bug：前端传 source_entity_id/target_entity_id）
    e_src = next(e for e in ents["items"] if e["name"] == "设备A")
    e_tgt = next(e for e in ents["items"] if e["name"] == "维护周期")
    r = _post(f"/api/admin/kbs/{kb1}/relations",
              {"source_entity_id": e_src["id"], "target_entity_id": e_tgt["id"],
               "relation_type": "需要"}, token)
    assert r.status_code == 200, r.text
    rels = _get(f"/api/admin/kbs/{kb1}/relations", token).json()
    assert any(x["relation_type"] == "需要" for x in rels["items"])
    # 不存在的实体 ID 应返回 404
    r = _post(f"/api/admin/kbs/{kb1}/relations",
              {"source_entity_id": "deadbeef", "target_entity_id": e_tgt["id"],
               "relation_type": "x"}, token)
    assert r.status_code == 404, r.text

    # 实体合并
    eid_src = next(e["id"] for e in ents["items"] if e["name"] == "轴承")
    eid_dst = next(e["id"] for e in ents["items"] if e["name"] == "设备A")
    r = _post("/api/admin/entities/merge", {"source_id": eid_src, "target_id": eid_dst}, token)
    assert r.status_code == 200, r.text
    ents = _get(f"/api/admin/kbs/{kb1}/entities", token).json()
    assert "轴承" not in {e["name"] for e in ents["items"]}

    # 密钥
    def mk_key(name: str, kb_ids: list[int]) -> str:
        r = _post("/api/admin/keys", {"name": name, "key_type": "search", "allowed_kb_ids": kb_ids}, token)
        assert r.status_code == 200, r.text
        return r.json()["key"]

    key1 = mk_key("电脑1", [kb1])
    key2 = mk_key("电脑2", [kb2])

    # 检索：真实 embedding 代码路径
    r = _post("/api/v1/knowledge/search", {"query": "设备A的维护周期", "top_k": 5, "graph_depth": 1}, key1)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["permission_scope"]["kb_ids"] == [kb1]
    assert len(res["chunks"]) > 0
    top = res["chunks"][0]
    assert "维护" in top["content"] and top.get("doc_name") == "维护手册.md"
    # 图谱命中的实体应出现（查询文本含"设备A"实体名）
    graph_names = {e["name"] for e in res["graph"]["entities"]}
    assert "设备A" in graph_names, graph_names

    # 图谱定向查询
    r = _post("/api/v1/knowledge/graph/query", {"entity": "设备A", "depth": 1}, key1)
    assert r.status_code == 200
    assert len(r.json()["entities"]) >= 1

    # OpenAI 兼容聚合端点
    r = _post("/api/v1/chat/completions",
              {"messages": [{"role": "user", "content": "设备A多久保养一次？"}]}, key1)
    assert r.status_code == 200, r.text
    answer = r.json()["choices"][0]["message"]["content"]
    assert "模拟云端回答" in answer

    # 租户隔离：key2 检索不得返回 kb1 数据
    r = _post("/api/v1/knowledge/search", {"query": "设备A的维护周期", "top_k": 5}, key2)
    res2 = r.json()
    assert res2["permission_scope"]["kb_ids"] == [kb2]
    assert all(c["kb_id"] == kb2 for c in res2["chunks"]), "越权返回了其他租户数据"

    # MCP：initialize / list_tools / call_tool
    _mcp_check(key1)

    # MCP 无效密钥应被拒
    _mcp_check_bad_key()

    # 10 并发 × 20 次检索压测
    latencies: list[float] = []

    def one_search(_):
        t0 = time.perf_counter()
        r = _post("/api/v1/knowledge/search", {"query": "设备维护周期是什么", "top_k": 8, "graph_depth": 1}, key1)
        lat = (time.perf_counter() - t0) * 1000
        latencies.append(lat)
        assert r.status_code == 200
        assert r.json()["permission_scope"]["kb_ids"] == [kb1]
        return lat

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(one_search, range(200)))

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    print(f"\n[压测] 200 次请求(10并发) | avg={statistics.mean(latencies):.1f}ms "
          f"p50={latencies[len(latencies)//2]:.1f}ms p95={p95:.1f}ms max={latencies[-1]:.1f}ms")
    assert p95 < 2000, f"P95={p95}ms 超过 2s"

    # ---- 图谱检索精度回归（持久规则：按真实关系收紧，跨主题不串扰）----
    pkb = _post("/api/admin/kbs", {"name": "精度测试", "description": ""}, token).json()["id"]

    def mk_ent(name: str, etype: str) -> str:
        return _post(f"/api/admin/kbs/{pkb}/entities", {"name": name, "type": etype}, token).json()["id"]

    def mk_rel(src: str, tgt: str, rtype: str) -> None:
        r = _post(f"/api/admin/kbs/{pkb}/relations",
                  {"source_entity_id": src, "target_entity_id": tgt, "relation_type": rtype}, token)
        assert r.status_code == 200, r.text

    us = mk_ent("美国", "站点")
    ca = mk_ent("加拿大", "站点")
    us1, us2 = mk_ent("美1", "ASIN"), mk_ent("美2", "ASIN")
    ca1, ca2 = mk_ent("加1", "ASIN"), mk_ent("加2", "ASIN")
    brand_us = mk_ent("美牌", "品牌")
    mk_rel(us, us1, "产品"); mk_rel(us, us2, "产品")
    mk_rel(ca, ca1, "产品"); mk_rel(ca, ca2, "产品")
    mk_rel(us, brand_us, "品牌")

    def graph_names(q: str) -> set[str]:
        r = _post(f"/api/admin/kbs/{pkb}/debug-search",
                  {"query": q, "top_k": 8, "graph_depth": 1, "enable_graph": True}, token)
        assert r.status_code == 200, r.text
        return {e["name"] for e in r.json()["graph"]["entities"]}

    # 点名站点+类型：只返回该站点自己的 ASIN，不串到其他站点
    assert graph_names("美国站的ASIN") == {"美国", "美1", "美2"}, graph_names("美国站的ASIN")
    assert graph_names("加拿大的ASIN") == {"加拿大", "加1", "加2"}, graph_names("加拿大的ASIN")
    # 点名站点+关系类型：只返回该站点自己的品牌，不串到其他站点
    assert graph_names("美国站的品牌") == {"美国", "美牌"}, graph_names("美国站的品牌")
    assert graph_names("加拿大的品牌") == {"加拿大"}, graph_names("加拿大的品牌")  # 加拿大无品牌
    # 纯类型列举：只返回该类型实体，不扩展邻居
    assert graph_names("站点有哪些") == {"美国", "加拿大"}, graph_names("站点有哪些")
    assert _delete(f"/api/admin/kbs/{pkb}", token).status_code == 200

    # 清理
    from app.database import engine
    engine.dispose()
    for _p in ("test_live.db", "test_live_data"):
        if os.path.isdir(_p):
            shutil.rmtree(_p, ignore_errors=True)
        elif os.path.exists(_p):
            os.remove(_p)


def _mcp_check(key: str) -> None:
    import anyio
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def run():
        async with streamable_http_client(
            f"http://127.0.0.1:{APP_PORT}/mcp",
            http_client=httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}, trust_env=False),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [t.name for t in tools.tools]
                assert "search_knowledge_base" in names, names
                assert "list_knowledge_bases" in names and "list_documents" in names, names
                res = await session.call_tool("search_knowledge_base",
                                              {"query": "设备A的维护周期", "top_k": 3})
                text = res.content[0].text
                print(f"\n[MCP search 原始返回] isError={res.isError}\n{text[:400]}")
                data = json.loads(text)
                assert data["permission_scope"]["kb_ids"] == [1]
                assert len(data["chunks"]) > 0
                res2 = await session.call_tool("list_documents", {})
                docs = json.loads(res2.content[0].text)
                assert len(docs) >= 1
                return names

    names = anyio.run(run)
    print(f"[MCP] tools={names}")


def _mcp_check_bad_key() -> None:
    import anyio
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def run():
        try:
            async with streamable_http_client(
                f"http://127.0.0.1:{APP_PORT}/mcp",
                http_client=httpx.AsyncClient(headers={"Authorization": "Bearer sk-invalid"}, trust_env=False),
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
            return "accepted"  # 不应走到
        except Exception:
            return "rejected"

    outcome = anyio.run(run)
    assert outcome == "rejected", "无效密钥竟然通过了 MCP 鉴权"
    print("[MCP] 无效密钥已被拒绝")
