"""Native TLS-only entrypoint for Action Core's narrow Gateway READ app.

This module never starts a plaintext server, reverse proxy or redirect.
The owner-provisioned certificate and key must be mounted read-only.
"""
import os
import re
import ssl
import stat
from pathlib import Path

import uvicorn

from info_hub.settings import get_settings

_TLS_DIR = Path("/run/action-core-gateway-tls")
CERT_PATH = _TLS_DIR / "tls.crt"
KEY_PATH = _TLS_DIR / "tls.key"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _validate_tls_file(path: Path, *, private: bool) -> None:
    """Reject absent, linked or writable files before starting the listener."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        entry = os.fstat(fd)
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise RuntimeError("GATEWAY_TLS_FILE_INVALID")
        if not 128 <= entry.st_size <= 65536:
            raise RuntimeError("GATEWAY_TLS_FILE_SIZE_INVALID")
        mode = stat.S_IMODE(entry.st_mode)
        if mode & 0o022 or (private and mode & 0o077):
            raise RuntimeError("GATEWAY_TLS_FILE_PERMISSIONS_INVALID")
    finally:
        os.close(fd)


def verify_startup() -> None:
    """Fail closed before TCP admission unless the HTTPS prerequisites exist."""
    digest = get_settings().action_gateway_read_token_sha256.get_secret_value()
    if not _DIGEST.fullmatch(digest):
        raise RuntimeError("GATEWAY_READ_VERIFIER_NOT_CONFIGURED")
    if _TLS_DIR.is_symlink() or _TLS_DIR.parent.is_symlink():
        raise RuntimeError("GATEWAY_TLS_MOUNT_INVALID")
    _validate_tls_file(CERT_PATH, private=False)
    _validate_tls_file(KEY_PATH, private=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(CERT_PATH), keyfile=str(KEY_PATH))


def main() -> None:
    verify_startup()
    uvicorn.run(
        "info_hub.gateway_read_main:app",
        host="0.0.0.0",
        port=443,
        ssl_certfile=str(CERT_PATH),
        ssl_keyfile=str(KEY_PATH),
        ssl_version=ssl.PROTOCOL_TLS_SERVER,
        proxy_headers=False,
        server_header=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
