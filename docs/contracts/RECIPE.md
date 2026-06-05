# RECIPE.md — Test Recipe Module

This doc is the contract for the **Recipe** module: the application-level
description of what to test, with what parameters, against what limits.
The Recipe module owns authoring, validation, versioning, and the wire
shape that LabVIEW reads at run start. It does **not** execute steps —
the **Test Sequencer DQMH** module (`LABVIEW_BRIDGE.md`) does, per the
locked control decision in `PRINCIPLES.md` §0.

Read `PRINCIPLES.md` and `CORE.md` first. This doc sits on top of both.

---

## 0. Locked decisions for this module

| Decision | Choice |
|---|---|
| Recipe shape | **One shape, pluggable step types.** Not three recipe variants. |
| Persistence | JSON on disk, folder-per-recipe with `vN/` subfolders. Same pattern as `BORROWABLE_MODULES.md` #1. |
| Versioning | Append-only; saves create new versions; never overwrite an `active` version. |
| Deletion | **Never.** Status transitions only: `draft → active → deprecated → archived`. |
| Drafts | Live in `drafts/` alongside `vN/` folders. Mutable until published. |
| Identity scope | New product line = new `recipe_id`. Versions are content evolution, not product variation. |
| Step-type schemas | One directory, shared by primitives and application-specific types. |
| Execution seam | LabVIEW Test Sequencer DQMH module owns a single `Execute` request that dispatches internally by `step_type`. Python validates and persists; LabVIEW executes. |
| Validation strictness | Hard-fail at save and at run start; warn-only at load (so historical recipes remain readable for audit). |

---

## 1. Why this module exists

Without it, "the test for product X" is spread across hand-written test
classes, lives only in source control, and changes silently. Operators
can't see what's about to run; auditors can't prove what ran yesterday;
non-engineers can't author new tests.

With it:

- **Test content is data**, validated by schema, versioned by structure.
- **Authoring is one of three styles**, mixed freely inside one recipe:
  primitives (set / measure / compare), composites (repeat / sweep), or
  hand-offs to a LabVIEW test class for the cases primitives can't
  express.
- **Run records cite the exact bytes** that executed — `recipe_id` +
  `version` + `content_hash` — so a year later you can prove a given DUT
  passed against a known artifact.
- **The corpus is RAG-ready by construction**, following `PRINCIPLES.md`
  §5: every recipe carries human-readable metadata; every save is an
  append-only event with a summary.

---

## 2. The recipe shape

One JSON document per version. Validated against
`schemas/recipe.schema.json` at every save.

```jsonc
{
  "schema_version": 1,
  "recipe_id": "inverter-board-rev-c",
  "version": 3,
  "status": "active",

  // ── header ────────────────────────────────────────────────────
  "name": "Inverter Board Rev C — Production",
  "description": "Full production test for Rev C boards. Verifies bus regulation, interlocks, and load response.",
  "owner": "alice@acme.test",
  "created_at": "2026-05-12T09:34:21Z",
  "barcode_prefixes": ["INV-C-", "INVC2026"],
  "tags": ["production", "inverter", "rev-c"],
  "estimated_duration_s": 180,
  "required_role": "operator",
  "linked_documents": ["docs/INV-C-TP.pdf"],

  // ── prompts at run start ──────────────────────────────────────
  "run_parameters": [
    { "name": "serial_number", "kind": "string", "required": true,
      "validation": { "pattern": "^SN[0-9]{8}$" } },
    { "name": "lot_id",        "kind": "string", "required": false }
  ],

  // ── envelope defaults; per-step values override ───────────────
  "defaults": {
    "enabled": true,
    "timeout_ms": 30000,
    "retry_count": 0,
    "on_fail": "stop"
  },

  // ── pre/post hooks ────────────────────────────────────────────
  "setup_steps":    [ /* steps */ ],
  "teardown_steps": [ /* always run, including on abort */ ],

  // ── main body ─────────────────────────────────────────────────
  "steps": [ /* tree of steps */ ],

  // ── stamped at save ───────────────────────────────────────────
  "content_hash": "sha256:9f6c..."
}
```

