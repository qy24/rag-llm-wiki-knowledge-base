"""FastAPI 依赖：管理员 JWT 鉴权、API 密钥解析与权限范围注入。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import ApiKey, User
from .security import decode_access_token, hash_api_key

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供凭证")
    user_id = decode_access_token(creds.credentials)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "凭证无效或已过期")
    user = db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """写操作依赖：仅 admin 角色可执行；只读账号（viewer）403。"""
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只读账号无修改权限")
    return user


@dataclass
class KeyScope:
    api_key: ApiKey
    user: User | None
    allowed_kb_ids: list[int] = field(default_factory=list)


def resolve_key_scope(db: Session, raw_key: str) -> KeyScope | None:
    """纯函数版密钥解析：供 FastAPI 依赖与 MCP 中间件共用。无效/吊销/过期返回 None。"""
    key_hash = hash_api_key(raw_key)
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if api_key is None:
        return None
    if api_key.revoked:
        return None
    if api_key.expires_at is not None and api_key.expires_at < datetime.now():
        return None
    # last_used_at 节流更新（>60s 才写），避免每次检索都触发 SQLite 写锁
    now = datetime.now()
    if api_key.last_used_at is None or (now - api_key.last_used_at).total_seconds() > 60:
        api_key.last_used_at = now
        try:
            db.commit()
        except Exception:
            db.rollback()
    user = db.get(User, api_key.user_id)
    return KeyScope(api_key=api_key, user=user,
                    allowed_kb_ids=list(api_key.allowed_kb_ids or []))


def get_key_scope(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> KeyScope:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供 API 密钥")
    scope = resolve_key_scope(db, creds.credentials)
    if scope is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API 密钥无效、已吊销或已过期")
    return scope


def require_key_type(*types: str):
    def checker(scope: KeyScope = Depends(get_key_scope)) -> KeyScope:
        if scope.api_key.key_type not in types:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "该密钥类型无权执行此操作")
        return scope
    return checker
