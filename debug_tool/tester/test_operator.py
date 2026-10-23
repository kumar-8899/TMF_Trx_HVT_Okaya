"""The operator's page and the endpoints behind it: served only to the PC itself, key-protected, and each action works."""

import asyncio
import sys
import zipfile

import httpx
import pytest

from debug_tool.tester.test_mcp import running


@pytest.mark.asyncio
async def test_the_page_carries_the_operator_key_and_never_the_mcp_token(tmp_path):
    async with running(tmp_path) as rig:
        tok = (await rig.share())["token"]
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{rig.base}/")
            assert r.status_code == 200 and rig.rt.operator_key in r.text and tok not in r.text
            assert "__OPERATOR_KEY__" not in r.text and r.headers["cache-control"] == "no-store"
            assert "textContent" in r.text and ".innerHTML" not in r.text            # bench text is never injected as markup


@pytest.mark.asyncio
async def test_operator_endpoints_all_need_the_key(tmp_path):
    async with running(tmp_path) as rig:
        async with httpx.AsyncClient() as c:
            for method, path in (("GET", "/operator/status"), ("GET", "/operator/live"), ("GET", "/operator/scripts"), ("GET", "/operator/python"),
                                 ("POST", "/operator/collect"), ("POST", "/operator/scripts/run"), ("POST", "/operator/analyze"),
                                 ("POST", "/operator/python/extract"), ("POST", "/operator/analyze-upload"), ("GET", "/operator/access")):
                r = await c.request(method, rig.base + path, json={})
                assert r.status_code == 401, path


@pytest.mark.asyncio
async def test_collect_analyze_round_trip_from_the_page(tmp_path, monkeypatch):
    from debug_server import sysinfo
    monkeypatch.setattr(sysinfo, "processes", lambda: {"processes": []})
    monkeypatch.setattr(sysinfo, "app_health", lambda port=None: {"app_running": False, "note": "n"})
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")              # the 'Desktop' of this test
    (tmp_path / "home" / "Desktop").mkdir(parents=True)
    async with running(tmp_path) as rig:
        async with httpx.AsyncClient(timeout=60) as c:
            col = await c.post(f"{rig.base}/operator/collect", json={"rows": 100, "integrity": False}, headers=rig.op)
            assert col.status_code == 200, col.text
            res = col.json()
            assert res["path"].startswith(str(tmp_path / "home" / "Desktop")) and "download_url" not in res    # local: not served remotely
            assert zipfile.is_zipfile(res["path"])
            an = await c.post(f"{rig.base}/operator/analyze", json={"path": f'"{res["path"]}"'}, headers=rig.op)       # quotes pasted from Explorer
            assert an.status_code == 200 and "look_here_first" in an.json() and an.json()["markdown"].startswith("#")
            up = await c.post(f"{rig.base}/operator/analyze-upload?name=my bundle", content=open(res["path"], "rb").read(), headers=rig.op)
            assert up.status_code == 200 and "uploads" not in up.json()["paths"]["folder"]
            assert (await c.post(f"{rig.base}/operator/analyze", json={"path": str(tmp_path / "nope.zip")}, headers=rig.op)).status_code == 400
            assert (await c.post(f"{rig.base}/operator/analyze-upload", content=b"", headers=rig.op)).status_code == 400
            assert (await c.post(f"{rig.base}/operator/analyze-upload", content=b"not a zip", headers=rig.op)).status_code == 400
        assert any(e.get("event") == "operator_collect" for e in rig.rt.log.tail(50))


@pytest.mark.asyncio
async def test_collect_without_an_install_says_so(tmp_path):
    from debug_tool.appinfo import AppInfo
    from debug_tool.tester.test_mcp import build_app, create_runtime, EngineConfig
    rt = create_runtime(EngineConfig(app=AppInfo(None, None, "not found"), data_dir=tmp_path / "t"))
    app = build_app(rt, port=1, manage_engine=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5)), base_url="http://127.0.0.1") as c:
        r = await c.post("/operator/collect", json={}, headers={"X-Operator-Key": rt.operator_key})
        assert r.status_code == 409 and "no app install" in r.json()["detail"]


@pytest.mark.asyncio
async def test_operator_scripts_run_without_a_card_and_respect_the_run_rule(tmp_path):
    async with running(tmp_path) as rig:
        rig.rt.engine.scripts._python = lambda: {"kind": "system", "path": sys.executable, "version": "x", "notes": []}
        async with httpx.AsyncClient(timeout=60) as c:
            ok = await c.post(f"{rig.base}/operator/scripts/run", json={"interpreter": "python", "script": "print('mine')"}, headers=rig.op)
            assert ok.status_code == 200 and ok.json()["stdout"].strip() == "mine" and ok.json()["approved_by"]
            assert len((await c.get(f"{rig.base}/operator/scripts", headers=rig.op)).json()["history"]) == 1
            rig.rt.engine.ingestor._active = True
            blocked = await c.post(f"{rig.base}/operator/scripts/run", json={"interpreter": "python", "script": "print(1)"}, headers=rig.op)
            assert blocked.status_code == 409 and "test run is in progress" in blocked.json()["detail"]
            forced = await c.post(f"{rig.base}/operator/scripts/run", json={"interpreter": "python", "script": "print(2)", "allow_during_run": True}, headers=rig.op)
            assert forced.status_code == 200
            rig.rt.engine.ingestor._active = False
            assert (await c.post(f"{rig.base}/operator/scripts/run", json={"interpreter": "bash", "script": "x"}, headers=rig.op)).status_code == 400
        assert [e["event"] for e in rig.rt.log.tail(50) if e.get("event") == "operator_script"] == ["operator_script", "operator_script"]


@pytest.mark.asyncio
async def test_python_page_endpoints(tmp_path):
    async with running(tmp_path) as rig:
        async with httpx.AsyncClient(timeout=60) as c:
            st = (await c.get(f"{rig.base}/operator/python", headers=rig.op)).json()
            assert {"extracted", "can_extract", "will_use", "wheelhouses"} <= set(st)
            rig.rt.engine.pyenv._which = lambda n: None
            rig.rt.engine.pyenv.tool_dir = None
            r = await c.post(f"{rig.base}/operator/python/extract", headers=rig.op)
            assert r.status_code == 409 and "no usable Python" in r.json()["detail"]
