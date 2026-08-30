"""Single-origin SPA serving (core/services/spa.py).

The edge serves the built bundle, but the API and the SPA share a path namespace
(`GET /runs` is both the runs API and a client route). Serving must mirror the dev
Vite `serveSpa` bypass: a `text/html` navigation gets the shell, an API client keeps
the JSON route. These tests pin exactly that, with no broker and no full app boot.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.services.spa import install_spa, resolve_frontend_dist

HTML = {"accept": "text/html,application/xhtml+xml"}
JSON = {"accept": "application/json"}


def _bundle(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root>SHELL</div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return dist


def _app(dist: Path) -> TestClient:
    app = FastAPI()

    @app.get("/runs")
    async def runs():  # a real API route sharing the /runs path with the SPA
        return {"runs": []}

    install_spa(app, dist)
    return TestClient(app)


def test_root_navigation_serves_shell(tmp_path):
    client = _app(_bundle(tmp_path))
    resp = client.get("/", headers=HTML)
    assert resp.status_code == 200
    assert "SHELL" in resp.text


def test_client_route_navigation_serves_shell(tmp_path):
    # A hard refresh / deep-link on a client route the backend has no route for.
    client = _app(_bundle(tmp_path))
    resp = client.get("/recipes/abc/edit", headers=HTML)
    assert resp.status_code == 200
    assert "SHELL" in resp.text


def test_shared_path_html_gets_shell_json_gets_api(tmp_path):
    # /runs is BOTH an API route and a client route — the Accept header decides.
    client = _app(_bundle(tmp_path))
    nav = client.get("/runs", headers=HTML)
    assert nav.status_code == 200 and "SHELL" in nav.text
    api = client.get("/runs", headers=JSON)
    assert api.status_code == 200 and api.json() == {"runs": []}


def test_real_asset_is_served(tmp_path):
    client = _app(_bundle(tmp_path))
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text
    resp2 = client.get("/favicon.svg")
    assert resp2.status_code == 200 and "svg" in resp2.text


def test_unknown_api_path_not_shadowed_for_json_clients(tmp_path):
    # An API client hitting a wrong path must still 404, not receive the HTML shell.
    client = _app(_bundle(tmp_path))
    resp = client.get("/nope/not/a/route", headers=JSON)
    assert resp.status_code == 404


def test_resolve_returns_none_when_no_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("TMF_FRONTEND_DIR", str(tmp_path / "absent"))
    # The env candidate is absent; the source/frozen candidates won't exist under a
    # temp CWD either — but if a repo build is present this still must not raise.
    result = resolve_frontend_dist()
    assert result is None or (result / "index.html").is_file()


def test_resolve_finds_env_bundle(tmp_path, monkeypatch):
    dist = _bundle(tmp_path)
    monkeypatch.setenv("TMF_FRONTEND_DIR", str(dist))
    assert resolve_frontend_dist() == dist.resolve()
