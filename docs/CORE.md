# CORE.md — The Application Platform

The **core** is the small, stable Python layer every module depends on. It is
**not a module**; it is the platform modules plug into. It hosts the module
framework, owns the shared services, and runs the web edge.

The **controller** (test execution — sequence, step timing, abort/timeout,
safety) lives in **LabVIEW** and is reached over MQTT (`LABVIEW_BRIDGE.md`).
The core is the application platform around that controller: web, persistence,
the module framework, and the bridge client.

Read `PRINCIPLES.md` first; this doc implements §1, §2, §3, §6 of it.

---

## 1. The seven core services

Everything depends on these; they depend on nothing else.

| Service | Exposes to modules | Notes |
|---|---|---|
| **db** | repositories, sessions, migration runner | base repository stamps the RAG envelope (§7) |
| **bridge** | `publish` / `request` / `subscribe` to LabVIEW | the Python side of `LABVIEW_BRIDGE.md` |
| **config** | validated config access per module | JSON + JSON Schema, `schema_version` header |
| **auth** | `verify(token) -> Principal`, `require_role(...)` | **port** filled by the active Auth variant (§6.4) |
| **diag** | `debug/info/warning/error/exception`, `timed(...)` | the bus from `LOGGING.md` §2.4 |
| **web** | mount a router under a prefix; error handlers | FastAPI shell; RFC-7807 bodies; CORS; request-id |
| **(framework)** | registry, manifest loader, activation gate | §3–§5 of this doc |

### CoreServices — the injected container

At activation the core hands each module exactly the services its manifest
declared (`core_dependencies`). Simple, explicit dependency injection — no DI
framework.

```
CoreServices:
    db           : Database          # repositories, sessions, migrations
    bridge       : BridgeClient      # publish / request / subscribe to LabVIEW
    config       : ConfigService     # validated config for this module
    auth         : TokenVerifier     # verify(token) -> Principal ; require_role
    diag         : Diagnostics       # emit family + timed span
    web          : WebShell          # mount routers, error handlers
    station      : str               # this station id
    get_contract : (name) -> object  # resolve a sibling CONTRACT to its active variant
```

---

## 2. What a module is

- A **contract** — the operations it exposes and events it emits.
- One or more **variants** — interchangeable implementations of that contract.
- A **manifest** — static JSON self-description (ships with the module).
- A **registration** — code that self-registers the module and its variants.

### 2.1 Registration (the driver-registry pattern, generalised)

```
@register_module(
    module_id       = "auth",
    contract        = AuthContract,
    contract_version= 1,
    display_name    = "User Authentication",
)
class AuthModule: ...

@register_variant("auth", "local_db", display_name="Local DB sessions")
class LocalDbAuth(AuthModule): ...

@register_variant("auth", "ldap", display_name="LDAP / AD")
class LdapAuth(AuthModule): ...
```

Autodiscovery imports every module package at startup so the decorators fire.
Duplicate `(module_id, variant_id)` MUST fail loudly. Lookup of an unknown id
MUST raise, never return null.

### 2.2 The contract a variant implements

```
class Module(Protocol):
    manifest       : Manifest
    router         : APIRouter | None              # contributed routes (optional)
    mqtt_handlers  : list[(topic, handler)]        # contributed subscriptions (optional)

    @classmethod
    def construct(core: CoreServices, config: dict) -> "Module"
    async def init()   -> None      # wire up; NO traffic yet
    async def start()  -> None      # begin work: subscribe, schedule, open
    async def stop()   -> None      # graceful shutdown
    async def health() -> Health    # for /readyz and /modules/status
```

`init` then `start` is the same two-phase bring-up the rest of the system uses:
everything is constructed and wired before anything starts moving traffic.

---

## 3. The three data layers

Mirrors the HAL exactly:

| Layer | JSON | Analogous to | Controlled by |
|---|---|---|---|
| **Manifest** | per module, static | hardware-catalog entry | module author |
| **Deployment config** | per station | `stations.toml` | deployer / installer |
| **License** | per customer | (new layer on top) | the vendor |

### 3.1 Module manifest

```json
{
  "schema_version": 1,
  "module": {
    "id": "auth",
    "version": "1.0.0",
    "contract_version": 1,
    "display_name": "User Authentication",
    "description": "Issues and validates operator sessions."
  },
  "entitlement_key": "auth",
  "variants": ["local_db", "ldap", "sso"],
  "core_dependencies": ["db", "config", "diagnostics", "auth", "web"],
  "contract_dependencies": [],
  "contributes": {
    "api_prefix": "/auth",
    "mqtt_subscriptions": [],
    "migrations": "migrations/",
    "frontend_flags": ["auth.sso_enabled"]
  },
  "config_schema": "schemas/auth.config.schema.json"
}
```

