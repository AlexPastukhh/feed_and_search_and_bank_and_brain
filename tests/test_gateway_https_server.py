"""Source-only validation for the dedicated native TLS/443 Action Core listener."""
import hashlib
import os
import shutil
import ssl
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from info_hub import gateway_https_server as service

TOKEN = "t" * 48
DIGEST = hashlib.sha256(TOKEN.encode("ascii")).hexdigest()


@pytest.fixture
def tls_files(tmp_path, monkeypatch):
    directory = tmp_path / "tls"
    directory.mkdir(mode=0o700)
    cert = directory / "tls.crt"
    key = directory / "tls.key"
    monkeypatch.setattr(service, "_TLS_DIR", directory)
    monkeypatch.setattr(service, "CERT_PATH", cert)
    monkeypatch.setattr(service, "KEY_PATH", key)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(action_gateway_read_token_sha256=SecretStr(DIGEST)),
    )
    return cert, key


def test_https_startup_rejects_absent_verifier(tls_files, monkeypatch):
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(action_gateway_read_token_sha256=SecretStr("")),
    )
    with pytest.raises(RuntimeError, match="GATEWAY_READ_VERIFIER_NOT_CONFIGURED"):
        service.verify_startup()


def test_https_startup_rejects_absent_or_unsafe_tls_files(tls_files):
    cert, key = tls_files
    with pytest.raises(FileNotFoundError):
        service.verify_startup()

    cert.write_bytes(b"C" * 256)
    key.write_bytes(b"K" * 256)
    os.chmod(cert, 0o644)
    os.chmod(key, 0o666)
    with pytest.raises(RuntimeError, match="GATEWAY_TLS_FILE_PERMISSIONS_INVALID"):
        service.verify_startup()

    os.chmod(key, 0o600)
    cert.unlink()
    cert.symlink_to(key)
    with pytest.raises(OSError):
        service.verify_startup()


def test_https_startup_rejects_invalid_certificate_pair(tls_files):
    cert, key = tls_files
    cert.write_bytes(b"C" * 256)
    key.write_bytes(b"K" * 256)
    os.chmod(cert, 0o644)
    os.chmod(key, 0o600)
    with pytest.raises(ssl.SSLError):
        service.verify_startup()


def test_native_https_startup_invokes_no_http_or_proxy(tls_files, monkeypatch):
    if not shutil.which("openssl"):
        pytest.skip("openssl required for fixture certificate")
    cert, key = tls_files
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "1", "-sha256",
            "-subj", "/CN=action-core-gw",
            "-addext", "subjectAltName=DNS:action-core-gw",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True, timeout=20, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.chmod(cert, 0o644)
    os.chmod(key, 0o600)
    service.verify_startup()

    calls = []
    monkeypatch.setattr(service.uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    service.main()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("info_hub.gateway_read_main:app",)
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 443
    assert kwargs["ssl_certfile"] == str(cert)
    assert kwargs["ssl_keyfile"] == str(key)
    assert kwargs["ssl_version"] == ssl.PROTOCOL_TLS_SERVER
    assert kwargs["proxy_headers"] is False
    assert kwargs["server_header"] is False
    assert kwargs["access_log"] is False
    assert "http" not in kwargs
