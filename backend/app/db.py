from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow() -> datetime:
    """Naive UTC timestamp (keeps MySQL DATETIME handling simple)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db():
    with SessionLocal() as db:
        yield db
