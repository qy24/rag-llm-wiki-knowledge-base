"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    role: str

    model_config = {"from_attributes": True}


class KBIn(BaseModel):
    name: str
    description: str = ""
    chunk_size: int = Field(default=512, ge=64, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=1024)
    graph_extraction_enabled: bool = True
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    layout_type: str = "auto"  # auto | layered | force


class KBUpdateIn(BaseModel):
    """部分更新（如图谱页只切布局）——全部字段可选。"""
    name: str | None = None
    description: str | None = None
    chunk_size: int | None = Field(default=None, ge=64, le=4096)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1024)
    graph_extraction_enabled: bool | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    layout_type: str | None = None


class KBOut(BaseModel):
    id: int
    name: str
    description: str
    chunk_size: int
    chunk_overlap: int
    graph_extraction_enabled: bool
    llm_base_url: str
    llm_model: str
    layout_type: str = "auto"
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: int
    kb_id: int
    filename: str
    file_size: int
    file_type: str
    status: str
    error_msg: str = ""
    page_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChunkOut(BaseModel):
    id: int
    kb_id: int
    doc_id: int
    seq: int
    content: str
    metadata: dict = Field(default_factory=dict, validation_alias="meta")
    embedding_status: str = "pending"

    model_config = {"from_attributes": True, "populate_by_name": True}


class ChunkUpdateIn(BaseModel):
    content: str


class KeyIn(BaseModel):
    name: str
    key_type: str = "search"  # search | ingest | full
    allowed_kb_ids: list[int] = Field(default_factory=list)
    expires_at: datetime | None = None
    prompt_template: str = ""  # 密钥级回答提示词（空=用全局/内置）


class KeyOut(BaseModel):
    id: int
    name: str
    key_type: str
    allowed_kb_ids: list[int]
    expires_at: datetime | None
    revoked: bool
    last_used_at: datetime | None
    created_at: datetime
    prompt_template: str = ""
    key: str | None = None  # 创建时返回明文一次

    model_config = {"from_attributes": True}


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)
    graph_depth: int = Field(default=1, ge=0, le=3)
    enable_graph: bool = True


class GraphQueryIn(BaseModel):
    entity: str
    relation_types: list[str] | None = None
    depth: int = Field(default=2, ge=1, le=5)


class ChatContentPart(BaseModel):
    """OpenAI 视觉消息内容片段：text 或 image_url（data:image/... 或 http(s) 地址）。"""
    type: str
    text: str | None = None
    image_url: dict[str, Any] | None = None


class ChatMessage(BaseModel):
    role: str
    # 纯文本（原有调用不受影响）或 OpenAI 视觉格式的内容片段列表
    content: str | list[ChatContentPart]


class ChatIn(BaseModel):
    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = 0.2
    top_k: int = Field(default=8, ge=1, le=50)
    graph_depth: int = Field(default=1, ge=0, le=3)
    # 多客户会话记忆：传入客户唯一 ID（邮箱/订单号）时，系统自动恢复该客户上次对话
    # 上下文并接着处理；不同客户（或不同密钥）之间完全隔离；不传则保持无状态（兼容旧调用）
    session_id: str | None = Field(default=None, max_length=128)
    # 对话上下文（可选）：一段多方往来文本（客户/客服/平台邮件等，无角色、按时间顺序）。
    # 传入后系统通读理解来龙去脉，针对 messages 中最新一条（未回复的问题）给出连贯衔接的回复；
    # 不传则按普通单问题正常回答。
    context: str | list[str] | None = None
    # 咨询阶段（二选一）：
    # - is_after_sale 布尔：True=售后（默认，订单已存在直接给解决方案）；False=售前咨询
    # - consult_type 字符串：presale/aftersale/售前/售后（显式传时优先于 is_after_sale）
    is_after_sale: bool = True
    consult_type: str | None = None


def resolve_consult_type(consult_type: str | None, is_after_sale: bool) -> str:
    """归一咨询类型：显式字符串优先；否则按布尔（True=售后，False=售前）。"""
    if consult_type in ("presale", "aftersale", "售前", "售后"):
        return "aftersale" if consult_type in ("aftersale", "售后") else "presale"
    return "aftersale" if is_after_sale else "presale"


class AdminChatIn(BaseModel):
    """admin 对话测试台请求：选 API 密钥，检索范围=密钥绑定 KB（不越权），提示词=密钥配置。"""
    api_key_id: int
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = 0.2
    top_k: int = Field(default=8, ge=1, le=50)
    graph_depth: int = Field(default=1, ge=0, le=3)
    context: str | list[str] | None = None
    is_after_sale: bool = True
    consult_type: str | None = None


def content_has_images(content: str | list[ChatContentPart]) -> bool:
    """消息是否携带图片（视觉分支判定）。"""
    return isinstance(content, list) and any(
        isinstance(p, ChatContentPart) and p.type == "image_url" for p in content)


def content_text(content: str | list[ChatContentPart]) -> str:
    """提取消息的纯文本部分（用于检索/审计日志）。"""
    if isinstance(content, str):
        return content
    return "\n".join(
        p.text for p in content
        if isinstance(p, ChatContentPart) and p.type == "text" and p.text
    ).strip()


def content_to_parts(content: str | list[ChatContentPart]) -> list[dict]:
    """把消息内容转成可发给 OpenAI 兼容接口的 content 片段（dict 列表）。"""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [p.model_dump(exclude_none=True) for p in content]


class EntityUpdateIn(BaseModel):
    name: str | None = None
    type: str | None = None
    properties: dict[str, Any] | None = None
    verified: bool | None = None


class RelationUpdateIn(BaseModel):
    relation_type: str | None = None
    properties: dict[str, Any] | None = None
    verified: bool | None = None


class EntityCreateIn(BaseModel):
    name: str
    type: str = "术语"
    properties: dict[str, Any] = Field(default_factory=dict)


class RelationCreateIn(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class EntityMergeIn(BaseModel):
    source_id: str
    target_id: str


class AuditUpdateIn(BaseModel):
    """审计打标（进化学习）：rating=good/bad/''，note 备注。"""
    rating: str | None = None
    note: str | None = None


class SettingsIn(BaseModel):
    embedding_mode: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    graph_extraction_enabled: bool | None = None
    prompt_answer_system: str | None = None


class SettingsOut(BaseModel):
    embedding_mode: str
    embedding_base_url: str
    embedding_model: str
    llm_base_url: str
    llm_model: str
    graph_extraction_enabled: bool
    prompt_answer_system: str = ""
    # 密钥脱敏展示
    embedding_api_key_masked: str = ""
    llm_api_key_masked: str = ""
