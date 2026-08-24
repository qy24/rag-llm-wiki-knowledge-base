"""视觉 RAG 集成测试：带图提问 → 图片理解 → 检索内部数据+内部图片 → 视觉生成。

启动两个真实服务器：
- fake 视觉 OpenAI（动态端口）：embedding + chat（描述/统计图片数量）
- 主应用（动态端口）：EMBEDDING_MODE=openai 指向 fake

验证：
1. 图片文档入库（占位文本块 + 图片实体 + 配图关系）
2. /v1/chat/completions 带图调用：返回"用户图1张，内部图1张"，
   且内部图片确实被组装进发给云端模型的请求
3. 租户隔离：仅授权 kb2 的密钥看不到 kb1 的内部图片
4. 参数校验：图片超 4 张 / image_url 缺 url → 400
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import socket
import threading
import time

# 环境必须在导入 app 前设置
os.environ["EMBEDDING_MODE"] = "openai"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["GRAPH_BACKEND"] = "local"
os.environ["DATABASE_URL"] = "sqlite:///./test_vision.db"
os.environ["DATA_DIR"] = "./test_vision_data"
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ["LLM_API_STYLE"] = "openai"

for _p in ("test_vision.db", "test_vision_data"):
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
os.environ["LLM_MODEL"] = "fake-vision-model"

import httpx  # noqa: E402
from fake_vision_server import app as fake_app  # noqa: E402
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


def _tiny_png(rgb=(200, 30, 30), size=(64, 48)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


def test_vision_rag():
    from fake_vision_server import LAST_DESCRIBE_REQ, LAST_FINAL_REQ

    # 登录
    r = _post("/api/admin/login", {"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    kb1 = _post("/api/admin/kbs", {"name": "视觉库1", "description": ""}, token).json()["id"]
    kb2 = _post("/api/admin/kbs", {"name": "视觉库2", "description": ""}, token).json()["id"]

    # 先建同名实体"产品A"，图片上传后自动建 配图 关系
    r = _post(f"/api/admin/kbs/{kb1}/entities", {"name": "产品A", "type": "产品"}, token)
    assert r.status_code == 200, r.text

    # 上传图片文档 + 文字文档到 kb1
    files = {"file": ("产品A.png", _tiny_png((200, 30, 30)), "image/png")}
    img_doc = _post(f"/api/admin/kbs/{kb1}/documents", files=files, token=token)
    assert img_doc.status_code == 200, img_doc.text
    img_doc_id = img_doc.json()["id"]
    md_doc = _post(f"/api/admin/kbs/{kb1}/documents", token=token,
                   files={"file": ("产品介绍.md",
                                   "产品A是公司最新款智能遥控器，支持Type-C接口充电。".encode("utf-8"),
                                   "text/markdown")})
    assert md_doc.status_code == 200, md_doc.text
    _wait_doc_done(token, img_doc_id)
    _wait_doc_done(token, md_doc.json()["id"])

    # 图片实体已生成并自动建立配图关系
    ents = _get(f"/api/admin/kbs/{kb1}/entities", token).json()["items"]
    img_ents = [e for e in ents if e.get("type") == "图片"]
    assert len(img_ents) >= 1, ents
    assert img_ents[0]["properties"].get("image_doc_id") == img_doc_id
    rels = _get(f"/api/admin/kbs/{kb1}/relations", token).json()["items"]
    assert any(r["relation_type"] == "配图" for r in rels), rels

    # 密钥：key1 绑 kb1，key2 绑 kb2
    key1 = _post("/api/admin/keys", {"name": "视觉电脑1", "key_type": "search",
                                     "allowed_kb_ids": [kb1]}, token).json()["key"]
    key2 = _post("/api/admin/keys", {"name": "视觉电脑2", "key_type": "search",
                                     "allowed_kb_ids": [kb2]}, token).json()["key"]

    # 用户附图（base64 data URL）
    user_img_b64 = base64.b64encode(_tiny_png((30, 200, 30), (80, 60))).decode()
    user_img_url = "data:image/png;base64," + user_img_b64

    # ---- 主场景：带图提问，应返回"用户图1张，内部图1张" ----
    LAST_DESCRIBE_REQ.clear()
    LAST_FINAL_REQ.clear()
    r = _post("/api/v1/chat/completions",
              {"messages": [{"role": "user", "content": [
                  {"type": "text", "text": "这是什么产品？"},
                  {"type": "image_url", "image_url": {"url": user_img_url}},
              ]}]}, key1)
    assert r.status_code == 200, r.text
    resp = r.json()
    answer = resp["choices"][0]["message"]["content"]
    assert answer == "模拟视觉回答：用户图1张，内部图1张。", answer

    # 图片理解步骤确实把用户图发给了模型
    assert LAST_DESCRIBE_REQ.get("num_images") == 1, LAST_DESCRIBE_REQ
    # 最终生成步骤：用户图 + 内部图都被发出
    assert LAST_FINAL_REQ.get("user_imgs") == 1, LAST_FINAL_REQ
    assert LAST_FINAL_REQ.get("internal_imgs") == 1, LAST_FINAL_REQ

    # 内部图片清单返回（doc_id / 文件名）
    internal = resp.get("internal_images", [])
    assert any(i["doc_id"] == img_doc_id and i["filename"] == "产品A.png"
               for i in internal), internal
    assert len(resp.get("sources", [])) > 0

    # ---- 租户隔离：key2（仅 kb2）看不到 kb1 的内部图片 ----
    r = _post("/api/v1/chat/completions",
              {"messages": [{"role": "user", "content": [
                  {"type": "text", "text": "这是什么产品？"},
                  {"type": "image_url", "image_url": {"url": user_img_url}},
              ]}]}, key2)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "模拟视觉回答：用户图1张，内部图0张。"
    assert r.json().get("internal_images") == []

    # ---- 参数校验 ----
    # 超过 4 张图 → 400
    too_many = [{"type": "image_url", "image_url": {"url": user_img_url}} for _ in range(5)]
    r = _post("/api/v1/chat/completions",
              {"messages": [{"role": "user", "content": too_many}]}, key1)
    assert r.status_code == 400, r.text
    # image_url 缺 url → 400
    r = _post("/api/v1/chat/completions",
              {"messages": [{"role": "user", "content": [
                  {"type": "text", "text": "hi"},
                  {"type": "image_url", "image_url": {}},
              ]}]}, key1)
    assert r.status_code == 400, r.text
    # 非法 scheme → 400
    r = _post("/api/v1/chat/completions",
              {"messages": [{"role": "user", "content": [
                  {"type": "image_url", "image_url": {"url": "file:///C:/x.png"}},
              ]}]}, key1)
    assert r.status_code == 400, r.text

    # 清理
    from app.database import engine
    engine.dispose()
    for _p in ("test_vision.db", "test_vision_data"):
        if os.path.isdir(_p):
            shutil.rmtree(_p, ignore_errors=True)
        elif os.path.exists(_p):
            os.remove(_p)
