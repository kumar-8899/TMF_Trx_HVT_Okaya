# Contract — `mes` (MES Interlock)

Cross-station interlock: gate a run on the **previous** stage's result, and
**publish** this stage's result for the **next** stage. The transport is
pluggable (folder shipped; database/XML are phase-2 behind the same seam).
Entitlement key `mes`. Fills the optional `core.interlock` port.

## Two directions
- **Inbound gate** — before testing serial *S*, confirm *S* passed the previous
  stage. Missing or FAIL → block (policy `on_missing: block|allow`).
- **Outbound publish** — on `run-finished`, write *S*'s result (+ identity) so the
  next stage can gate on it.

## The seam (pluggable transport)
`MesProvider` (modules/mes/providers/base.py):
- `check_upstream(serial) -> InterlockResult{allowed, prior_result, detail}`
- `publish_result(serial, result, payload)`
Providers: **folder** (`FolderProvider`), database/xml (future). Selected by
config `provider`; add a type = one subclass + a factory entry.

### Folder transport
Each stage writes `{downstream_dir}/{PASS|FAIL}/{serial}.json`. The next stage's
`upstream_dir` = the previous stage's `downstream_dir`; a unit proceeds only if
`{upstream_dir}/PASS/{serial}.json` exists. Payload: `{ serial, result, stage,
station, model, operator, recipe_id, run_id, written_ts }`.

## Integration
- **Port:** the module registers `core.interlock.check`. `runs.run_start` calls it
  with the resolved serial **before** creating the run; not allowed →
  `InterlockError` → **HTTP 409**. No MES loaded ⇒ port is fail-open (allowed).
- **Publish:** the module subscribes `event/run-finished`, looks up the run record
  for the serial, and publishes downstream (when publish is enabled).

## Config
```jsonc
{ "stage": "st1", "provider": "folder",
  "gate":    { "enabled": false, "on_missing": "block" },
  "publish": { "enabled": false },
  "folder":  { "upstream_dir": "data/mes/upstream", "downstream_dir": "data/mes/downstream" } }
```
Loaded but inactive by default; gate/publish are toggled at runtime from the
**Settings page** (persisted as a `mes_setting` record).

## HTTP surface (gated `SYSTEM.SETTINGS`)
| Method | Path | Behaviour |
|---|---|---|
| GET | `/mes/status` | provider, stage, gate/publish flags, provider detail |
| PUT | `/mes/config` | `{ gate_enabled?, publish_enabled? }` → persist + apply |

## Standalone test
`core + mes + folder transport + :memory: db` — `modules/mes/tester/test_mes.py`
(gate block/allow, FAIL upstream, publish, run-finished publish, runtime toggle).
