# Phase 2 — Recipe acceptance (Test Recipe)

Third business module. Spec: [contracts/RECIPE.md](contracts/RECIPE.md) +
[contracts/STEP_TYPES.md](contracts/STEP_TYPES.md). One recipe shape, pluggable
step types; filesystem-versioned (append-only, no delete) + DB corpus mirror.

## Status (Python side complete; R1–R6)

| Slice | Scope | Status |
|---|---|---|
| R1 | gate-load, step-type registry (15 types), `list_step_types`/`get_step_schema` | ✅ |
| R2 | authoring + versioning (folder-per-recipe, drafts, content_hash, corpus mirror) | ✅ |
| R3 | validation: schema + semantic (hard-fail at publish); cross-reference deferred (warn-only) | ✅ |
| R4 | execution wire: `bridge.serve("recipe.fetch")` + `${run.x}` substitution (`query/{op}`) | ✅ |
| R5 | export/import: ZIP + manifest hash; add/update/reject conflict modes; `recipe-imported` | ✅ |
| R6 | version diff + diff-based save summary; `required_role` surfaced; lifecycle transitions | ✅ |

`cd backend; ruff check .; pytest -q` → all green; recipe needs no broker except
the R4 round-trip (skipped without mosquitto).

## Reconciliations (vs RECIPE.md, locked with the user)
- Permission-first: reads `RECIPE.VIEW`, writes `RECIPE.EDIT` (not the doc's role).
- Topics: our station-relative tree; new **`query/{op}`** class (LV→Py, Python-served)
  documented in LABVIEW_BRIDGE §3/§5.
- Persistence: filesystem source of truth **+** `recipe.version` envelope in `core.db`.
- Export ZIP nests by `recipe_id` (single + all share one shape).

## Deferred (need other subsystems / LabVIEW)
- **Cross-reference validation** (variables / instances / `sequencer.list_test_classes`)
  — Variable Engine + Sequencer don't exist yet; warn-only stub.
- **LabVIEW Test Sequencer `Execute` VIs** (the 15 handlers) + `event/step-completed`
  — the user's desk work against the documented contract; Python serves
  `recipe.fetch` and the events land via the existing `runs`/`logs` subscribers.
- run-start `required_role` enforcement (run-start is LabVIEW-side).

## Manual
```pwsh
cd backend; python run.py    # admin/admin -> super_admin (RECIPE.*)
# create -> publish -> get -> export -> diff -> validate via /recipes/* (see RECIPE §11)
```
