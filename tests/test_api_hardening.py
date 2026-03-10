import importlib
import tempfile

from fastapi.testclient import TestClient

from pythia_live.database import PythiaDB


def test_api_rate_limit_and_metrics(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        db_path = f"{td}/api.db"
        PythiaDB(db_path)

        monkeypatch.setenv("PYTHIA_DB_PATH", db_path)
        monkeypatch.setenv("PYTHIA_ALLOW_UNAUTHENTICATED", "true")
        monkeypatch.setenv("PYTHIA_RATE_LIMIT_REQUESTS", "2")
        monkeypatch.setenv("PYTHIA_RATE_LIMIT_WINDOW_SECONDS", "60")
        monkeypatch.setenv("PYTHIA_LATENCY_SAMPLE_SIZE", "20")

        import pythia_live.api as api_module

        api_module = importlib.reload(api_module)
        client = TestClient(api_module.app)

        first = client.get("/api/v1/health")
        assert first.status_code == 200
        assert "X-Process-Time-Ms" in first.headers

        second = client.get("/api/v1/metrics")
        assert second.status_code == 200
        body = second.json()
        assert body["rate_limit_requests"] == 2
        assert body["api_latency_p50_ms"] is not None

        third = client.get("/api/v1/health")
        assert third.status_code == 429
        assert third.headers["Retry-After"] == "60"
