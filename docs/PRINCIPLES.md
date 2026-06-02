# PRINCIPLES.md — Development Principles & Locked Decisions

This document is the **constitution** for the project. Every other doc
(`LABVIEW_BRIDGE.md`, `CORE.md`, the per-module contracts) sits underneath it,
and every chat or Claude Code session reads the relevant doc and builds against
**the doc**, not against memory. Memory lags; the docs are the contract.

---

## 0. Locked decisions

These are settled. Re-open only by editing this file.

| Decision | Choice | Reference |
|---|---|---|
| **Transport** | MQTT (broker-based). Python is the only web edge; the React frontend is unchanged; LabVIEW ↔ Python over MQTT. Per-station **local broker**; bridge only low-rate topics (`event/#`, `status`, `value/#`) up to a central broker. Keep `stream/#` local. | `LABVIEW_BRIDGE.md` |
| **Control** | **LabVIEW is the controller (Option A).** LabVIEW owns test execution — the sequence, step timing, abort/timeout, and safety. Python hosts the business modules and the web edge. Run-state authority lives on the deterministic side. | `LABVIEW_BRIDGE.md`, `CORE.md` |
| **Config / data format** | **JSON**, validated by **JSON Schema** with a `schema_version` header on every file. (JSONtext on the LabVIEW side; recipes and the MQTT wire are already JSON.) | this doc, §4 |
| **Deployment unit** | **The station.** Each station runs its own LabVIEW + Python + local broker + frontend. A central broker feeds a read-only fleet dashboard. Singleton = one station with no bridge. | `LABVIEW_BRIDGE.md` |

---

## 1. Modular product architecture

The application is a set of **modules** (Auth, Analytics, Licensing, Action &
Error Logs, Recipe, Report, …) over a small shared **core**. This is the
driver-registry and recipe-step patterns already in the codebase, raised to the
level of product features.

- A **module is a contract** — the operations it exposes and the events it emits.
- A **variant is an implementation** of that contract (Auth: local-DB / LDAP / SSO; Report: PDF / HTML / MES-only).
- **Config + license decide what is active.** A JSON manifest names the module, its chosen variant, its core dependencies, and its entitlement key. The core discovers registered modules at startup and activates the ones config selects and the license permits.

```
        ┌── config (which variant) ──┐   ┌── license (is it allowed) ──┐
        ▼                             ▼   ▼
  ┌─────────────────── module activation gate ───────────────────┐
  │  Auth(v=local) · Analytics · Licensing · Logs · Recipe · …    │  ← contracts; one variant each
  └───────────────────────────┬──────────────────────────────────┘
                              ▼  depends ONLY on core, never on siblings
  ┌───────────────────────────────────────────────────────────────┐
  │  CORE:  db · MQTT-bridge client · config/schema · token verify  │
  │         · diagnostics emit · web shell + RFC-7807 errors        │
  └───────────────────────────────────────────────────────────────┘
```

Two principles that look like they conflict, and the rule that resolves each:

- **Standalone vs shared code.** Modules depend on the **core**, never on each other. "Standalone" means *core + this one module boots and runs*. Auth never imports Analytics, but both use the core's database layer. No duplication, no sibling coupling.
- **Low customization vs variants.** The only sanctioned ways to vary a module are **choosing a variant** and **editing its config** — never editing module internals. Variation is data, not a code fork.

A module MUST be runnable on its own (core + that module), because that is what
makes "build a tester as we go" tractable.

---

## 2. The core (shared layer)

Small and stable. Everything else depends on it; it depends on nothing else.

- Database access (pool, migrations, base repository).
- MQTT bridge client (the Python side of `LABVIEW_BRIDGE.md`).
- Config + JSON-Schema loader.
- Bearer-token **verification** (the Auth *module* issues tokens; *verifying* them is a core service every module uses).
- Diagnostics emit (the bus from `LOGGING.md`).
- Web-app shell: routing, middleware, RFC-7807 error bodies.
- The module framework itself: registry/discovery, manifest schema, activation gate, lifecycle hooks (`init` / `start` / `stop` / `health`).

