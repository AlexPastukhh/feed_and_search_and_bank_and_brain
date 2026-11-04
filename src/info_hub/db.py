"""Database foundation shared by API, Alembic and worker."""
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase

from info_hub.settings import get_settings


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy domain models."""


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)
