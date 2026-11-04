"""Connector registry and first specialized RSS/Atom adapter."""
from info_hub.contracts import SyncBatch, SyncConnector
from info_hub.feeds import parse_feed
from info_hub.fetch import fetch_feed


class RssAtomConnector:
    def sync(
        self, config: dict, *, etag: str | None,
        last_modified: str | None,
    ) -> SyncBatch:
        url = config["feed_url"]
        status, body, new_etag, new_modified = fetch_feed(
            url, etag=etag, last_modified=last_modified,
        )
        items = parse_feed(body) if status == 200 else []
        return SyncBatch(items=items, etag=new_etag, last_modified=new_modified)


_CONNECTORS: dict[str, SyncConnector] = {"rss_atom": RssAtomConnector()}


def get_connector(key: str) -> SyncConnector:
    try:
        return _CONNECTORS[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported connector: {key}") from exc
