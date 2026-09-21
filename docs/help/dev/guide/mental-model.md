# Mental model

## Three tiers, two seams

```tmf:diagram
architecture
```

- **Controller** — owns test execution: the sequence, step timing, abort/timeout, safety, hardware. It is
  a **contract with two implementations**: the LabVIEW engine or the standalone Python controller.
  Exactly one is active per PC (`app.json` `controller.kind`); when it is `python` the backend supervises
  it. The rest of the app cannot tell them apart.
- **Python backend** — the app platform and the **only web edge**. A small `core` (database, config,
  auth verification, diagnostics, web shell, streaming) plus **modules**.
- **React frontend** — talks only to the backend (REST + WebSocket), never to the broker.

## The MQTT seam

Topics follow one grammar, `tmf/{station}/{class}/{name}`, with classes `cmd · query · stream · value ·
event · diag · status`. Request/reply is MQTT-3.1.1-safe: the payload carries `reply_to` + `id`. Topics are
derived from the grammar — never stored per variable.

**Debugging starts with MQTT Explorer on `tmf/#`**, not with a stack trace: most "why didn't X happen" is
answered by looking at the topic tree. Every op the Python controller serves is listed under
[Facts & figures](help:dev-guide-facts); the wire reference is [MQTT messages](help:dev-mqtt-messages).

## Modules

A **module is a contract**; a **variant** is an implementation of it. Config + license decide which
modules and variants are active. Modules depend **only on core, never on each other**, and consume
**permissions (`DOMAIN.ACTION`), never roles**. Each must run standalone (core + that module).

```tmf:facts
modules
```

More: [Module framework](help:dev-module-framework) · [Core services](help:dev-core-services) ·
[CORE contract](help:dev-core).

## Data

Everything is JSON with a JSON Schema and a `schema_version`; a `*.example.json` ships and the live file is
gitignored. Persisted records carry a common envelope (`id, type, ts, station, source_version, summary`) so
they are self-contained and future-proof for search. See [Principles](help:dev-guide-principles).

## Where things live

| Question | Look here |
|---|---|
| Which modules loaded, and why one didn't? | `GET /modules/status` |
| Is the station ready / link up? | `GET /readyz` |
| What did the system just do? | Diagnostics + Logs screens, MQTT Explorer `tmf/#` |
| Why did this run fail? | the run's `test-result` rows + `run-aborted` event |
| Bench capture from a customer site | [Remote debugging](help:dev-remote-debug) |
