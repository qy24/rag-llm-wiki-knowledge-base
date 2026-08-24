"""Embedding 抽象：openai（云端兼容，默认）| dummy（离线开发占位）。"""
from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod

import httpx

from ..config import Settings


class Embedder(ABC):
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """入库（文档侧）嵌入：指令式模型可在此加 passage 前缀"""
        return self.embed(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """检索（查询侧）嵌入：指令式模型可在此加 query 前缀"""
        return self.embed(texts)


class OpenAICompatEmbedder(Embedder):
    def __init__(self, settings: Settings):
        self.base_url = settings.embedding_base_url.rstrip("/")
        # OpenAI 兼容网关一般以 /v1 提供接口；只填根域名时自动补全（与 LLM 客户端一致）
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.api_key = settings.embedding_api_key
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self._batch = settings.embedding_batch_size
        # Qwen3-Embedding 等指令式模型：查询/文档推荐加前后缀
        self._query_prefix = settings.embedding_query_prefix or ""
        self._passage_prefix = settings.embedding_passage_prefix or ""

    def _request(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i:i + self._batch]
            resp = httpx.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": batch},
                timeout=600,  # 本地大模型（Ollama）首次加载可能较慢
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda x: x["index"])
            out.extend(d["embedding"] for d in data)
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._request(texts)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._passage_prefix:
            texts = [self._passage_prefix + t for t in texts]
        return self._request(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if self._query_prefix:
            texts = [self._query_prefix + t for t in texts]
        return self._request(texts)


class DummyEmbedder(Embedder):
    """离线占位：确定性哈希向量。仅用于无网络开发/测试，检索效果有限。"""

    def __init__(self, settings: Settings):
        self.dim = 256

    def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = [0.0] * self.dim
            for i in range(len(text) - 1):
                gram = text[i:i + 2]
                h = int(hashlib.md5(gram.encode()).hexdigest()[:8], 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 16) % 2 == 0 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            results.append([v / norm for v in vec])
        return results


def get_embedder(settings: Settings, model_override: str = "") -> Embedder:
    if settings.embedding_mode == "dummy":
        return DummyEmbedder(settings)
    return OpenAICompatEmbedder(settings)