On the LabVIEW side, the **HAL** is the hardware-side embodiment of this same
data-driven, plug-and-play idea (catalog + instances + capability services).

---

## 3. Product & licensing

Treat this as a product; features are gated by the purchased plan.

- A **plan → entitlements** mapping is **data**: which modules, which variants, which feature flags, what limits (e.g. max stations, max users).
- The core consults entitlements **at activation**; the frontend **reflects** them; the API **enforces** them independently. Never trust the frontend.
- **Licensing loads first** — it is what the activation gate reads. (It may start as an "everything on" stub and be hardened later.)

---

## 4. Data-driven (JSON)

- Functionality is configured by JSON config files validated by **JSON Schema**, each with a `schema_version` header.
- An `*.example.json` ships alongside; the live file is gitignored and copied from the example on first run (the existing TOML convention, in JSON).
- Wire shapes and config shapes follow the stability rules in `DATA_TRANSFER.md` §6: field names stable, numbers in their declared form, enums as strings, optional fields explicitly absent/null, lists always present.

---

## 5. Data is RAG-ready by construction

AI features are future; design for them today and **build none of them now**.
Same logic as writing the diagnostics shape down before the viewer existed:
cheap discipline now, expensive retrofit avoided later. No vector store, no
embeddings today.

- **Common metadata envelope.** Every persisted record is JSON carrying `id`, `type`, `ts`, `station`, source version, and a **human-readable summary/message** — the uniform hook a future ingestion pipeline embeds and filters on.
- **Self-contained records.** Enough context travels with each record to understand it without reading its neighbours (the `LOGGING.md` §6 rule, applied everywhere).
- **Natural language alongside codes.** Error explanations, step descriptions, recipe metadata in plain words, not just enums — so content embeds and retrieves meaningfully.
- **Stable IDs + provenance everywhere.** `run_id`, `recipe_id` + version, station, operator, timestamp — so retrieval can filter and a future answer can cite its source.
- **The durable stores ARE the corpus.** Versioned recipes, run records, the diagnostics JSONL sink, the action/error logs. Keep raw structured records, **append-only** where possible; never let data collapse into a rendered-only report that throws structure away.
- **Reserve a `Knowledge` module slot** that plugs into the same module framework and ingests this corpus when wanted — designed-for today, built later.

---

## 6. How we build

- **Project docs are the single source of truth** across chats and across the Claude Code handoff. Decide in a chat → crystallise into a doc → build against the doc.
- **Design vs build split.** Architecture, contracts, scaffolding, and these docs are produced in the design chat. Implementation, testers, and the build run in Claude Code against the real repo.
- **Phased, one module at a time.** Per module: contract → implement + tester → verify standalone → plug into the activation gate → next.
- **Testers as we go.** DQMH auto-generated Tester VIs on the LabVIEW side; pytest + a smoke harness on Python. A module is testable because it is independently runnable (§1).
- **Debug-first** (matters because the owner is graphical-first, not text-first):
  - MQTT Explorer (or any MQTT GUI) on `tmf/#` is the **live graphical traffic tap** — most "why didn't X happen" is answered by looking at the topic tree, not a stack trace.
  - The **Diagnostics Bus** is the cross-language spine: LabVIEW and Python emit the same event shape, so a bug across the MQTT seam is one timeline.
  - Failures are **loud and structured** — a typed, categorised diagnostic event plus an RFC-7807 body — never a bare exception to decode.
- **Build-ready from day one.** PyInstaller sidecar + LabVIEW built EXE + Tauri shell + installer, in CI, building from the first commit. (Already sketched in the packaging notes.)
- **Do not overcomplicate.** The module system reuses patterns already proven here (driver registry, recipe-step library, schema-validated config). Variation is data. Add no machinery without a demonstrated need.

---

## Build order

0. **Core walking skeleton** — boots, loads one dummy module, runs its tester, one MQTT round-trip + one stream + one retained value + LWT, *and builds the installer*. End to end.
1. **DAQ / stream + controller vertical** — first real slice; proves the transport and the LabVIEW-as-controller path; highest-risk integration, done early.
2. **Business modules in dependency order** — Auth → Action & Error Logs → Recipe → Report / Analytics → harden Licensing.