Every **step** shares this envelope:

```jsonc
{
  "step_id":         "vbus_setpoint_check",        // stable per recipe
  "step_type":       "measure_and_compare",        // registry id
  "name":            "Verify Vbus at 264 V",
  "description":     "Set DC bus to 264 V, settle, measure, compare.",
  "enabled":         true,
  "timeout_ms":      5000,
  "retry_count":     1,
  "on_fail":         "stop",
  "safety_critical": true,
  "params":          { /* type-specific, validated against step_type's schema */ }
}
```

See `STEP_TYPES.md` for the 15 starter step types' parameter schemas.

---

## 3. Step types — one shape, three use cases

| Use case | Step types used |
|---|---|
| **A — Parameter-driven** | `test_reference` steps point at LabVIEW test classes; the recipe carries only parameters and limits. |
| **B — Endurance / cycling** | Composite steps (`repeat`, `sweep`) wrap inner steps of any other type. Composition is recursive in the schema. |
| **C — Sequence editor** | Primitive steps: `set_output`, `measure`, `compare`, `ramp_until`, `wait`, `prompt_operator`, etc. |

The risk you flagged for Type C — "what if a test needs complex
analysis?" — is resolved by **mixing**: a Type-C recipe can drop in a
single `test_reference` step for the one measurement that needs an FFT,
without becoming a "different kind of recipe." Authors aren't forced to
choose a recipe style up front.

---

## 4. The step-type registry

Step types are plugins, registered the same way drivers register
(`HAL.md` §3). New step type = ship a schema + ship a handler.

### 4.1 Two halves of one contract

| Half | Where | What |
|---|---|---|
| **Schema** | Python — `step_types/<type_id>/schema.json` | JSON Schema for `params`; validated at save, load, and run-start. |
| **Handler** | LabVIEW — a sub-case inside the Test Sequencer DQMH `Execute` request | Receives `(step.params, run_context)`, returns `{ status, measurements, message, elapsed_ms }`. |

The JSON Schema is the shared contract across the seam. The Test
Sequencer's `Execute` case switches on `step_type` and dispatches to the
matching sub-VI; adding a new step type means adding one schema file on
the Python side and one sub-VI on the LabVIEW side. No bridge surface
changes; no new MQTT topics.

### 4.2 Registration on the Python side

```python
@register_step_type(
    type_id      = "measure_and_compare",
    display_name = "Measure & compare to limits",
    schema_path  = "schema.json",
    composite    = False,                              # True for repeat/sweep/if/group
    capabilities = ("variable_read",),
)
class MeasureAndCompareStepType: ...
```

Composite step types declare `composite=True` and their schema
references the base step schema for `inner_steps` — recursion is the
natural shape.

### 4.3 The step-types directory

```
step_types/
    _common/
        envelope.schema.json       # base step shape, $ref'd by every type
        condition.schema.json      # the small fixed condition grammar
        limits.schema.json         # min/max/expected
    set_output/
        schema.json
        type.py                    # @register_step_type
    measure/
        ...
    ...
```

Application-specific step types ship into the same directory. There is
no separation between "core" and "app" step types — they're all
registered the same way and validated by the same loader.

---

## 5. Identity, versioning, and the no-delete rule

### 5.1 Three identity levels

```
recipe_id      stable, never changes        "inverter-board-rev-c"
version        monotonic per recipe_id      1, 2, 3, ...
content_hash   sha256 of canonical JSON     stamped at save, immutable
```

A run record stores all three. The hash is the proof artifact for "what
exact bytes ran on this DUT." Compute it at save time and never modify
the file afterwards.

### 5.2 Save = new version

Saving an edit to an active recipe always creates a new version. There
is no in-place mutation of an active version. Drafts are mutable because
they're not yet `active`; the moment a draft is published, it freezes as
`vN+1`.

### 5.3 Folder layout

