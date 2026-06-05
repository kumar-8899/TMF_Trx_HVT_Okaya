"""logs standalone tester (CORE.md §6.2). L1: registration + manifest + skeleton."""

import modules.logs  # noqa: F401 — import registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from modules.logs.variants.db import DbLogs


def test_registered():
    rec = default_registry.get("logs")
    assert rec.variant_ids == ["db"]
    assert default_registry.variant("logs", "db") is DbLogs


def test_manifest_valid():
    m = ManifestLoader().load("logs")
    assert m.entitlement_key == "logs"
    assert m.variants == ["db"]
    assert m.contributes.api_prefix == "/logs"
    assert set(m.core_dependencies) == {"db", "bridge", "config", "auth", "diag", "web"}


async def test_skeleton_lifecycle():
    core = CoreServices(station="st1")
    mod = DbLogs.construct(core, {})
    await mod.init()
    await mod.start()
    health = await mod.health()
    assert health.status.value == "ok"
    await mod.stop()
