"""云端大模型（OpenAI 兼容）客户端：图谱抽取 + 聚合生成。"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

import httpx

from ..config import Settings

_EXCLUDE_PATTERNS = [
    re.compile(r"(?:除了|除去|剔除|排除|不要)\s*([^的，。,、和及与所有都以外]+)"),
    re.compile(r"([^的，。,、和及与所有都]+)\s*以外"),
]


def rule_exclude_terms(query: str) -> list[str]:
    """中文规则兜底：从'除了X/不要X/X以外'等表达中提取排除词（不依赖 LLM）。"""
    for pat in _EXCLUDE_PATTERNS:
        m = pat.search(query)
        if m and m.group(1).strip():
            return [m.group(1).strip()]
    return []

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
    @abstractmethod
    def chat(self, messages: list[dict], json_mode: bool = False,
             temperature: float = 0.2, max_tokens: int = 2048) -> str: ...

    def configured(self) -> bool:
        return True


class OpenAICompatLLM(LLMClient):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    def chat(self, messages: list[dict], json_mode: bool = False,
             temperature: float = 0.2, max_tokens: int = 2048) -> str:
        body: dict = {"model": self.model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body, timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class DummyLLM(LLMClient):
    """离线占位：图谱抽取返回空结构，对话返回固定文本。仅开发/测试用。"""

    def __init__(self, settings: Settings | None = None):
        pass

    def configured(self) -> bool:
        return True

    def chat(self, messages: list[dict], json_mode: bool = False,
             temperature: float = 0.2, max_tokens: int = 2048) -> str:
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
             temperature: float = 0.2, max_tokens: int = 2048) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # 关闭思考链，直接输出
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        resp = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
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
        json_mode=True, max_tokens=4096,
    )
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"entities": [], "relations": []}


def query_entities(llm: LLMClient, query: str) -> list[str]:
    content = llm.chat(
        [{"role": "system", "content": QUERY_ENTITY_SYSTEM},
         {"role": "user", "content": query}],
        json_mode=True, max_tokens=512,
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
        json_mode=True, max_tokens=512,
    )
    data = _extract_json(content)
    return {
        "anchors": [str(x) for x in data.get("anchors", []) if x],
        "relation_types": [str(x) for x in data.get("relation_types", []) if x],
        "entity_types": [str(x) for x in data.get("entity_types", []) if x],
        "exclude": [str(x) for x in data.get("exclude", []) if x],
    }
