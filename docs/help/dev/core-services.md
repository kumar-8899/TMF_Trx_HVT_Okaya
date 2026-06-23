# Core services

The shared platform every module leans on (`core/services/`).

| Service | What it gives |
|---|---|
| `db` / Repository | Append-first record store (SQLite). Records carry the **RAG envelope** `{id,type,ts,station,source_version,summary,data}`. `put/get/query/delete/delete_id`. |
| `diagnostics` | The cross-language spine. `info/warning/error/exception/timed`. Pluggable sinks (stdout, JSONL, **BusDiagSink** → `diag/<subsystem>`). |
| `bridge` (MQTT) | The only link to LabVIEW. `request(op,args)` (cmd + reply), `publish`, `subscribe`, retained `latest`, `serve` (Py-served queries). Topics scoped `tmf/<station>/…`. |
| `config` | Loads `app.json` + `license.json`; drift detection. |
| `licensing` | Entitlement checks for the gate. |
| `web` | FastAPI shell, readiness checks (`/readyz`), router mounting. |
| `auth_verify` | `TokenVerifier` port + `permission_granted` (wildcard-aware). |
| `interlock` | MES gate port (fail-open until MES fills it). |

## The bus in one screen
- **Py → LV**: `cmd/<op>` (request/reply via payload `id` + `reply_to`).
- **LV → Py**: `event/<kind>`, `value/<name>` (retained), `status` (retained + LWT), `diag`, `stream/<sig>` (high-rate, not persisted).
See `LABVIEW_BRIDGE.md` for the full map.

## Records & RAG
Everything durable is an enveloped record so it can later feed retrieval/health. Don't invent ad-hoc tables; use the repo with a `type`.
