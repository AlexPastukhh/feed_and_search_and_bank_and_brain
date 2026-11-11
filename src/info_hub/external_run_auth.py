"""Executor-bound registration credentials; deliberately disabled by default."""
import hmac
import json
import re

from fastapi import HTTPException, Request

from info_hub.settings import get_settings


def authenticated_external_executor(request: Request, action_id: int) -> str:
    """Resolve executor ID from configured server-side credential, not the body.

    This protects only external-run registration. Other prototype API routes
    remain unauthenticated and must not be exposed to untrusted networks.
    """
    raw = get_settings().action_external_run_tokens.get_secret_value()
    try:
        if not raw or len(raw) > 8192:
            raise ValueError("disabled")
        credentials = json.loads(raw)
        if not isinstance(credentials, dict) or not 1 <= len(credentials) <= 32:
            raise ValueError("invalid map")
        valid = all(
            isinstance(who, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}", who)
            and isinstance(config, dict) and set(config) == {"token", "action_ids"}
            and isinstance(config["token"], str)
            and 32 <= len(config["token"]) <= 256
            and config["token"].isascii()
            and not any(ch.isspace() for ch in config["token"])
            and isinstance(config["action_ids"], list)
            and 1 <= len(config["action_ids"]) <= 100
            and all(type(action) is int and action > 0 for action in config["action_ids"])
            and len(set(config["action_ids"])) == len(config["action_ids"])
            for who, config in credentials.items()
        )
        if not valid or len({v["token"] for v in credentials.values()}) != len(credentials):
            raise ValueError("invalid credentials")
    except (ValueError, TypeError):
        # Do not print the invalid config or secrets.
        raise HTTPException(
            status_code=503, detail="External run registration is not configured",
        ) from None

    header = request.headers.get("authorization", "")
    scheme, delimiter, submitted = header.partition(" ")
    if scheme.lower() != "bearer" or delimiter != " " or not submitted:
        raise HTTPException(
            status_code=401, detail="Executor credential required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if len(submitted) > 256 or not submitted.isascii() or any(ch.isspace() for ch in submitted):
        raise HTTPException(status_code=403, detail="Executor credential denied")
    matches = [
        executor for executor, config in credentials.items()
        if hmac.compare_digest(submitted, config["token"])
    ]
    if len(matches) != 1 or action_id not in credentials[matches[0]]["action_ids"]:
        raise HTTPException(status_code=403, detail="Executor credential denied")
    return matches[0]
