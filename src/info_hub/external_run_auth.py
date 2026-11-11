"""Authorize post-hoc External AI Run registration without executor identity.

Bearer tokens are scoped Action grants, never actor identifiers in the
request, audit record, response or idempotency fingerprint.
"""
import hmac
import json

from fastapi import HTTPException, Request

from info_hub.settings import get_settings


def authorize_external_run(request: Request, action_id: int) -> None:
    """Require a valid server-side token allowed for exactly this Action.

    No executor ID is accepted or returned. Only the access grant is checked.
    The rest of the local prototype API remains unauthenticated; do not expose
    it to untrusted networks.
    """
    raw = get_settings().action_external_run_tokens.get_secret_value()
    try:
        if not raw or len(raw) > 8192:
            raise ValueError("disabled")
        grants = json.loads(raw)
        if not isinstance(grants, list) or not 1 <= len(grants) <= 32:
            raise ValueError("invalid grants")
        valid = all(
            isinstance(grant, dict) and set(grant) == {"token", "action_ids"}
            and isinstance(grant["token"], str)
            and 32 <= len(grant["token"]) <= 256
            and grant["token"].isascii()
            and not any(ch.isspace() for ch in grant["token"])
            and isinstance(grant["action_ids"], list)
            and 1 <= len(grant["action_ids"]) <= 100
            and all(type(action) is int and action > 0 for action in grant["action_ids"])
            and len(set(grant["action_ids"])) == len(grant["action_ids"])
            for grant in grants
        )
        if not valid or len({grant["token"] for grant in grants}) != len(grants):
            raise ValueError("invalid grants")
    except (ValueError, TypeError):
        # Never print invalid configuration, tokens or external inputs.
        raise HTTPException(
            status_code=503, detail="External run registration is not configured",
        ) from None

    header = request.headers.get("authorization", "")
    scheme, delimiter, submitted = header.partition(" ")
    if scheme.lower() != "bearer" or delimiter != " " or not submitted:
        raise HTTPException(
            status_code=401, detail="Registration credential required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if (len(submitted) > 256 or not submitted.isascii()
            or any(ch.isspace() for ch in submitted)):
        raise HTTPException(status_code=403, detail="Registration credential denied")
    matches = [
        grant for grant in grants
        if hmac.compare_digest(submitted, grant["token"])
    ]
    if len(matches) != 1 or action_id not in matches[0]["action_ids"]:
        raise HTTPException(status_code=403, detail="Registration credential denied")
