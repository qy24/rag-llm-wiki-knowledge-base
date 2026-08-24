"""数据库引擎与会话。开发默认 SQLite（WAL），生产可切 PostgreSQL。"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False, "timeout": 30}
    # SQLite 文件目录必须预先存在
    db_path = settings.database_url.replace("sqlite:///", "", 1)
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册

    Base.metadata.create_all(bind=engine)
    _migrate()

def _migrate() -> None:
    """轻量迁移：为已有库补充新增列（SQLite ALTER TABLE ADD COLUMN 幂等）。"""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if insp.has_table("api_keys"):
        cols = {c["name"] for c in insp.get_columns("api_keys")}
        if "prompt_template" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE api_keys ADD COLUMN prompt_template TEXT DEFAULT ''"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
