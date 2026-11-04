"""Minimal source-independent ingestion contracts (no speculative operations)."""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ConnectorItem:
    external_id: str
    title: str
    url: str | None
    author: str | None
    published_at: datetime | None
    content_text: str
    content_status: str
    content_hash: str
    raw_payload: dict


@dataclass(frozen=True)
class SyncBatch:
    items: list[ConnectorItem]
    etag: str | None = None
    last_modified: str | None = None


class SyncConnector(Protocol):
    def sync(
        self, config: dict, *, etag: str | None,
        last_modified: str | None,
    ) -> SyncBatch: ...
