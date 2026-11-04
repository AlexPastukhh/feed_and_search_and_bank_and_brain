"""RSS/Atom parsing: dependency-free, with bounded input and stable IDs."""
import hashlib
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

from info_hub.contracts import ConnectorItem

MAX_FEED_BYTES = 3_000_000
MAX_ITEMS = 200
MAX_RAW_ITEM = 100_000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.fragments.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.fragments.append(data)


def plain_text(markup: str | None) -> str:
    parser = _TextExtractor()
    parser.feed(markup or "")
    return " ".join(" ".join(parser.fragments).split())


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _value(element: ET.Element, name: str) -> str:
    child = _child(element, name)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def _date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed(data: bytes) -> list[ConnectorItem]:
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("RSS document exceeds maximum allowed size")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("RSS document contains prohibited XML declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("Invalid RSS/Atom XML") from exc

    is_atom = _local(root.tag) == "feed"
    if is_atom:
        items = [item for item in root if _local(item.tag) == "entry"]
    else:
        container = _child(root, "channel")
        if container is None:
            container = root
        items = [item for item in container if _local(item.tag) == "item"]
    if not items and _local(root.tag) not in {"feed", "rss", "RDF"}:
        raise ValueError("Not an RSS/Atom feed")

    parsed: list[ConnectorItem] = []
    for item in items[:MAX_ITEMS]:
        title = plain_text(_value(item, "title"))[:1000] or "(untitled)"
        url = _value(item, "link")
        if is_atom:
            links = [c for c in item if _local(c.tag) == "link"]
            preferred = next((c for c in links if c.get("rel", "alternate") == "alternate"), None)
            link = preferred if preferred is not None else (links[0] if links else None)
            url = link.get("href", "") if link is not None else ""
        identifier = _value(item, "id" if is_atom else "guid") or url
        published_raw = (_value(item, "published") or _value(item, "updated")) if is_atom else (
            _value(item, "pubDate") or _value(item, "date")
        )
        if not identifier:
            identifier = hashlib.sha256(
                (title + "|" + published_raw).encode("utf-8")
            ).hexdigest()
        author = _value(item, "author") or _value(item, "creator")
        if is_atom:
            author_element = _child(item, "author")
            if author_element is not None:
                author = _value(author_element, "name") or author
        content = (
            _value(item, "content") or _value(item, "encoded") or
            _value(item, "summary") or _value(item, "description")
        )
        text = plain_text(content)
        payload = {
            "format": "atom" if is_atom else "rss",
            "raw_xml": ET.tostring(item, encoding="unicode")[:MAX_RAW_ITEM],
        }
        checksum = hashlib.sha256(json.dumps(
            [title, url, author, published_raw, text], ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        if len(identifier) > 700:
            identifier = "sha256:" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        parsed.append(ConnectorItem(
            external_id=identifier,
            title=title,
            url=url or None,
            author=author[:500] if author else None,
            published_at=_date(published_raw),
            content_text=text,
            # A feed body can be truncated by the publisher. Do not claim full article.
            content_status="partial" if text else "metadata_only",
            content_hash=checksum,
            raw_payload=payload,
        ))
    return parsed