```
data/recipes/
    inverter-board-rev-c/
        meta.json                      # status, latest_version, owner; only mutable file
        v1/
            recipe.json
            recipe.json.sha256
        v2/
            recipe.json
            recipe.json.sha256
        v3/
            recipe.json
            recipe.json.sha256
        drafts/
            d-2026-06-05-001/
                recipe.json            # mutable until published
                base_version: 3        # which version was forked from
```

### 5.4 New product line = new recipe_id

`inverter-board-rev-d` is a new `recipe_id`, not v4 of `rev-c`. The id
is the product line; versions are the recipe content for that line.
Authoring tools can copy-from-template, but the result is its own
folder.

### 5.5 Diff between versions

```
GET /recipes/{id}/diff?from=2&to=3
   → structured diff of the step trees (added/removed/modified steps,
     changed parameters, header changes)
```

High value, low cost. Operators want "what actually changed since
yesterday's golden run."

---

## 6. Lifecycle states

```
draft        not yet runnable; visible to authors only
active       runnable; default selection
deprecated   not selectable for new runs by default; loadable for historical reference
archived     hidden from default lists; loadable only by explicit version
```

Transitions are append-only events:

```
event/recipe-created       { recipe_id, version=1, by, at }
event/recipe-version-saved { recipe_id, version, content_hash, by, at }
event/recipe-deprecated    { recipe_id, by, at, reason }
event/recipe-archived      { recipe_id, version, by, at }
```

Nothing on disk is ever removed. The `meta.json` file tracks current
status. Every state transition emits a diagnostic event with a
human-readable summary, per `PRINCIPLES.md` §5.

---

## 7. Validation — three layers, all required

| Layer | Checks | When |
|---|---|---|
| **Schema** | Per-step-type JSON Schema; envelope conformance; recipe header fields. | Save + load + import |
| **Cross-reference** | Every variable referenced exists in the Variable Engine; every instance referenced is in the Instance Registry; every `test_class_id` is registered on the LabVIEW side (queried over `bridge.request("sequencer.list_test_classes")` at validation time). | Save + run start |
| **Semantic** | `ramp_until` has a termination condition; `sweep` values lie within the target variable's limits; setup/teardown trees terminate; no infinite repeats without a stop condition. | Save |

Strictness rule (locked decision): hard-fail at save and at run start;
warn-only at load. This keeps old recipes readable after a HAL change
while preventing broken recipes from being run.

```
POST /recipes/{id}/v{n}/validate?station=N
   → { ok: bool, errors: [...], warnings: [...] }
```

The UI calls this before run start. Operators see issues before step 3
of 47 fails on a missing variable.

---

## 8. Run-time parameters

`run_parameters` declares values not known until run start (serial,
lot, operator notes). The UI prompts; the orchestrator passes the
resulting dict into the run start request:

```
POST /run/start
{
  "recipe_id":       "inverter-board-rev-c",
  "version":         3,
  "station":         1,
  "run_parameters":  { "serial_number": "SN12345678", "lot_id": "L-2026-A" }
}
```

Inside step params, run-time values appear as
`${run.serial_number}` substitutions. A small recursive walker
substitutes at run start, before the recipe goes over the bridge to
LabVIEW. No expression language — pure substitution.

Validation rules: each `run_parameters` entry declares `kind` (string |
number | bool), `required`, and optional `validation` (regex for
strings, min/max for numbers).

---

## 9. Persistence and the RAG envelope

Every recipe write passes through `core.db` and is stamped with the
common envelope from `CORE.md` §7:

```json
{
  "id":             "<uuid>",
  "type":           "recipe.version",
  "ts":             1748513761.234,
  "station":        "st1",
  "source_version": "1.0.0",
  "summary":        "Saved v3 of 'Inverter Board Rev C — Production' (3 new steps added, 1 limit tightened)",
  "data":           { /* the recipe JSON */ }
}
```

The `summary` is generated from the diff between the new version and
the previous one. It is the natural-language hook a future Knowledge
module will retrieve on.