`contract_dependencies` lists other modules' **contracts** (not packages) — see §6.3.

### 3.2 Deployment config (`config/app.json`)

```json
{
  "schema_version": 1,
  "station": "st1",
  "license": "config/license.json",
  "modules": [
    { "id": "auth",   "variant": "local_db",  "config": { "session_ttl_min": 480 } },
    { "id": "recipe", "variant": "filesystem", "config": { "root": "data/recipes" } },
    { "id": "logs",   "variant": "jsonl" }
  ]
}
```

### 3.3 License / entitlements (`config/license.json`)

```json
{
  "schema_version": 1,
  "plan": "pro",
  "issued_to": "Acme Test Lab",
  "expires": "2027-01-01T00:00:00Z",
  "entitlements": {
    "modules":  { "auth": true, "recipe": true, "report": true, "analytics": false },
    "variants": { "auth": ["local_db", "ldap"] },
    "features": { "report.pdf": true, "report.advanced": false },
    "limits":   { "max_stations": 4, "max_users": 25 }
  },
  "signature": "<detached signature, verified by the Licensing module>"
}
```

The license is **data**, signed, and validated by the Licensing module. The
gate (§4) treats absent entitlements as "off" (fail-closed).

---

## 4. The activation gate

The startup resolution pipeline — config ∩ license over the registered set,
following the HAL rule: **a bad entry logs and is skipped; the app still comes
up usable.**

```
discover()                                    # decorators fire; registry populated
license = Licensing.load_and_verify()         # signature + expiry; entitlements

for entry in app.modules:
    m = registry.get(entry.id)                       # registered?      else skip + log
    if not license.allows_module(entry.id):          # licensed?        else skip + log "not licensed"
        continue
    if entry.variant not in m.variants:              # variant exists?  else skip + log
        continue
    if not license.allows_variant(entry.id,
                                   entry.variant):    # variant licensed? else skip + log
        continue
    for dep in m.contract_dependencies:              # required contracts present?
        if dep not in active_contracts:
            log + skip "needs contract {dep}"; break
    cfg      = config.load(entry.id, entry.config, m.config_schema)   # validate
    services = core.select(m.core_dependencies)                       # inject ONLY declared
    inst     = registry.variant(entry.id, entry.variant) \
                       .construct(services, cfg)
    await inst.init()
    web.mount(inst.router, m.contributes.api_prefix)
    bridge.subscribe(inst.mqtt_handlers)
    db.run_migrations(m.contributes.migrations)
    active[entry.id] = inst
    active_contracts.add(m.contract_id)

for inst in active.values():
    await inst.start()

expose GET /modules/status   # loaded vs skipped + reason (for debugging + the UI)
```

`GET /modules/status` is both a debugging surface (Principle 6) and the source
the frontend reads to reflect entitlements (Principle 11).

---

## 5. App lifecycle

```
1. Boot core services      db.connect · bridge.connect · config.load · diag.start
2. Activate modules        the gate (§4)         — log + continue on per-module failure
3. Start modules           inst.start() for each active module
4. Serve
5. Shutdown (reverse)      inst.stop() · bridge.disconnect · db.close
```

