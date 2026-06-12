"""report standalone tester (CORE.md §6.2). RP1: assembly + sqlite sink + queries."""

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

import modules.report  # noqa: F401 — registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from core.services.auth_verify import AuthError, Principal, TokenVerifier
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.report.variants.standard import StandardReport


@pytest.fixture
async def ctx():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, auth=TokenVerifier(),
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
    )
    mod = StandardReport.construct(core, {})
    yield mod, core, db
    await db.close()


async def _seed_run(db, run_id, result, recipe="inv-c"):
    await db.repo.put("run_event", {"type": "run-started", "ts": 1.0, "run_id": run_id,
                                    "recipe": recipe, "version": 3})
    await db.repo.put("run_event", {"type": "step-completed", "ts": 2.0, "run_id": run_id,
                                    "step_id": "s1", "status": "PASSED",
                                    "measurements": [{"name": "vbus", "value": 264.0, "units": "V"}]})
    await db.repo.put("run_event", {"type": "run-finished", "ts": 3.0, "run_id": run_id, "result": result})


async def _finish(mod, run_id, result):
    await mod._on_event("tmf/st1/event/run-finished",
                        {"type": "run-finished", "ts": 3.0, "payload": {"run_id": run_id, "result": result}})


def test_registered():
    rec = default_registry.get("report")
    assert rec.variant_ids == ["standard"]
    m = ManifestLoader().load("report")
    assert m.entitlement_key == "report" and m.contributes.api_prefix == "/reports"


async def test_assembles_and_stores_report(ctx):
    mod, _, db = ctx
    await _seed_run(db, "R1", "PASS")
    await _finish(mod, "R1", "PASS")

    rep = await mod.get_report("R1")
    assert rep["result"] == "PASS"
    assert rep["recipe_id"] == "inv-c" and rep["recipe_version"] == 3
    assert len(rep["steps"]) == 1 and rep["steps"][0]["step_id"] == "s1"
    assert rep["measurements"][0]["value"] == 264.0
    assert rep["started_ts"] == 1.0 and rep["finished_ts"] == 3.0


async def test_list_filters(ctx):
    mod, _, db = ctx
    await _seed_run(db, "R1", "PASS", recipe="inv-c")
    await _finish(mod, "R1", "PASS")
    await _seed_run(db, "R2", "FAIL", recipe="other")
    await _finish(mod, "R2", "FAIL")

    assert (await mod.list_reports())["total"] == 2
    assert [r["run_id"] for r in (await mod.list_reports(result="FAIL"))["items"]] == ["R2"]
    assert [r["run_id"] for r in (await mod.list_reports(recipe_id="inv-c"))["items"]] == ["R1"]


# --- REST ------------------------------------------------------------------


def _client(mod, core):
    core.auth.register(lambda t: Principal("v", role="viewer", permissions=frozenset({"REPORT.VIEW"}))
                       if t == "viewer" else _raise())
    app = FastAPI()
    app.state.auth = core.auth
    app.include_router(mod.router, prefix="/reports")
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _raise():
    raise AuthError("bad token")


async def test_rest(ctx):
    mod, core, db = ctx
    await _seed_run(db, "R1", "PASS")
    await _finish(mod, "R1", "PASS")
    async with _client(mod, core) as c:
        v = {"Authorization": "Bearer viewer"}
        assert (await c.get("/reports")).status_code == 401          # no token
        got = await c.get("/reports/R1", headers=v)
        assert got.status_code == 200 and got.json()["result"] == "PASS"
        assert (await c.get("/reports/none", headers=v)).status_code == 404
        lst = await c.get("/reports", headers=v)
        assert lst.status_code == 200 and lst.json()["total"] == 1
