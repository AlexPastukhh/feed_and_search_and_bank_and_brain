"""On-demand extraction of public HTML articles.

No login, JS execution, proxies or paywall handling. URL validation follows the
same conservative rule set as RSS. This is not a general web crawling system.
"""
import hashlib
from dataclasses import dataclass
from urllib.parse import urljoin

from info_hub.fetch import validate_feed_url

MAX_HTML_BYTES = 2_500_000


@dataclass(frozen=True)
class ExtractedPage:
    source_url: str
    text: str
    content_hash: str


def extract_page_text(html: bytes, *, url: str) -> str:
    from trafilatura import extract

    text = extract(html, url=url, output_format="txt",
                   include_comments=False, include_tables=True)
    return (text or "").strip()


def fetch_public_article(url: str) -> ExtractedPage:
    import httpx

    current = url
    with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
        for _ in range(5):
            validate_feed_url(current, resolve_dns=True)
            with client.stream(
                "GET", current,
                headers={"User-Agent": "InfoHubArticle/0.1 (on-demand personal archive)"},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect response omitted Location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not (
                    "text/html" in content_type or "application/xhtml+xml" in content_type
                ):
                    raise ValueError("URL did not return an HTML page")
                parts: list[bytes] = []
                size = 0
                for piece in response.iter_bytes():
                    size += len(piece)
                    if size > MAX_HTML_BYTES:
                        raise ValueError("HTML page exceeds 2.5 MB limit")
                    parts.append(piece)
                raw = b"".join(parts)
                text = extract_page_text(raw, url=current)
                if len(text) < 180:
                    raise ValueError("No substantial article text was found")
                return ExtractedPage(
                    source_url=current,
                    text=text,
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
    raise ValueError("Too many article redirects")
