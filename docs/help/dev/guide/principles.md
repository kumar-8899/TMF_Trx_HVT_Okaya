# Principles

The full constitution is [Principles (full document)](help:dev-principles) — decisions there are
**locked**; re-open them only by editing that file. This page is the short version: what each principle
means for **you, building an app**.

| Principle | What it means when you build |
|---|---|
| **The docs are the contract** | Decide → update the doc → build against the doc, never from memory. A change without a doc change is unfinished. |
| **The controller is a contract; LabVIEW and Python are variants** | Never assume which one runs. Talk to it only over MQTT ops (`run.start`, `variable.read`, `instrument.call`…). |
| **Python is the only web edge** | The frontend never speaks MQTT. New data for a screen = a backend route, not a broker subscription. |
| **A module is a contract; a variant is an implementation** | Vary behaviour by choosing a variant or editing config — never by editing module internals. |
| **Modules depend on core only** | Don't import a sibling module. If you need something shared, it belongs in core (a framework change). |
| **Permissions, not roles** | Gate with `DOMAIN.ACTION`. Roles are just bundles of permissions an admin edits at runtime. |
| **Variation is data, not a code fork** | Recipes, variable maps, config and specs are data. Reach for code only for product-specific behaviour the core step types can't express. |
| **JSON + JSON Schema + `schema_version`** | Anything you persist or configure gets a schema and an `*.example.json`. Live config is gitignored. |
| **Data is RAG-ready by construction** | Persisted records are self-contained with plain-language summaries and stable IDs, append-only where possible — so they can be searched and cited later. |
| **Failures are loud and structured** | A typed diagnostic event plus an RFC-7807 body — never a swallowed exception, never a fake pass. |
| **Testers as we go** | Every module/step type ships a tester and runs standalone. Simulation is per instrument, so a bench can be proven without hardware. |
| **Do not overcomplicate** | Reuse the proven patterns (registry, schema-validated config, step types). Add no machinery without a demonstrated need. |
| **Limits come from the product spec** | Never invent a limit or parameter to make a test pass. |

## Two rules that look contradictory (and how they resolve)

- **Standalone vs shared code** — modules use the **core**, never each other. "Standalone" means *core +
  this one module boots and runs*.
- **Low customisation vs variants** — the only sanctioned variation is *choosing a variant* and *editing
  its config*.

Next: [Ownership boundary](help:dev-guide-ownership) · [Architecture](help:dev-architecture) ·
[Application template](help:dev-template).
