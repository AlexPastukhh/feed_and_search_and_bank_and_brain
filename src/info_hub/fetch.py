"""Conservative public-HTTP fetch for RSS feeds."""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit


def validate_feed_url(url: str, *, resolve_dns: bool = False) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("RSS URL must use HTTP or HTTPS and include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credentials embedded in URLs are not allowed")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ValueError("Local HTTP hosts are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL port") from exc
    if port is not None and port not in {80, 443}:
        raise ValueError("Only standard HTTP/HTTPS ports are supported")
    if not resolve_dns:
        try:
            ip = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return
        if not ip.is_global:
            raise ValueError("Private or local HTTP hosts are not allowed")
        return
    results = socket.getaddrinfo(parsed.hostname, port or (443 if parsed.scheme == "https" else 80))
    if not results:
        raise ValueError("DNS returned no addresses")
    for result in results:
        ip = ipaddress.ip_address(result[4][0])
        if not ip.is_global:
            raise ValueError("Private or local HTTP hosts are not allowed")


def fetch_feed(url: str, *, etag: str | None, last_modified: str | None):
    """Return (status, body, etag, last-modified); never follow unchecked redirects."""
    import httpx

    headers = {"User-Agent": "InfoHubFeed/0.1 (+personal RSS reader)"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    current = url
    with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False) as client:
        for _ in range(5):
            validate_feed_url(current, resolve_dns=True)
            with client.stream("GET", current, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    target = response.headers.get("location")
                    if not target:
                        raise ValueError("Redirect response omitted Location")
                    current = urljoin(current, target)
                    continue
                if response.status_code == 304:
                    return (304, b"", response.headers.get("etag") or etag,
                            response.headers.get("last-modified") or last_modified)
                response.raise_for_status()
                chunks = []
                size = 0
                for part in response.iter_bytes():
                    size += len(part)
                    if size > 3_000_000:
                        raise ValueError("RSS response exceeds 3 MB limit")
                    chunks.append(part)
                return (200, b"".join(chunks), response.headers.get("etag"),
                        response.headers.get("last-modified"))
    raise ValueError("Too many feed redirects")
