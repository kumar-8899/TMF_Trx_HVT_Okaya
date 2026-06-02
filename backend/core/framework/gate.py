"""The activation gate (CORE.md §4).

config ∩ license over the registered set. Follows the HAL rule: a bad entry
logs and is skipped; the app still comes up usable. Produces a report that
backs GET /modules/status (a debug surface + the entitlement mirror the
frontend reads).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.framework.contract import Core
from core.framework.manifest import ManifestError, ManifestLoader
from core.framework.registry import Registry, RegistryError
from core.services.diagnostics import Diagnostics
from core.services.licensing import License


@dataclass
class ModuleStatus:
    id: str
    variant: str
    loaded: bool
    reason: str = ""
    display_name: str = ""


@dataclass
class ActivationResult:
    active: dict = field(default_factory=dict)   # module_id -> instance
    report: list = field(default_factory=list)   # list[ModuleStatus]

    def status_payload(self) -> dict:
        return {
            "loaded": [s.id for s in self.report if s.loaded],
            "skipped": [
                {"id": s.id, "variant": s.variant, "reason": s.reason}
                for s in self.report
                if not s.loaded
            ],
            "modules": [
                {
                    "id": s.id,
                    "variant": s.variant,
                    "status": "loaded" if s.loaded else "skipped",
                    "reason": s.reason,
                    "display_name": s.display_name,
                }
                for s in self.report
            ],
        }


async def activate_modules(
    *,
    core: Core,
    registry: Registry,
    manifests: ManifestLoader,
    app_config: dict,
    license: License,
    diag: Diagnostics,
) -> ActivationResult:
    result = ActivationResult()
    active_contracts: set[str] = set()

    def skip(entry_id: str, variant: str, reason: str, display: str = "") -> None:
        diag.warning("gate", "module skipped", module=entry_id, variant=variant, reason=reason)
        result.report.append(ModuleStatus(entry_id, variant, False, reason, display))

    for entry in app_config.get("modules", []):
        mid, variant = entry["id"], entry["variant"]
        try:
            rec = registry.get(mid)
        except RegistryError:
            skip(mid, variant, "not registered")
            continue

        if not license.allows_module(mid):
            skip(mid, variant, "not licensed", rec.display_name)
            continue
        if variant not in rec.variant_ids:
            skip(mid, variant, f"unknown variant '{variant}'", rec.display_name)
            continue
        if not license.allows_variant(mid, variant):
            skip(mid, variant, "variant not licensed", rec.display_name)
            continue

        try:
            manifest = manifests.load(mid)
        except ManifestError as exc:
            skip(mid, variant, f"bad manifest: {exc}", rec.display_name)
            continue

        missing = [d for d in manifest.contract_dependencies if d not in active_contracts]
        if missing:
            skip(mid, variant, f"needs contract '{missing[0]}'", rec.display_name)
            continue

        try:
            cfg = core.config.load_module(mid, entry.get("config", {}), manifest.config_schema_path)
            services = core.select(manifest.core_dependencies)
            inst = registry.variant(mid, variant).construct(services, cfg)
            await inst.init()
        except Exception as exc:  # noqa: BLE001 — bad entry skips, app stays up (CORE.md §4)
            skip(mid, variant, f"init failed: {exc}", rec.display_name)
            continue

        core.web.mount(getattr(inst, "router", None), manifest.contributes.api_prefix)
        if core.bridge is not None:
            for topic, handler in getattr(inst, "mqtt_handlers", []):
                core.bridge.subscribe(topic, handler)
        await core.db.run_migrations(manifest.migrations_path)

        result.active[mid] = inst
        core.contracts[rec.contract_id] = inst
        active_contracts.add(rec.contract_id)
        result.report.append(ModuleStatus(mid, variant, True, "", rec.display_name))
        diag.info("gate", "module loaded", module=mid, variant=variant)

    # Start phase — everything constructed + wired before traffic moves (CORE.md §4, §5).
    for mid, inst in result.active.items():
        await inst.start()
        diag.info("gate", "module started", module=mid)

    return result