Health endpoints (`BORROWABLE_MODULES.md` #4):

- `GET /healthz` → process alive. Trivial.
- `GET /readyz` → core services up **and** the LabVIEW bridge link is online (its `status` retained = `online`) **and** every module marked required has started.

---

## 6. Dependency rules

### 6.1 Modules depend on the core, never on each other

A module imports only the core. Two modules sharing a concern (Auth and
Analytics both using a database) share the **core's** db service; neither
imports the other.

### 6.2 Standalone = core + this module

Every module must boot and run with only the core present — this is what makes
"a tester as we go" tractable (Principle 1). The DQMH/pytest tester for a module
exercises it against the core alone.

### 6.3 Collaboration is through contracts, not packages

When a module genuinely needs another's capability at runtime, it declares a
dependency on that module's **contract** (interface) in
`contract_dependencies` and resolves it via `core.get_contract("recipe")`,
which returns whatever variant is active. It MUST NOT import the sibling
package. The contract is the seam — same as HAL capability interfaces.

For standalone testing, the tester injects **stub** implementations of declared
contract dependencies. "Standalone" then means: core + this module + stubs for
its declared contracts.

### 6.4 Token verification: a core port the Auth variant fills

Verification depends on the auth scheme (DB sessions vs JWT vs SSO), so the core
exposes `core.auth` as a **port**. The active Auth variant registers its
verifier into that port at `init`. Every other module uses `core.auth` and never
touches the Auth package. If no Auth module is loaded, `core.auth` rejects all
tokens (fail-closed); a dev-only `no-auth` variant exists for local work.

---

## 7. Persistence and the RAG envelope

The base repository stamps every record with the common metadata envelope from
`PRINCIPLES.md` §5, so a module **cannot** persist a record without it:

```
Repository.put(record_type, payload, *, id=None, summary=None) -> id
    # writes:
    # {
    #   "id":             <uuid or supplied>,
    #   "type":           record_type,
    #   "ts":             <epoch seconds, float>,
    #   "station":        <core.station>,
    #   "source_version": <app version>,
    #   "summary":        <human-readable one-liner>,
    #   "data":           payload            # the module's own JSON
    # }

Repository.get(record_type, id)
Repository.query(record_type, filter=None, since=None, limit=None)
```

Records are append-only where the domain allows (logs, run records, recipe
versions). These stores are the future RAG corpus; nothing is stored as a
rendered-only report.

Run records are an example of the pattern, not core code: LabVIEW (the
controller) emits `event/run-*` over MQTT, and a small module subscribed to
those topics persists run records through this repository for Report/Analytics
to read.

---

## 8. Repo layout

```
repo/
  backend/                       # Python — the platform + modules
    core/
      app.py                     # app factory + lifespan (§5)
      services/
        db.py                    # pool, sessions, base repository (§7)
        bridge.py                # MQTT bridge client — Python side of LABVIEW_BRIDGE.md
        config.py                # JSON + JSON Schema loader
        auth_verify.py           # the core.auth port (§6.4)
        diagnostics.py           # the bus (LOGGING.md)
      framework/
        registry.py              # @register_module / @register_variant + discovery
        manifest.py              # manifest schema + loader
        gate.py                  # the activation gate (§4)
        contract.py              # Module protocol, CoreServices, Health
      schemas/                   # core JSON Schemas: manifest, app, license, envelope
    modules/
      auth/
        manifest.json
        __init__.py              # registers module + variants
        contract.py              # AuthContract
        variants/
          local_db.py
          ldap.py
        api.py                   # FastAPI router
        migrations/
        tester/                  # pytest + smoke harness
      recipe/   …
      logs/     …
      report/   …
    config/
      app.example.json
      license.example.json
    pyproject.toml
  labview/                       # the controller + DQMH modules
    src/                         # LabVIEW project (Super Test App.lvproj)
    Source/
      Modules/
        MQTT Bridge/             # the single DQMH Bridge module (MQTT)
        # controller / DAQ / safety DQMH modules land here
    bridge/                      # README: the Bridge wire contract (pinned to backend/tools/lv_stub.py)
    drivers/  hardware-catalog/  stations.json  variables.json   # the HAL, JSON
  frontend/                      # React shell (unchanged)
  src-tauri/                     # Tauri shell + installer
  deploy/                        # mosquitto.conf, CI
  docs/                          # PRINCIPLES.md, CORE.md, LABVIEW_BRIDGE.md, contracts/*
```

(`live` config files are gitignored and copied from `*.example.json` on first run.)

---

## 9. The reference module (`hello`)

A throwaway module that proves the whole path for the walking skeleton:

- Registers one variant (`default`); has a manifest with `entitlement_key = "hello"`.
- Contributes `GET /hello/ping` → `{ "pong": true, "station": ... }`.
- On that route, issues one `bridge.request("hello.echo", {...})` to a LabVIEW stub and returns the reply (proves the MQTT round-trip).
- Emits one `diag.info("hello", "pinged", ...)` (proves the bus + MQTT Explorer visibility).
- Ships a tester that calls `/hello/ping` against `core + hello` alone.

It is deleted once real modules exist.

---

## 10. Phase-0 acceptance criteria (walking skeleton "done")

The skeleton is complete when, end to end:

1. The app boots through the §5 lifecycle; all core services come up.
2. The `hello` module activates through the gate (§4); `/modules/status` shows it loaded.
3. Flipping `hello` to `false` in `license.json` makes it **not** load, with the reason shown in `/modules/status` — gating proven.
4. `/healthz` is green; `/readyz` is green only once the bridge link `status` is `online`.
5. `GET /hello/ping` returns a reply that round-tripped through MQTT to a LabVIEW stub.
6. One `stream/{signal}` frame and one retained `value/{var}` flow LabVIEW → Python and are visible in MQTT Explorer alongside the `diag` event.
7. The LWT works: kill the LabVIEW stub and `status` flips to `offline`; `/readyz` goes not-ready.
8. CI builds the PyInstaller sidecar + the LabVIEW EXE + the Tauri installer on commit.

Meeting all ten leaves every real module dropping onto proven rails.
