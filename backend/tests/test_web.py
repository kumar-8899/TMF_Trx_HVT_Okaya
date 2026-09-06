"""Web shell: health, readiness, RFC-7807, request-id (CORE.md §5)."""

from fastapi.testclient import TestClient

from core.app import create_app


def _client(config_dir):
    app = create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)
    return TestClient(app, raise_server_exceptions=False)


def test_healthz_green(config_dir):
    with _client(config_dir) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_readyz_ready_when_core_up(config_dir):
    with _client(config_dir) as client:
        resp = client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True
        assert body["checks"]["db"] is True


def test_unknown_route_is_rfc7807(config_dir):
    with _client(config_dir) as client:
        resp = client.get("/does-not-exist")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["status"] == 404
        assert body["instance"] == "/does-not-exist"
        assert body["request_id"]


def test_request_id_echoed(config_dir):
    with _client(config_dir) as client:
        resp = client.get("/healthz", headers={"X-Request-ID": "abc123"})
        assert resp.headers["X-Request-ID"] == "abc123"


def test_modules_status_reports_gate(config_dir):
    # A registered + licensed module loads through the gate (bridge disabled here,
    # but activation does not need a live link).
    with _client(config_dir) as client:
        resp = client.get("/modules/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "modules" in body and "loaded" in body and "skipped" in body
        assert "variables" in body["loaded"]
