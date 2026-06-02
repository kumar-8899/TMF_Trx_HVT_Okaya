"""The activation gate (CORE.md §4) — config ∩ license, skip-and-continue."""

import json

import pytest

from core.framework.contract import Core, Health
from core.framework.gate import activate_modules
from core.framework.manifest import ManifestLoader
from core.framework.registry import Registry
from core.services.config import ConfigService
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from core.services.licensing import License


class FakeWeb:
    def __init__(self):
        self.mounted = []

    def mount(self, router, prefix):
        self.mounted.append((router, prefix))


def make_variant():
    """A minimal Module implementation for the gate to drive."""

    class DummyDefault:
        def __init__(self):
            self.router = None
            self.mqtt_handlers = []
            self.events = []

        @classmethod
        def construct(cls, core, config):
            obj = cls()
            obj.core, obj.config = core, config
            return obj

        async def init(self):
            self.events.append("init")

        async def start(self):
            self.events.append("start")

        async def stop(self):
            self.events.append("stop")

        async def health(self):
            return Health()

    return DummyDefault


def write_manifest(modules_dir, mid, *, contract_deps=None, core_deps=("db", "config", "diag")):
    d = modules_dir / mid
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "module": {
                    "id": mid,
                    "version": "1.0.0",
                    "contract_version": 1,
                    "display_name": mid.title(),
                },
                "entitlement_key": mid,
                "variants": ["default"],
                "core_dependencies": list(core_deps),
                "contract_dependencies": list(contract_deps or []),
                "contributes": {"api_prefix": f"/{mid}"},
                "config_schema": None,
            }
        )
    )


@pytest.fixture
async def ctx(tmp_path):
    db = Database(":memory:")
    await db.connect()
    config = ConfigService(tmp_path)
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    core = Core(db=db, bridge=None, config=config, auth=None, diag=diag, web=FakeWeb(), station="st1")
    reg = Registry()
    modules_dir = tmp_path / "modules"
    yield core, reg, modules_dir, diag
    await db.close()


def register(reg, mid):
    @reg.register_module(mid, contract=object, display_name=mid.title())
    class Base:
        pass

    reg.register_variant(mid, "default")(make_variant())


def lic(modules, variants=None):
    return License(
        {"entitlements": {"modules": modules, "variants": variants or {}}}, valid=True
    )


async def _run(core, reg, modules_dir, diag, app_config, license):
    return await activate_modules(
        core=core,
        registry=reg,
        manifests=ManifestLoader(modules_dir=modules_dir),
        app_config=app_config,
        license=license,
        diag=diag,
    )


async def test_happy_path_loads_and_starts(ctx):
    core, reg, modules_dir, diag = ctx
    register(reg, "dummy")
    write_manifest(modules_dir, "dummy")
    app_config = {"modules": [{"id": "dummy", "variant": "default"}]}

    result = await _run(core, reg, modules_dir, diag, app_config, lic({"dummy": True}))

    assert "dummy" in result.active
    assert result.active["dummy"].events == ["init", "start"]
    assert core.contracts["dummy"] is result.active["dummy"]
    payload = result.status_payload()
    assert payload["loaded"] == ["dummy"]
    assert payload["skipped"] == []


async def test_unlicensed_module_skipped_with_reason(ctx):
    core, reg, modules_dir, diag = ctx
    register(reg, "dummy")
    write_manifest(modules_dir, "dummy")
    app_config = {"modules": [{"id": "dummy", "variant": "default"}]}

    # license flip: dummy = False (CORE.md §10 #3)
    result = await _run(core, reg, modules_dir, diag, app_config, lic({"dummy": False}))

    assert "dummy" not in result.active
    skipped = result.status_payload()["skipped"]
    assert skipped == [{"id": "dummy", "variant": "default", "reason": "not licensed"}]


async def test_unregistered_module_skipped(ctx):
    core, reg, modules_dir, diag = ctx
    app_config = {"modules": [{"id": "ghost", "variant": "default"}]}
    result = await _run(core, reg, modules_dir, diag, app_config, lic({"ghost": True}))
    assert result.status_payload()["skipped"][0]["reason"] == "not registered"


async def test_unknown_variant_skipped(ctx):
    core, reg, modules_dir, diag = ctx
    register(reg, "dummy")
    write_manifest(modules_dir, "dummy")
    app_config = {"modules": [{"id": "dummy", "variant": "bogus"}]}
    result = await _run(core, reg, modules_dir, diag, app_config, lic({"dummy": True}))
    assert "unknown variant" in result.status_payload()["skipped"][0]["reason"]


async def test_missing_contract_dependency_skipped(ctx):
    core, reg, modules_dir, diag = ctx
    register(reg, "needy")
    write_manifest(modules_dir, "needy", contract_deps=["provider"])
    app_config = {"modules": [{"id": "needy", "variant": "default"}]}
    result = await _run(core, reg, modules_dir, diag, app_config, lic({"needy": True}))
    assert result.status_payload()["skipped"][0]["reason"] == "needs contract 'provider'"


async def test_contract_dependency_satisfied_in_order(ctx):
    core, reg, modules_dir, diag = ctx
    register(reg, "provider")
    register(reg, "needy")
    write_manifest(modules_dir, "provider")
    write_manifest(modules_dir, "needy", contract_deps=["provider"])
    app_config = {
        "modules": [
            {"id": "provider", "variant": "default"},
            {"id": "needy", "variant": "default"},
        ]
    }
    result = await _run(
        core, reg, modules_dir, diag, app_config, lic({"provider": True, "needy": True})
    )
    assert set(result.active) == {"provider", "needy"}


async def test_bad_entry_does_not_sink_the_app(ctx):
    """HAL rule: one bad module skips, the rest still come up (CORE.md §4)."""
    core, reg, modules_dir, diag = ctx
    register(reg, "good")
    write_manifest(modules_dir, "good")
    # 'bad' registered but no manifest on disk -> bad manifest, skipped
    register(reg, "bad")
    app_config = {
        "modules": [
            {"id": "bad", "variant": "default"},
            {"id": "good", "variant": "default"},
        ]
    }
    result = await _run(core, reg, modules_dir, diag, app_config, lic({"good": True, "bad": True}))
    assert "good" in result.active
    assert "bad" not in result.active
