"""冒烟测试：上传 → 解析/切分/向量化 → 检索 → 多租户权限隔离。

使用 dummy embedding + 本地存储 + 临时 SQLite，无需网络与外部服务。
"""
from __future__ import annotations

import os
import shutil
import time

os.environ["EMBEDDING_MODE"] = "dummy"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["GRAPH_BACKEND"] = "local"
os.environ["DATABASE_URL"] = "sqlite:///./test_smoke.db"
os.environ["DATA_DIR"] = "./test_data"
# 测试固定 OpenAI 兼容风格 + 空 LLM Key（避免读取真实 .env 的本地 Ollama 配置）
os.environ["LLM_API_STYLE"] = "openai"
os.environ["LLM_API_KEY"] = ""

for _p in ("test_smoke.db", "test_data"):
    if os.path.isdir(_p):
        shutil.rmtree(_p, ignore_errors=True)
    elif os.path.exists(_p):
        os.remove(_p)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _wait_doc_done(token: str, doc_id: int, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/admin/documents/{doc_id}",
                       headers={"Authorization": f"Bearer {token}"})
        doc = r.json()
        if doc["status"] == "完成":
            return doc
        if doc["status"] == "失败":
            raise AssertionError(f"文档处理失败: {doc['error_msg']}")
        time.sleep(0.5)
    raise TimeoutError("文档处理超时")


def test_full_pipeline_and_tenant_isolation():
    with client:  # 触发 lifespan：建表/初始化管理员/启动 worker
        # 登录
        r = client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200, r.text
        admin_token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {admin_token}"}

        # 租户 1 的知识库：设备维护
        r = client.post("/api/admin/kbs", json={"name": "设备维护", "description": "设备维护知识库"},
                        headers=auth)
        assert r.status_code == 200, r.text
        kb1 = r.json()["id"]

        # 租户 2 的知识库：财务制度
        r = client.post("/api/admin/kbs", json={"name": "财务制度", "description": "财务知识库"},
                        headers=auth)
        assert r.status_code == 200, r.text
        kb2 = r.json()["id"]

        def upload(kb_id: int, filename: str, content: str) -> int:
            r = client.post(
                f"/api/admin/kbs/{kb_id}/documents",
                files={"file": (filename, content.encode("utf-8"), "text/markdown")},
                headers=auth,
            )
            assert r.status_code == 200, r.text
            return r.json()["id"]

        doc1 = upload(kb1, "维护手册.md", (
            "# 设备维护手册\n\n"
            "## 日常维护周期\n\n"
            "设备 A 的日常维护周期为每周一次，内容包括润滑、清洁与紧固检查。\n\n"
            "## 故障处理\n\n"
            "当设备 A 出现异响时，应停止运行并联系维修工程师。\n\n"
            "## 备件\n\n"
            "常用备件包括轴承与密封圈，库存由仓库部门管理。\n"
        ))
        doc2 = upload(kb2, "报销制度.md", (
            "# 差旅报销制度\n\n"
            "## 报销标准\n\n"
            "住宿费上限每晚 400 元，市内交通费实报实销。\n\n"
            "## 审批流程\n\n"
            "报销单需先经部门主管审批，再交财务部复核。\n\n"
            "## 发票要求\n\n"
            "发票抬头必须为公司全称，金额超过 1000 元需附明细。\n"
        ))

        # 等待处理完成
        d1 = _wait_doc_done(admin_token, doc1)
        d2 = _wait_doc_done(admin_token, doc2)
        assert d1["page_count"] >= 3 and d2["page_count"] >= 3

        # 切分块已生成，且元数据（页码/标题）已持久化
        r = client.get(f"/api/admin/kbs/{kb1}/chunks", headers=auth)
        chunks1 = r.json()
        assert len(chunks1) >= 3, f"kb1 chunks: {len(chunks1)}"
        assert all(c["metadata"] for c in chunks1), "chunk 元数据为空"
        assert all("page" in c["metadata"] for c in chunks1), "chunk 缺少 page 元数据"

        # 图谱接口可用（dummy LLM 返回空实体，流程跑通即可）
        r = client.get(f"/api/admin/kbs/{kb1}/entities", headers=auth)
        assert r.status_code == 200

        # 两个租户的密钥
        def create_key(name: str, kb_ids: list[int]) -> str:
            r = client.post("/api/admin/keys",
                            json={"name": name, "key_type": "search", "allowed_kb_ids": kb_ids},
                            headers=auth)
            assert r.status_code == 200, r.text
            return r.json()["key"]

        key1 = create_key("电脑1", [kb1])
        key2 = create_key("电脑2", [kb2])

        def search(key: str, query: str) -> dict:
            r = client.post("/api/v1/knowledge/search", json={"query": query, "top_k": 5},
                            headers={"Authorization": f"Bearer {key}"})
            assert r.status_code == 200, r.text
            return r.json()

        # 租户 1 检索自己的数据
        res1 = search(key1, "设备的维护周期")
        assert res1["permission_scope"]["kb_ids"] == [kb1]
        contents1 = " ".join(c["content"] for c in res1["chunks"])
        assert "维护" in contents1 and "报销" not in contents1, contents1[:200]

        # 租户 2 检索自己的数据
        res2 = search(key2, "报销怎么走流程")
        assert res2["permission_scope"]["kb_ids"] == [kb2]
        contents2 = " ".join(c["content"] for c in res2["chunks"])
        assert "报销" in contents2 and "维护" not in contents2, contents2[:200]

        # 租户 2 用"设备"查询：不得返回租户 1 的数据
        res3 = search(key2, "设备维护周期")
        contents3 = " ".join(c["content"] for c in res3["chunks"])
        assert "维护" not in contents3, contents3[:200]

        # 吊销密钥后立即失效
        keys = client.get("/api/admin/keys", headers=auth).json()
        kid = next(k["id"] for k in keys if k["name"] == "电脑1")
        r = client.post(f"/api/admin/keys/{kid}/revoke", headers=auth)
        assert r.status_code == 200
        r = client.post("/api/v1/knowledge/search", json={"query": "维护"},
                        headers={"Authorization": f"Bearer {key1}"})
        assert r.status_code == 401

        # 无密钥 / 无效密钥被拒
        r = client.post("/api/v1/knowledge/search", json={"query": "维护"})
        assert r.status_code == 401
        r = client.post("/api/v1/knowledge/search", json={"query": "维护"},
                        headers={"Authorization": "Bearer sk-invalid"})
        assert r.status_code == 401

        # 检索调试台（回归：曾因审计参数把 request 传入 api_key_id 导致 500）
        r = client.post(f"/api/admin/kbs/{kb1}/debug-search",
                        json={"query": "维护", "top_k": 5, "graph_depth": 1, "enable_graph": True},
                        headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["permission_scope"]["kb_ids"] == [kb1]

        # 审计日志有记录
        audit = client.get("/api/admin/audit", headers=auth).json()
        actions = {a["action"] for a in audit["items"]}
        assert "knowledge.search" in actions

        # 删除文档级联清理
        r = client.delete(f"/api/admin/documents/{doc1}", headers=auth)
        assert r.status_code == 200
        r = client.get(f"/api/admin/kbs/{kb1}/chunks", headers=auth)
        assert all(c["doc_id"] != doc1 for c in r.json())

    # 清理：先释放数据库连接再删文件
    from app.database import engine
    engine.dispose()
    for _p in ("test_smoke.db", "test_data"):
        if os.path.isdir(_p):
            shutil.rmtree(_p, ignore_errors=True)
        elif os.path.exists(_p):
            os.remove(_p)
