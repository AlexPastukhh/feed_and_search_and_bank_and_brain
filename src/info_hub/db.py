"""Database foundation shared by API, Alembic and worker."""
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from info_hub.settings import get_settings


class Base(DeclarativeBase):
    """Declarative base for database models."""


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def open_session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as session:
        yield session
