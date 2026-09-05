"""云端大模型（OpenAI 兼容）客户端：图谱抽取 + 聚合生成。"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod

import httpx

from ..config import Settings

GRAPH_EXTRACT_SYSTEM = (
    "你是知识图谱抽取引擎。从给定的文本中抽取实体与关系。"
    "实体类型：人物/组织/产品/术语/事件/指标/地点。"
    '只输出 JSON：{"entities":[{"name":"..","type":".."}],'
    '"relations":[{"source":"..","target":"..","type":".."}]}。'
    "实体名要简洁规范，同名实体合并；relation 的 source/target 必须是已列出的实体名。"
    "如果文本没有实体，输出 {\"entities\":[],\"relations\":[]}。"
)

QUERY_ENTITY_SYSTEM = (
    "你是信息检索助手。从用户查询中识别可能指向知识库实体的关键名词（人名/组织/产品/术语/指标）。"
    '只输出 JSON：{"entities":["名称1","名称2"]}。没有则输出 {"entities":[]}。'
)

QUERY_INTENT_SYSTEM = (
    "你是检索查询意图解析器。把用户的检索问题解析成结构化 JSON，只输出 JSON，不要任何解释。\n"
    '格式：{"anchors":["点名实体"], "relation_types":["关系类型"], "entity_types":["实体类型"], "exclude":["要排除的对象"]}\n'
    "示例：\n"
    '问题"给我美国站的ASIN"→{"anchors":["美国"],"relation_types":[],"entity_types":["ASIN"],"exclude":[]}\n'
    '问题"给我加拿大除了遥控器的所有产品"→{"anchors":["加拿大"],"relation_types":["产品"],"entity_types":[],"exclude":["遥控器"]}\n'
    '问题"加拿大的品牌"→{"anchors":["加拿大"],"relation_types":["品牌"],"entity_types":[],"exclude":[]}\n'
    "规则：anchors=查询点名的具体实体；relation_types=查询提到的关系类型；"
    "entity_types=查询提到的实体类型词；exclude=查询明确排除的对象（除了X/不要X/排除X中的X）。"
    "没有的字段用空数组[]，不要用英文翻译中文术语。"
)

IMAGE_DESCRIBE_SYSTEM = (
    "你是图像理解引擎，服务于企业知识库检索。"
    "请用简洁的中文要点描述图片内容，重点提取可用于检索的事实："
    "图中的物体、品牌/文字、型号、数量、场景、人物动作等。"
    "不超过 80 字，不要臆测图中没有的信息。"
)


def _extract_json(text: str) -> dict:
    """鲁棒解析 LLM 输出中的 JSON（兼容 markdown 代码块/前后缀文字）。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return {}


class LLMClient(ABC):
    # 是否支持图片输入（视觉模型）。OpenAI 兼容端点按视觉模型配置视为支持；
    # 本机 Ollama 的 qwen3.5 无视觉能力，默认不支持。
    supports_vision: bool = False

    @abstractmethod
    def chat(self, messages: list[dict], json_mode: bool = False,
             temperature: float = 0.2, max_tokens: int = 2048,
             timeout: int | None = None) -> str: ...

    def configured(self) -> bool:
        return True


class OpenAICompatLLM(LLMClient):
    supports_vision = True

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        # 大多数 OpenAI 兼容网关（OpenAI/aihubmix 等）以 /v1 提供接口；
        # 用户只填根域名（如 https://aihubmix.com）时自动补全，避免 401/404
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        # NVIDIA NIM：模型 id 带组织前缀（deepseek-ai/deepseek-v4-flash-0731），缺前缀会 404
        if "nvidia" in self.base_url.lower() and "/" not in model:
            for prefix, org in (("deepseek", "deepseek-ai"), ("qwen", "qwen"),
                                ("llama", "meta"), ("yi", "01-ai"), ("mistral", "mistralai")):
                if model.startswith(prefix):
                    model = f"{org}/{model}"
                    break
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    def chat(self, messages: list[dict], json_mode: bool = False,
             temperature: float = 0.2, max_tokens: int = 2048,
             timeout: int | None = None) -> str:
        body: dict = {"model": self.model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        effective_timeout = timeout or self.timeout
        # 轻量重试：云端限流（429）/5xx/网络断连（RemoteProtocolError 等）时退避重试，
        # 最多 3 次（间隔 1s/2s/3s）——NVIDIA 高峰期断连常见，不重试会直接 502
        import time
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body, timeout=effective_timeout,
                )
                if resp.status_code not in (429, 500, 502, 503, 504):
                    resp.raise_for_status()
                    msg = resp.json()["choices"][0]["message"]
                    content = msg.get("content") or ""
                    if content:
                        return content
                    # 思考模型（content 空、思考链在 reasoning_content）被 max_tokens 截断时视为失败重试
                    finish = resp.json()["choices"][0].get("finish_reason")
                    if finish == "length":
                        last_exc = RuntimeError("模型思考/回答被 max_tokens 截断（content 为空），请调大 max_tokens")
                    else:
                        last_exc = RuntimeError("模型返回空 content")
                else:
                    last_exc = httpx.HTTPStatusError(
                        f"Server error '{resp.status_code}'", request=resp.request, response=resp)
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                # 5xx 以外的状态码错误/网络层异常也纳入重试
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code not in (429, 500, 502, 503, 504, 529):
                    raise
                last_exc = e
            if attempt < 2:
                time.sleep(attempt + 1)
        assert last_exc is not None
        raise last_exc


