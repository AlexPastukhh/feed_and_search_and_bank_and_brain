"""Fail-closed authorization for the narrow Action Core Gateway READ surface."""
import hashlib
import hmac
import re

from fastapi import HTTPException, Request

from info_hub.settings import get_settings

ALLOWED_ACTION_IDS = frozenset({3, 4})
EXPECTED_HOSTS = frozenset({"action-core-gw", "action-core-gw:443"})
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_MIN_TOKEN_LENGTH = 32
_MAX_TOKEN_LENGTH = 256


async def authorize_gateway_read(request: Request, action_id: int) -> None:
    """Require the dedicated bearer and reject all caller-controlled routing."""
    if action_id not in ALLOWED_ACTION_IDS:
        raise HTTPException(status_code=403, detail="Action is not permitted")

    expected_path = f"/gateway/v1/actions/{action_id}"
    if request.scope.get("raw_path") != expected_path.encode("ascii"):
        raise HTTPException(status_code=404, detail="Gateway route not found")
    if request.scope.get("query_string"):
        raise HTTPException(status_code=400, detail="Query parameters are not supported")

    host_values = [
        value for name, value in request.scope.get("headers", [])
        if name.lower() == b"host"
    ]
    if len(host_values) != 1:
        raise HTTPException(status_code=421, detail="Invalid Host")
    try:
        host = host_values[0].decode("ascii").lower()
    except UnicodeDecodeError:
        raise HTTPException(status_code=421, detail="Invalid Host") from None
    if host not in EXPECTED_HOSTS:
        raise HTTPException(status_code=421, detail="Invalid Host")

    # GET has no body in this contract. Stop on the first non-empty ASGI chunk.
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(status_code=400, detail="GET body is not supported")

    digest = get_settings().action_gateway_read_token_sha256.get_secret_value()
    if _SHA256_HEX.fullmatch(digest) is None:
        raise HTTPException(status_code=503, detail="Gateway READ is not configured")
    auth_values = [
        value for name, value in request.scope.get("headers", [])
        if name.lower() == b"authorization"
    ]
    if not auth_values:
        raise HTTPException(
            status_code=401,
            detail="Gateway READ credential required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if len(auth_values) != 1:
        raise HTTPException(status_code=400, detail="Invalid Authorization header")
    try:
        authorization = auth_values[0].decode("ascii")
    except UnicodeDecodeError:
        raise HTTPException(status_code=403, detail="Gateway READ credential denied") from None

    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or separator != " " or not token:
        raise HTTPException(
            status_code=401,
            detail="Gateway READ credential required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if (
        not _MIN_TOKEN_LENGTH <= len(token) <= _MAX_TOKEN_LENGTH
        or not token.isascii()
        or any(character.isspace() for character in token)
    ):
        raise HTTPException(status_code=403, detail="Gateway READ credential denied")
    submitted_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    if not hmac.compare_digest(submitted_digest, digest):
        raise HTTPException(status_code=403, detail="Gateway READ credential denied")
