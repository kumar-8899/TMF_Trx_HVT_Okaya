---
name: system-blueprint
description: Turn a filled "System Blueprint" Excel workbook into a test application's canonical I/O artifacts — the controller-side variable map (app/<name>/maps/<station>.json) plus an Instruments setup checklist and a composite-driver spec. Use when a developer has (or wants to start) a spreadsheet describing an application's instruments and input/output signals with their addresses, wants to generate/scaffold an app's variable map from it, or hands over a fuller version of that sheet mid-project to update an app already built from an earlier partial one. It defines the SYSTEM (topology), never the tests. Related to new-test-app but runs on its own timeline — the full sheet often arrives after the app is scaffolded. Do NOT use to author a driver (create-instrument-library), a step type (test-step-authoring), or a whole new app fork (new-test-app).
---

# System Blueprint (define an app's I/O from a spreadsheet)

A **System Blueprint** is an Excel workbook a test engineer fills in to declare ONE
application's I/O system: its **instruments** and every **input/output signal** with the
**address relative to an instrument**. A deterministic generator turns it into the
framework's canonical artifacts, reconciling in place when a fuller sheet arrives later.

Read `docs/SYSTEM_BLUEPRINT.md` (the contract) before running. Key ideas:

- **It defines topology, not tests.** No recipes/step-types. Recipes reference the signal
  names it produces, later.
- **It is authoring input, never runtime data.** The generator emits the same
  `app/<name>/maps/<station>.json` the controller loads — as if hand-authored. The
  workbook itself is never read at runtime.
- **Every row has a stable `tag`.** Assign it once, never change it. It is the reconcile
  key: a fuller sheet UPDATES what exists (fills TBDs, renames by tag, adds new) instead
  of clobbering it.
- **Progressive fill-in.** Blank / `TBD` = not known yet. A signal with no read/write is
  kept PENDING (not emitted) until a later sheet completes it.

## The tool

All work goes through the framework tool (run from `backend/`, so `tools`, `modules`, and
`instrumentlib` resolve):

```
python -m tools.blueprint make-template  <path.xlsx>
python -m tools.blueprint generate --workbook <path.xlsx> --app-name <name> [--root <repo>]
                                   [--prune] [--dry-run]
```

`generate` writes, under `app/<name>/`: `maps/<station>.json`, `maps/.blueprint.lock.json`
(the tag ledger), `docs/INSTRUMENTS.md`, `docs/MULTIPLEXING.md` (if any scan rows), and
`blueprint-report.md`. It exits `2` on blocking validation errors and writes nothing then.

## Workflow

1. **Get the sheet.** If the developer has one, use it. If not, `make-template` a blank
   one and help them fill it (the **Read me** sheet documents every column and the closed
   vocabularies — owners, transports, capability methods — which are surfaced live from
   the framework code). Fill what is known; leave the rest blank or `TBD`.
2. **Sanity-check with `--dry-run`** first: it validates and prints the report without
   writing. Resolve every **Error** (they block); Warnings and Pending are expected on a
   partial sheet.
3. **Generate.** Run without `--dry-run`. Read the report back to the developer:
   Added / Changed / Removed / Pending, and the Multiplexing handoff.
4. **Instruments are DB records.** The map's `instance` names are foreign keys to records
   the operator creates on **Config → Instruments** — the generator cannot create them.
   Walk the developer through `docs/INSTRUMENTS.md`; for standalone/sim runs it also emits
   a paste-ready `controller.json` `instances` block.
5. **Composite drivers (multiplexing).** When a single reader is scanned across points via
   relays, each scan point is an ordinary Signals row on a **composite instrument**; the
   Multiplexing sheet becomes `docs/MULTIPLEXING.md` — the build spec. Hand that to the
   **`create-instrument-library`** skill to build the driver (channel → relay pattern +
   settle, hidden inside the driver). A digital output that only steers the mux is a
   selector element there, **not** a signal.
6. **Later, a fuller sheet.** Re-run `generate` with the same `--app-name`. It reconciles
   by tag: fills TBDs, renames/moves by tag, adds new rows, and **keeps-and-warns** any
   signal dropped from the sheet (it may be referenced by a recipe). Pass `--prune` only
   when the developer confirms a dropped signal should be deleted.

## Relationship to new-test-app

`new-test-app` scaffolds the app tree and (optionally) a starter map. `system-blueprint`
is how that map gets filled/regenerated from a spreadsheet — usually **after** the fork
exists, and repeatedly as the I/O is nailed down. Run it against the fork's root
(`--root`) so it writes into the fork's `app/<name>/`.

## Guardrails

- Never invent instrument capabilities, methods, or addresses — the generator validates
  read/write against the real capability catalog and fails loudly on a wrong method.
- Never hand-edit the generated map to add signals — edit the **sheet** and regenerate, so
  the ledger stays the source of truth. (Framework-owned files, recipes, step types, and
  UI overrides are never touched by this tool.)
- Do not commit the filled `.xlsx` into the framework repo; it belongs to the app (or to
  the engineer). The `.xlsx` is a generated/owned authoring artifact, not a contract.
