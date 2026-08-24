"""模拟 OpenAI 兼容服务器（视觉 RAG 测试用）：/v1/embeddings + /v1/chat/completions。

- embeddings：确定性 16 维哈希向量（与 fake_openai_server 一致）；
- chat/completions：
  - system 含"图像理解引擎"→ 图片理解描述（返回"描述结果：图中是产品A。"）
  - 其他 → 统计末条消息中用户附图/内部图片数量，返回"模拟视觉回答：用户图X张，内部图Y张。"
记录最近一次描述请求与最终生成请求，供测试断言图片确实被发出。
"""
from __future__ import annotations

import hashlib
import math

from fastapi import FastAPI

app = FastAPI(title="fake-vision-openai")

LAST_DESCRIBE_REQ: dict = {}
LAST_FINAL_REQ: dict = {}

INTERNAL_CAPTION = "本地知识库检索到的相关图片"


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


# json_mode 时的图谱抽取/意图解析返回：只返回输入文本中出现的实体
EXTRACT_JSON = {
    "entities": [
        {"name": "产品A", "type": "产品"},
        {"name": "Type-C", "type": "术语"},
    ],
    "relations": [
        {"source": "产品A", "target": "Type-C", "type": "支持"},
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
    system = messages[0].get("content", "") if messages else ""
    last = messages[-1] if messages else {}
    content = last.get("content", "")
    parts = content if isinstance(content, list) else [{"type": "text", "text": content}]

    image_parts = [p for p in parts if p.get("type") == "image_url"]
    text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]

    json_mode = body.get("response_format", {}).get("type") == "json_object"
    if json_mode:
        joined = " ".join(text_parts) + " ".join(
            str(p.get("image_url", {}).get("url", "")) for p in image_parts)
        related = [e for e in EXTRACT_JSON["entities"] if e["name"] in joined]
        relations = [r for r in EXTRACT_JSON["relations"]
                     if r["source"] in [e["name"] for e in related]
                     and r["target"] in [e["name"] for e in related]]
        import json as _json
        content_out = _json.dumps({"entities": related, "relations": relations},
                                  ensure_ascii=False)
    elif isinstance(system, str) and "图像理解引擎" in system:
        # 原地更新（clear+update），保持与测试进程共享的同一 dict 对象
        LAST_DESCRIBE_REQ.clear()
        LAST_DESCRIBE_REQ.update({
            "num_images": len(image_parts),
            "texts": " | ".join(text_parts),
        })
        content_out = "描述结果：图中是产品A。"
    else:
        # 内部图片固定放在"（以下为本地知识库检索到的相关图片...）"caption 之后
        saw_caption = False
        user_imgs = 0
        internal_imgs = 0
        for p in parts:
            if p.get("type") == "image_url":
                if saw_caption:
                    internal_imgs += 1
                else:
                    user_imgs += 1
            elif INTERNAL_CAPTION in (p.get("text") or ""):
                saw_caption = True
        global LAST_FINAL_REQ
        LAST_FINAL_REQ.clear()
        LAST_FINAL_REQ.update({
            "num_images": len(image_parts),
            "user_imgs": user_imgs,
            "internal_imgs": internal_imgs,
            "texts": " | ".join(text_parts),
        })
        content_out = f"模拟视觉回答：用户图{user_imgs}张，内部图{internal_imgs}张。"

    return {
        "id": "chatcmpl-fake-vision",
        "object": "chat.completion",
        "model": body.get("model", "fake-vision-model"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content_out},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
