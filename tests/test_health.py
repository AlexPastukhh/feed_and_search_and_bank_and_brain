"""FastAPI health contract tests (run with dev dependencies)."""
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from info_hub.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok(monkeypatch) -> None:
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            assert str(statement) == "SELECT 1"

    class Engine:
        def connect(self):
            return Connection()

    monkeypatch.setattr("info_hub.health.get_engine", lambda: Engine())
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_unavailable(monkeypatch) -> None:
    def failing_engine():
        raise OperationalError("connect", {}, Exception("offline"))

    monkeypatch.setattr("info_hub.health.get_engine", failing_engine)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
