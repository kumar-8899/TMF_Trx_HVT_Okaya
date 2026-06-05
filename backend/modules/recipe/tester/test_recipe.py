"""recipe standalone tester (CORE.md §6.2). R1: step-type registry + schemas."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

import modules.recipe  # noqa: F401 — registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from core.services.auth_verify import AuthError, Principal, TokenVerifier
from core.services.bridge import BridgeClient
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.recipe.runtime_params import substitute
from modules.recipe.storage import RecipeValidationError
from modules.recipe.variants.filesystem import FilesystemRecipe
from tests._mqtt import Broker, find_mosquitto

EXPECTED_TYPES = {
    "set_output", "measure", "compare", "measure_and_compare", "ramp_until",
    "wait", "wait_until", "prompt_operator", "log_message", "abort_if",
    "repeat", "sweep", "if_then_else", "group", "test_reference",
}


@pytest.fixture
async def mod():
    core = CoreServices(station="st1")
    m = FilesystemRecipe.construct(core, {"root": "data/recipes"})
    await m.init()
    return m


def test_module_registered():
    rec = default_registry.get("recipe")
    assert rec.variant_ids == ["filesystem"]


def test_manifest_valid():
    m = ManifestLoader().load("recipe")
    assert m.entitlement_key == "recipe"
    assert m.contributes.api_prefix == "/recipes"


async def test_fifteen_step_types(mod):
    types = {t["type_id"] for t in mod.list_step_types()}
    assert types == EXPECTED_TYPES
    assert len(types) == 15
    composites = {t["type_id"] for t in mod.list_step_types() if t["composite"]}
    assert composites == {"repeat", "sweep", "if_then_else", "group"}


async def test_get_step_schema(mod):
    schema = mod.get_step_schema("measure_and_compare")
    assert schema["$id"] == "tmf:recipe:step_types/measure_and_compare/params"
    assert "limits" in schema["properties"]


async def test_schema_validation_with_refs(mod):
    # a valid measure_and_compare step (limits $ref resolves to _common)
    good = {
        "step_id": "vbus_check", "step_type": "measure_and_compare",
        "params": {"variable": "vbus_main", "limits": {"min": 250.0, "max": 278.0}},
    }
    assert mod._schemas.validate_step(good) == []

    bad_params = {"step_id": "x", "step_type": "measure_and_compare", "params": {"variable": "v"}}
    assert mod._schemas.validate_step(bad_params)  # missing limits

    bad_envelope = {"step_id": "BAD ID", "step_type": "wait", "params": {"duration_ms": 1}}
    assert mod._schemas.validate_step(bad_envelope)  # step_id pattern

    unknown = {"step_id": "x", "step_type": "nope", "params": {}}
    assert any("unknown step_type" in e for e in mod._schemas.validate_step(unknown))


async def test_composite_inner_steps_validate(mod):
    # repeat's inner_steps $ref the envelope — one level resolves
    repeat = {
        "step_id": "cycle", "step_type": "repeat",
        "params": {"iterations": 5, "inner_steps": [
            {"step_id": "settle", "step_type": "wait", "params": {"duration_ms": 100}}
        ]},
    }
    assert mod._schemas.validate_step(repeat) == []


# --- REST ------------------------------------------------------------------


_TOKENS = {
    "viewer": Principal("v", role="operator", permissions=frozenset({"RECIPE.VIEW"})),
    "editor": Principal("e", role="engineer", permissions=frozenset({"RECIPE.VIEW", "RECIPE.EDIT"})),
    "noperm": Principal("n", role="operator", permissions=frozenset({"TEST.RUN"})),
}


async def _client(mod):
    app = FastAPI()
    tv = TokenVerifier()
    tv.register(lambda t: _TOKENS[t] if t in _TOKENS else _raise())
    app.state.auth = tv
    app.include_router(mod.router, prefix="/recipes")
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _raise():
    raise AuthError("bad token")


async def test_rest_step_types(mod):
    async with await _client(mod) as c:
        v = {"Authorization": "Bearer viewer"}
        assert (await c.get("/recipes/step-types")).status_code == 401          # no token
        r = await c.get("/recipes/step-types", headers=v)
        assert r.status_code == 200 and len(r.json()) == 15
        s = await c.get("/recipes/step-types/measure/schema", headers=v)
        assert s.status_code == 200 and s.json()["$id"].endswith("measure/params")
        assert (await c.get("/recipes/step-types/ghost/schema", headers=v)).status_code == 404
        assert (await c.get("/recipes/step-types", headers={"Authorization": "Bearer noperm"})).status_code == 403


# --- R2: authoring + versioning --------------------------------------------


PAYLOAD = {
    "schema_version": 1, "recipe_id": "inv-c", "name": "Inverter Board Rev C",
    "owner": "alice@acme.test", "tags": ["production"], "barcode_prefixes": ["INV-C-"],
    "steps": [{"step_id": "settle", "step_type": "wait", "params": {"duration_ms": 100}}],
}


@pytest.fixture
async def fsmod(tmp_path):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
    )
    m = FilesystemRecipe.construct(core, {"root": str(tmp_path / "recipes")})
    await m.init()
    yield m, db
    await db.close()


async def test_create_save_publish(fsmod):
    mod, db = fsmod
    created = await mod.create_recipe(PAYLOAD)
    did = created["draft_id"]
    assert mod.store.read_meta("inv-c")["status"] == "draft"

    await mod.save_draft("inv-c", did, {**PAYLOAD, "name": "Inv C edited"})
    pub = await mod.publish_draft("inv-c", did)
    assert pub["version"] == 1 and pub["status"] == "active"
    assert pub["content_hash"].startswith("sha256:")

    # version on disk + corpus record in db
    got = await mod.get_recipe("inv-c")
    assert got["version"] == 1 and got["name"] == "Inv C edited"
    rec = await db.repo.get("recipe.version", "inv-c:v1")
    assert rec is not None and rec["data"]["content_hash"] == pub["content_hash"]


async def test_create_duplicate_and_validation(fsmod):
    mod, _ = fsmod
    await mod.create_recipe(PAYLOAD)
    from modules.recipe.storage import RecipeExistsError
    with pytest.raises(RecipeExistsError):
        await mod.create_recipe(PAYLOAD)

    # publish an invalid recipe (wait step missing duration_ms) -> RecipeValidationError
    bad = await mod.create_recipe({**PAYLOAD, "recipe_id": "bad",
                                   "steps": [{"step_id": "w", "step_type": "wait", "params": {}}]})
    with pytest.raises(RecipeValidationError):
        await mod.publish_draft("bad", bad["draft_id"])


async def test_second_version_via_fork(fsmod):
    mod, _ = fsmod
    c1 = await mod.create_recipe(PAYLOAD)
    await mod.publish_draft("inv-c", c1["draft_id"])
    fork = await mod.fork_draft("inv-c")
    assert fork["recipe"]["version"] == 1  # forked from v1
    await mod.save_draft("inv-c", fork["draft_id"], {**fork["recipe"], "name": "v2"})
    v2 = await mod.publish_draft("inv-c", fork["draft_id"])
    assert v2["version"] == 2
    versions = await mod.list_versions("inv-c")
    assert [v["version"] for v in versions] == [1, 2]


async def test_discovery_barcode_lifecycle(fsmod):
    mod, _ = fsmod
    c1 = await mod.create_recipe(PAYLOAD)
    await mod.publish_draft("inv-c", c1["draft_id"])

    assert [r["recipe_id"] for r in await mod.list_recipes(status="active")] == ["inv-c"]
    assert (await mod.get_by_barcode("INV-C-12345"))["recipe_id"] == "inv-c"

    await mod.archive("inv-c", 1)
    assert (await mod.list_versions("inv-c"))[0]["archived"] is True
    await mod.deprecate("inv-c", reason="superseded")
    assert mod.store.read_meta("inv-c")["status"] == "deprecated"


async def test_content_hash_matches_sidecar(fsmod):
    mod, _ = fsmod
    c1 = await mod.create_recipe(PAYLOAD)
    pub = await mod.publish_draft("inv-c", c1["draft_id"])
    sidecar = (mod.store.recipe_dir("inv-c") / "v1" / "recipe.json.sha256").read_text()
    assert sidecar == pub["content_hash"]


async def test_rest_authoring_gated(fsmod):
    mod, _ = fsmod
    async with await _client(mod) as c:
        editor = {"Authorization": "Bearer editor"}
        viewer = {"Authorization": "Bearer viewer"}

        # viewer cannot create
        assert (await c.post("/recipes", headers=viewer, json=PAYLOAD)).status_code == 403
        created = await c.post("/recipes", headers=editor, json=PAYLOAD)
        assert created.status_code == 201
        did = created.json()["draft_id"]

        pub = await c.post(f"/recipes/inv-c/drafts/{did}/publish", headers=editor)
        assert pub.status_code == 200 and pub.json()["version"] == 1

        # viewer can read
        got = await c.get("/recipes/inv-c", headers=viewer)
        assert got.status_code == 200 and got.json()["version"] == 1
        assert (await c.get("/recipes", headers=viewer)).json()[0]["recipe_id"] == "inv-c"


# --- R3: validation --------------------------------------------------------


def _measure_compare(measurement="v"):
    return [
        {"step_id": "m", "step_type": "measure", "params": {"variable": "vbus_main", "store_as": "v"}},
        {"step_id": "c", "step_type": "compare",
         "params": {"source": {"measurement": measurement}, "limits": {"min": 1, "max": 2}}},
    ]


def test_validate_semantic_measurement_ref():
    from modules.recipe.validation.semantic import check_semantic
    ok = {"steps": _measure_compare("v")}
    bad = {"steps": _measure_compare("missing")}
    assert check_semantic(ok) == []
    assert any("unknown measurement 'missing'" in e for e in check_semantic(bad))


def test_validate_semantic_sweep_and_ramp():
    from modules.recipe.validation.semantic import check_semantic
    sweep_bad = {"steps": [{"step_id": "s", "step_type": "sweep",
                            "params": {"variable": "x", "range": {"start": 320.0, "end": 200.0, "step": 20.0},
                                       "inner_steps": [{"step_id": "w", "step_type": "wait",
                                                        "params": {"duration_ms": 1}}]}}]}
    assert any("sweep range end < start" in e for e in check_semantic(sweep_bad))
    ramp_bad = {"steps": [{"step_id": "r", "step_type": "ramp_until",
                           "params": {"variable": "x", "start": 320.0, "end": 200.0, "step_size": 2.0,
                                      "dwell_ms": 10, "until": {"variable": "t", "op": "==", "value": True}}}]}
    assert any("ramp_until end < start" in e for e in check_semantic(ramp_bad))


async def test_validate_report_and_crossref_warning(fsmod):
    mod, _ = fsmod
    report = mod.validate({"recipe_id": "x", "steps": _measure_compare("v")})
    assert report["ok"] is True
    assert any("cross-reference deferred" in w for w in report["warnings"])  # vbus_main ref

    bad = mod.validate({"recipe_id": "x", "steps": _measure_compare("missing")})
    assert bad["ok"] is False and bad["errors"]


async def test_publish_hard_fails_on_semantic(fsmod):
    mod, _ = fsmod
    created = await mod.create_recipe({**PAYLOAD, "recipe_id": "sem", "steps": _measure_compare("missing")})
    with pytest.raises(RecipeValidationError):
        await mod.publish_draft("sem", created["draft_id"])


async def test_validate_endpoint(fsmod):
    mod, _ = fsmod
    created = await mod.create_recipe(PAYLOAD)
    await mod.publish_draft("inv-c", created["draft_id"])
    async with await _client(mod) as c:
        v = {"Authorization": "Bearer viewer"}
        r = await c.post("/recipes/inv-c/versions/1/validate", headers=v)
        assert r.status_code == 200 and r.json()["ok"] is True


# --- R4: execution wire (Python half) --------------------------------------


def test_runtime_substitution():
    obj = {"a": "${run.vset}", "b": ["${run.lot}", 1], "c": "literal"}
    out = substitute(obj, {"vset": 264.0, "lot": "L1"})
    assert out == {"a": 264.0, "b": ["L1", 1], "c": "literal"}  # typed, recursive


_RUNREF = {
    "schema_version": 1, "recipe_id": "rr", "name": "Run-ref", "owner": "a",
    "barcode_prefixes": [], "tags": [],
    "run_parameters": [{"name": "vset", "kind": "number", "required": True}],
    "steps": [{"step_id": "set", "step_type": "set_output",
               "params": {"variable": "dc_bus_setpoint", "value": "${run.vset}"}}],
}


@pytest.mark.skipif(find_mosquitto() is None, reason="mosquitto not installed")
async def test_recipe_fetch_over_bridge(tmp_path):
    broker = Broker(tmp_path)
    broker.start()
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    plat = BridgeClient("st1", host=broker.host, port=broker.port, client_id="plat")
    lv = BridgeClient("st1", host=broker.host, port=broker.port, client_id="lv")
    core = CoreServices(db=db, bridge=plat,
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    mod = FilesystemRecipe.construct(core, {"root": str(tmp_path / "recipes")})
    await mod.init()
    try:
        created = await mod.create_recipe(_RUNREF)
        await mod.publish_draft("rr", created["draft_id"])
        await plat.connect(wait_timeout=5)
        await mod.start()                       # serves query/recipe.fetch
        await lv.connect(wait_timeout=5)
        await asyncio.sleep(0.3)                # let subscriptions land

        reply = await lv.query("recipe.fetch",
                               {"recipe_id": "rr", "version": 1, "run_parameters": {"vset": 264.0}},
                               timeout=5)
        assert reply["ok"] is True
        assert reply["result"]["steps"][0]["params"]["value"] == 264.0  # substituted
    finally:
        await lv.disconnect()
        await plat.disconnect()
        await db.close()
        broker.stop()
