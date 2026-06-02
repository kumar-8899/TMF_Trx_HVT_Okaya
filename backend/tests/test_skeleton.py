"""P1 smoke: the web shell boots and /healthz is green (CORE.md §10 #1, #4 half)."""

from fastapi.testclient import TestClient

from core.app import create_app


def test_healthz_green():
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
