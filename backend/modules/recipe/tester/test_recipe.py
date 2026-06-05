"""recipe standalone tester (CORE.md §6.2). R1: step-type registry + schemas."""

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

import modules.recipe  # noqa: F401 — registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from core.services.auth_verify import AuthError, Principal, TokenVerifier
from modules.recipe.variants.filesystem import FilesystemRecipe

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