class DummyLLM(LLMClient):
    """离线占位：图谱抽取返回空结构，对话返回固定文本。仅开发/测试用。"""

    def __init__(self, settings: Settings | None = None):
        pass

    def configured(self) -> bool:
        return True

    def chat(self, messages: list[dict], json_mode: bool = False,
             temperature: float = 0.2, max_tokens: int = 2048,
             timeout: int | None = None) -> str:
        if json_mode:
            return '{"entities":[],"relations":[]}'
        return "（离线模式回答：未配置云端大模型）"


class OllamaNativeLLM(LLMClient):
    """Ollama 原生接口：qwen3 系思考模型必须 think=false 才能拿到 content（OpenAI 兼容接口会输出空）。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 300):
        # base_url 形如 http://127.0.0.1:11434/v1，去掉尾部 /v1
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.model = model
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(self.model)

    def chat(self, messages: list[dict], json_mode: bool = False,
             temperature: float = 0.2, max_tokens: int = 2048,
             timeout: int | None = None) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # 关闭思考链，直接输出
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        resp = httpx.post(f"{self.base_url}/api/chat", json=body,
                          timeout=timeout or self.timeout)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


def resolve_llm(settings: Settings, kb=None) -> LLMClient:
    """按知识库覆盖 -> 全局配置 -> 离线占位 解析 LLM 客户端。"""
    if kb is not None and kb.llm_base_url and kb.llm_api_key and kb.llm_model:
        return OpenAICompatLLM(kb.llm_base_url, kb.llm_api_key, kb.llm_model)
    if settings.llm_api_key and settings.llm_base_url:
        if settings.llm_api_style == "ollama_native":
            return OllamaNativeLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
        return OpenAICompatLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    return DummyLLM()


def extract_graph(llm: LLMClient, texts: list[str]) -> dict:
    """从若干切分块抽取实体/关系。"""
    prompt = "\n\n---\n\n".join(
        f"[片段 {i + 1}]\n{t[:1500]}" for i, t in enumerate(texts)
    )
    content = llm.chat(
        [{"role": "system", "content": GRAPH_EXTRACT_SYSTEM},
         {"role": "user", "content": prompt}],
        json_mode=True, max_tokens=8192,
        timeout=600,  # 思考模型批量抽取慢，放宽读超时
    )
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"entities": [], "relations": []}


def query_entities(llm: LLMClient, query: str) -> list[str]:
    content = llm.chat(
        [{"role": "system", "content": QUERY_ENTITY_SYSTEM},
         {"role": "user", "content": query}],
        json_mode=True, max_tokens=1024,
    )
    try:
        raw = json.loads(content).get("entities", [])
    except json.JSONDecodeError:
        return []
    out = []
    for item in raw:
        name = item if isinstance(item, str) else (item or {}).get("name", "")
        if name:
            out.append(str(name).strip())
    return [n for n in out if n]


def parse_query_intent(llm: LLMClient, query: str) -> dict:
    """LLM 解析查询意图：点名实体/关系类型/实体类型/排除对象。解析失败返回空意图（回退规则匹配）。"""
    content = llm.chat(
        [{"role": "system", "content": QUERY_INTENT_SYSTEM},
         {"role": "user", "content": query}],
        json_mode=True, max_tokens=2048,  # 思考模型（deepseek 系）需为思考链留足 token
    )
    data = _extract_json(content)
    return {
        "anchors": [str(x) for x in data.get("anchors", []) if x],
        "relation_types": [str(x) for x in data.get("relation_types", []) if x],
        "entity_types": [str(x) for x in data.get("entity_types", []) if x],
        "exclude": [str(x) for x in data.get("exclude", []) if x],
    }


def describe_images(llm: LLMClient, image_parts: list[dict], text_hint: str = "") -> str:
    """视觉 RAG 第一步：让视觉模型理解用户附图，产出用于检索的文字描述。

    image_parts 为 OpenAI 视觉格式的 image_url 片段（dict 列表）。
    模型不支持视觉或调用失败时抛异常，由调用方回退纯文本检索。
    """
    user_content: list[dict] = [
        {"type": "text", "text": text_hint or "请描述这张图片的内容"}
    ]
    user_content.extend(image_parts)
    content = llm.chat(
        [{"role": "system", "content": IMAGE_DESCRIBE_SYSTEM},
         {"role": "user", "content": user_content}],
        temperature=0.1, max_tokens=1024,
    )
    return content.strip()
