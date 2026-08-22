"""模拟 OpenAI 兼容服务器（测试用）：/v1/embeddings + /v1/chat/completions。

- embeddings：确定性 16 维哈希向量（归一化），走真实 OpenAICompatEmbedder 代码路径；
- chat/completions：json_mode 时返回固定实体/关系 JSON（验证图谱抽取链路），
  否则返回"模拟云端回答：..."。
"""
from __future__ import annotations

import hashlib
import math

from fastapi import FastAPI

app = FastAPI(title="fake-openai")


def _embed(text: str) -> list[float]:
    dim = 16
    vec = [0.0] * dim
    for i in range(len(text) - 1):
        gram = text[i:i + 2]
        h = int(hashlib.md5(gram.encode()).hexdigest()[:8], 16)
        idx = h % dim
        vec[idx] += 1.0 if (h >> 16) % 2 == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


EXTRACT_JSON = {
    "entities": [
        {"name": "设备A", "type": "设备"},
        {"name": "维护周期", "type": "术语"},
        {"name": "轴承", "type": "备件"},
    ],
    "relations": [
        {"source": "设备A", "target": "维护周期", "type": "具有"},
        {"source": "设备A", "target": "轴承", "type": "使用"},
    ],
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/embeddings")
def embeddings(body: dict):
    texts = body.get("input", [])
    if isinstance(texts, str):
        texts = [texts]
    data = [{"index": i, "embedding": _embed(t)} for i, t in enumerate(texts)]
    return {"object": "list", "data": data, "model": body.get("model", "fake-embed")}


@app.post("/v1/chat/completions")
def chat_completions(body: dict):
    messages = body.get("messages", [])
    user_content = messages[-1].get("content", "") if messages else ""
    json_mode = body.get("response_format", {}).get("type") == "json_object"
    if json_mode:
        # 模拟真实 LLM：只返回与输入文本相关的实体（查询实体提取/图谱抽取都只提相关项）
        related = [
            e for e in EXTRACT_JSON["entities"]
            if e["name"] in user_content
        ]
        relations = [
            r for r in EXTRACT_JSON["relations"]
            if r["source"] in [e["name"] for e in related]
            and r["target"] in [e["name"] for e in related]
        ]
        content = __import__("json").dumps(
            {"entities": related, "relations": relations}, ensure_ascii=False)
    else:
        content = "模拟云端回答：" + user_content[:40]
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "model": body.get("model", "fake-model"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
