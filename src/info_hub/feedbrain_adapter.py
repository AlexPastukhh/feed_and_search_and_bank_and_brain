"""HTTP-only Feedbrain capability adapter; no imports of Feedbrain storage or services."""
import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from info_hub.action_broker import ToolExecutionError
from info_hub.action_workflow import SOURCE_PATTERN

MAX_HTTP_RESPONSE_BYTES = 64 * 1024


def validate_feedbrain_bindings(bindings: Mapping[str, int]) -> dict[str, int]:
    """Logical source aliases map only to explicitly allowed positive subscription IDs."""
    if not isinstance(bindings, dict):
        raise ValueError("Feedbrain bindings must be an object")
    normalized = {}
    for alias, subscription_id in bindings.items():
        if not isinstance(alias, str) or not SOURCE_PATTERN.fullmatch(alias):
            raise ValueError("Invalid logical source alias in Feedbrain bindings")
        if type(subscription_id) is not int or subscription_id <= 0:
            raise ValueError(f"Invalid subscription ID for source alias: {alias}")
        normalized[alias] = subscription_id
    return normalized


def load_feedbrain_bindings(raw: str) -> dict[str, int]:
    """Parse a trusted JSON environment variable, not data from a user Action."""
    if not raw or len(raw) > 8192:
        raise ValueError("Feedbrain bindings must be a nonempty JSON object (max 8192 chars)")
    def unique_keys(items: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate Feedbrain source alias: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_keys)
    except json.JSONDecodeError as exc:
        raise ValueError("Feedbrain bindings must be valid JSON") from exc
    return validate_feedbrain_bindings(value)


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_json(method: str, url: str, timeout: float) -> tuple[int, Any]:
    """Small bounded transport: no HTTP proxy, redirects, or unbounded response reads."""
    request = Request(
        url,
        data=b"" if method == "POST" else None,
        method=method,
        headers={"Accept": "application/json"},
    )
    opener = build_opener(ProxyHandler({}), _NoRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(data) > MAX_HTTP_RESPONSE_BYTES:
                raise ToolExecutionError(
                    "invalid_response", "Feedbrain HTTP response is too large",
                    tool="feedbrain",
                )
            try:
                return response.status, json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ToolExecutionError(
                    "invalid_response", "Feedbrain returned invalid JSON", tool="feedbrain",
                ) from exc
    except HTTPError as exc:
        # Do not forward response bodies or untrusted redirects as new requests.
        raise ToolExecutionError(
            "http_error", f"Feedbrain returned HTTP {exc.code}", tool="feedbrain",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ToolExecutionError(
            "transport_error", "Feedbrain request could not be completed", tool="feedbrain",
        ) from exc


def _positive_id(value: Any, location: str) -> int:
    if type(value) is not int or value <= 0:
        raise ToolExecutionError(
            "invalid_response", f"Feedbrain returned invalid {location}", tool="feedbrain",
        )
    return value


class FeedbrainSyncAdapter:
    """Implement information.sync by waiting for a real asynchronous Feedbrain IngestionRun."""

    name = "feedbrain"
    capabilities = frozenset({"information.sync"})

    def __init__(
        self, *,
        base_url: str,
        source_bindings: Mapping[str, int],
        poll_interval: float = 1.0,
        max_wait_seconds: float = 120.0,
        request_timeout: float = 10.0,
        transport: Callable[[str, str, float], tuple[int, Any]] = _http_json,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        parts = urlsplit(base_url)
        if (
            parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password or parts.path not in ("", "/")
            or parts.query or parts.fragment
        ):
            raise ValueError("Feedbrain base URL must be a trusted HTTP(S) service root")
        if poll_interval <= 0 or max_wait_seconds <= 0 or request_timeout <= 0:
            raise ValueError("Feedbrain timeouts and polling interval must be positive")
        self.base_url = base_url.rstrip("/")
        self.source_bindings = validate_feedbrain_bindings(dict(source_bindings))
        self.poll_interval = poll_interval
        self.max_wait_seconds = max_wait_seconds
        self.request_timeout = request_timeout
        self.transport = transport
        self.monotonic = monotonic
        self.sleep = sleep

    def validate_parameters(self, capability: str, parameters: Mapping[str, Any]) -> None:
        if capability not in self.capabilities:
            raise ToolExecutionError(
                "capability_unavailable", "Feedbrain cannot provide this capability",
                tool=self.name,
            )
        if not isinstance(parameters, Mapping) or set(parameters) != {"source"}:
            raise ToolExecutionError(
                "invalid_parameters", "information.sync requires only with.source",
                tool=self.name,
            )
        alias = parameters["source"]
        if not isinstance(alias, str) or alias not in self.source_bindings:
            raise ToolExecutionError(
                "source_unbound", "No Feedbrain subscription is bound to that source",
                tool=self.name,
            )

    def execute(
        self, capability: str, parameters: Mapping[str, Any],
        on_external_ref: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        self.validate_parameters(capability, parameters)
        alias = parameters["source"]
        subscription_id = self.source_bindings[alias]
        deadline = self.monotonic() + self.max_wait_seconds
        status, queued = self.transport(
            "POST", f"{self.base_url}/subscriptions/{subscription_id}/sync",
            min(self.request_timeout, self.max_wait_seconds),
        )
        if status != 202 or not isinstance(queued, dict):
            raise ToolExecutionError(
                "invalid_response", "Feedbrain did not accept the sync operation",
                tool=self.name,
            )
        run_id = _positive_id(queued.get("id"), "IngestionRun ID")
        external_ref = f"feedbrain:ingestion_run:{run_id}"
        if queued.get("subscription_id") != subscription_id:
            raise ToolExecutionError(
                "invalid_response", "Feedbrain returned a mismatched subscription ID",
                tool=self.name, external_run_ref=external_ref,
            )
        if on_external_ref is not None:
            on_external_ref(external_ref)

        # Feedbrain can return an already-active IngestionRun. Do not claim it was
        # created by this Action; just report its observed final outcome.
        while True:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise ToolExecutionError(
                    "timeout", "Feedbrain sync did not finish before the deadline",
                    tool=self.name, external_run_ref=external_ref,
                )
            try:
                status, run = self.transport(
                    "GET", f"{self.base_url}/runs/{run_id}",
                    min(self.request_timeout, remaining),
                )
            except ToolExecutionError as exc:
                raise ToolExecutionError(
                    exc.code, str(exc), tool=self.name,
                    external_run_ref=external_ref,
                ) from exc
            if status != 200 or not isinstance(run, dict):
                raise ToolExecutionError(
                    "invalid_response", "Feedbrain run status could not be read",
                    tool=self.name, external_run_ref=external_ref,
                )
            if run.get("id") != run_id or run.get("subscription_id") != subscription_id:
                raise ToolExecutionError(
                    "invalid_response", "Feedbrain returned an unrelated run",
                    tool=self.name, external_run_ref=external_ref,
                )
            run_status = run.get("status")
            if run_status == "completed":
                counts = {}
                for key in ("items_seen", "items_created", "items_updated"):
                    value = run.get(key)
                    if type(value) is not int or value < 0:
                        raise ToolExecutionError(
                            "invalid_response", f"Feedbrain returned invalid {key}",
                            tool=self.name, external_run_ref=external_ref,
                        )
                    counts[key] = value
                return {
                    "status": "completed",
                    "external_run_ref": external_ref,
                    "subscription_id": subscription_id,
                    "source": alias,
                    "counts": counts,
                }
            if run_status == "failed":
                # Do not forward arbitrary private/untrusted error bodies.
                raise ToolExecutionError(
                    "external_run_failed", "Feedbrain ingestion run failed",
                    tool=self.name, external_run_ref=external_ref,
                )
            if run_status not in ("queued", "running"):
                raise ToolExecutionError(
                    "invalid_response", "Feedbrain returned an unknown run status",
                    tool=self.name, external_run_ref=external_ref,
                )
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                continue
            self.sleep(min(self.poll_interval, remaining))