Lifecycle events (`recipe-deprecated`, `recipe-archived`,
`recipe-imported`) get their own envelope records with their own
summaries. Together, the recipe corpus is **append-only**, **stably
identified**, and **self-describing** — the three properties
`PRINCIPLES.md` §5 calls out.

---

## 10. Export / import

### 10.1 Single recipe export

```
GET /recipes/{id}/export?versions=all|latest|range:2-4
   → ZIP: recipe-{id}-{date}.zip
          /meta.json
          /v1/recipe.json + .sha256
          /v2/recipe.json + .sha256
          ...
          /manifest.json     # export envelope
```

The export `manifest.json` carries source station, `exported_at`,
`source_version`, and a manifest hash (sha256 over every file in the
ZIP) so corruption is detectable. Vendor signature is a future
addition (same key pair as `license.json` in `CORE.md` §3.3).

### 10.2 All recipes export

```
GET /recipes/export-all
   → ZIP of all recipe folders + top-level manifest.json
```

### 10.3 Import

```
POST /recipes/import
  multipart: file=<zip>
  query:     mode=add | update | reject_on_conflict
   → { imported: [...], skipped: [...], conflicts: [...] }
```

Conflict policy on same `recipe_id`:

- `add` — import only if `recipe_id` is new on this station; skip if
  present.
- `update` — import incoming versions as new `vN+k` on the existing
  `recipe_id`; never overwrites.
- `reject_on_conflict` — fail the whole import if any conflict.

Import is itself an event: `event/recipe-imported` with source, count,
mode, and conflicts.

---

## 11. The Recipe module contract

Per `CORE.md` §6.3, siblings depend on this contract, not the package.

```python
class RecipeContract(Protocol):
    # discovery
    list_recipes(*, status=None, tag=None) -> list[RecipeSummary]
    list_versions(recipe_id) -> list[VersionInfo]
    get_recipe(recipe_id, version=None) -> Recipe       # latest if version None
    get_by_barcode(barcode) -> Recipe                   # used by run start

    # authoring
    create_recipe(payload) -> Recipe                    # status=draft, version=1
    save_draft(recipe_id, draft_id, payload) -> Recipe
    publish_draft(recipe_id, draft_id) -> Recipe        # → vN+1, status=active
    deprecate(recipe_id, reason) -> None
    archive(recipe_id, version) -> None

    # validation + diff
    validate(payload, *, station=None, strict=False) -> ValidationReport
    diff(recipe_id, from_v, to_v) -> RecipeDiff

    # export / import
    export_recipe(recipe_id, versions="latest") -> bytes
    export_all() -> bytes
    import_bundle(data, mode) -> ImportReport

    # step-type registry introspection (for authoring UI)
    list_step_types() -> list[StepTypeInfo]
    get_step_schema(type_id) -> JsonSchema
```

REST surface (per `DATA_TRANSFER.md` §5 conventions):

```
GET    /recipes
GET    /recipes/{id}
GET    /recipes/{id}/versions
GET    /recipes/{id}/versions/{n}
POST   /recipes                                      # create
POST   /recipes/{id}/drafts                          # fork a draft
PUT    /recipes/{id}/drafts/{draft_id}               # update draft
POST   /recipes/{id}/drafts/{draft_id}/publish       # → new vN
POST   /recipes/{id}/deprecate
POST   /recipes/{id}/versions/{n}/archive
GET    /recipes/{id}/diff?from=&to=
POST   /recipes/{id}/versions/{n}/validate?station=
GET    /recipes/{id}/export?versions=
GET    /recipes/export-all
POST   /recipes/import
GET    /recipes/by-barcode/{prefix}
GET    /recipes/step-types
GET    /recipes/step-types/{type_id}/schema
```

Events emitted over MQTT (see §6 for shapes):

```
event/recipe-created
event/recipe-version-saved
event/recipe-deprecated
event/recipe-archived
event/recipe-imported
```

