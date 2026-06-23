# Module framework

How a feature becomes a module. Read alongside `CORE.md` §2.

## Anatomy
```
backend/modules/<id>/
  __init__.py        register_module + register_variant
  contract.py        Protocol the module fulfils (for cross-module use)
  manifest.json      id, entitlement_key, variants, core_dependencies, config_schema
  api.py             build_router(module) -> APIRouter
  variants/<v>.py    the implementation (construct/init/start/stop[/health])
  schemas/*.json     config schema(s)
  tester/test_*.py   standalone tester (real db, no broker)
```

## Registration
```python
@register_module("config", contract=ConfigContract, contract_version=1, display_name="Configuration")
class ConfigModule: ...
register_variant("config", "default", display_name="Default")(DefaultConfig)
```

## Lifecycle
`construct(core, config) -> init() -> start() -> stop()` (+ optional `health()`).
Long-running work (schedulers, subscriptions) starts in `start()`, cancels in `stop()`.

## Activation gate
A module loads only when **config ∩ license** allow it (`core/framework/gate.py`):
- Listed in `app.json` `modules[]`, AND
- `entitlement_key` enabled in `license.json` (+ the variant licensed).
Otherwise it's **skipped and the app continues** (loud diag, never a crash).

## CoreServices (DI)
The variant gets `core`: `db` (repo), `diag`, `bridge`, `config`, `auth`, `interlock`, `station`, and `get_contract(id)` to reach other modules' contracts. MQTT handlers are wired from `self.mqtt_handlers = [(subtopic, handler), …]`.

## Permissions
Routes gate with `require_permission("DOMAIN.ACTION")`. Add new permissions to the catalog (`modules/auth/permissions_catalog.py`) and grant them in role config.

## Checklist
Register · manifest · config schema · routes gated · tester · add to `app.json` + `license.json` (examples **and** live) · grant perms · docs.