The Test Sequencer reads the recipe at run start by calling
`bridge.request("recipe.fetch", { recipe_id, version, station })` —
synchronous, single round-trip, returns the full recipe JSON. No event
subscription needed for execution; events are for audit and the future
RAG corpus.

---

## 12. Repo layout (extends `CORE.md` §8)

```
backend/modules/recipe/
    manifest.json
    __init__.py                       # @register_module + variants
    contract.py                       # RecipeContract
    variants/
        filesystem.py                 # the default variant
    api.py                            # FastAPI router
    storage.py                        # folder layout + meta.json
    versioning.py                     # save / publish / hash
    validation/
        schema.py                     # JSON Schema validation
        cross_reference.py            # variable / instance / test_class checks
        semantic.py                   # ramp_until / sweep / loop checks
    diff.py                           # structured version diff
    export_import.py                  # zip pack / unpack
    runtime_params.py                 # ${run.x} substitution walker
    step_types/                       # one dir per step type
        _common/
            envelope.schema.json
            condition.schema.json
            limits.schema.json
        set_output/
            schema.json
            type.py
        measure/
            schema.json
            type.py
        ...
    migrations/
    tester/                           # pytest + smoke harness
data/recipes/                         # gitignored runtime store
```

---

## 13. Build phases

Mapped to the `PRINCIPLES.md` build order. The Recipe module is part of
the **business modules** phase, after the walking skeleton and the DAQ
vertical.

| Slice | Scope | LabVIEW dependency |
|---|---|---|
| **R1 — skeleton** | Module activates through the gate; manifest; `filesystem` variant; the 15 starter step-type schemas; `list_step_types` / `get_step_schema` endpoints. No execution yet. | None |
| **R2 — authoring** | CRUD endpoints for recipes + draft/publish lifecycle + folder layout + content hashing + `meta.json`. UI can author, but recipes don't run yet. | None |
| **R3 — validation** | Schema + cross-reference + semantic; `validate` endpoint; lint UI surface. | Reads Variable Engine + Instance Registry; queries LabVIEW for `list_test_classes`. |
| **R4 — execution wire** | `bridge.request("recipe.fetch", ...)` reachable from LabVIEW; Test Sequencer DQMH `Execute` case with handlers for the 15 starter types; `event/step-completed` events flow back. | **This is the seam slice.** |
| **R5 — export / import** | ZIP pack/unpack, conflict modes, audit events, content hashes on every file. | None |
| **R6 — diff + polish** | Version diff endpoint, deprecate/archive transitions, `required_role` enforcement, `run_parameters` substitution. | None |

R1–R3 are pure Python and can ship before any LabVIEW work. R4 is the
riskiest single piece; same shape as the DAQ vertical and best done
early in the LabVIEW work.

---

## 14. Phase-1 (R1) acceptance criteria

Mirrors `CORE.md` §10. R1 is complete when, end to end:

1. Recipe module activates through the gate. `/modules/status` shows it
   loaded.
2. `GET /recipes/step-types` returns 15 entries.
3. `GET /recipes/step-types/measure_and_compare/schema` returns a valid
   JSON Schema document.
4. Flipping `recipe` to `false` in `license.json` makes the module
   inactive; `/modules/status` shows the reason.
5. The diagnostic event for module activation is visible in MQTT
   Explorer with a meaningful summary.
6. The tester runs against `core + recipe` alone (no other module) and
   passes.

R2–R6 acceptance criteria are recorded as each slice is built; the
shape is the same — every slice ships a tester, an updated
`/modules/status` story, and an MQTT Explorer trail.

---

## 15. Reference reading

- `PRINCIPLES.md` — the constitution this module sits under.
- `CORE.md` — the platform this module plugs into.
- `LABVIEW_BRIDGE.md` — the bridge surface and topic convention.
- `HAL.md` + `VARIABLE_ENGINE.md` — the cross-reference validation
  targets.
- `BORROWABLE_MODULES.md` #1 — the recipe folder pattern this extends.
- `STEP_TYPES.md` — the catalog of 15 starter step type schemas.
