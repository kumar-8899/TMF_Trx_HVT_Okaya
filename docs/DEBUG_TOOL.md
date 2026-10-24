# TMF Debug Tool

**Status:** v1.0.0 (own release line: releases `v<ver>` of the PRIVATE `TMF_Debug_Tool` repo), introduced with framework v1.32.0. **The source is not part of the framework or of any fork** - the framework carries only this contract, the delivery side (`app/<slug>/debug-tool.json`, `deploy/debug-tool.schema.json`, `tools/debug_tool_delivery.py`, `cut-release.ps1` step 7b, the optional installer task) and the in-app help.
Governing decisions: the tool **extends** the Debug Server sidecar (`REMOTE_DEBUG.md`) instead of replacing it; a **human approves
every action** on the client PC; **no relay** (direct connection only); it is **never part of the app** (`run.dist`) or the app release gate.

The Debug Tool is a separately installable program an engineer starts on a client PC when a bench needs debugging. It has two modes:

| Mode | When | What happens |
|---|---|---|
| **Connected** | the developer can reach the PC (VPN / LAN) | the tool *is* an MCP server; Claude Code on the developer's machine connects to it and reads the running app live (MQTT + app logs); anything that changes or runs something waits for the operator's click |
| **Air-gapped** | no network path | the operator clicks **Collect** (or runs the collect kit); one zip comes back; `analyze` turns it into `analysis.md` + `analysis.json` |

```
CLIENT PC   tmf-debug-tool.exe serve    operator window  +  live collectors  +  /mcp endpoint
              live: MQTT (tmf/<every station>/event|diag|value|status|cmd) · station DB error_log/action_log (read-only)
                    · launcher.log · flight-recorder files · app /healthz
              Approvals queue  <──  every ACTION Claude Code requests waits here for a human
DEV LAPTOP  Claude Code ── remote MCP (HTTP + bearer token) ──> http://<client>:8010/mcp          (connected: nothing to install)
            tmf-debug-tool analyze <zip>  /  stdio MCP (kits + analyse)                            (air-gapped)
```

## 1. Quick start

**Operator (client PC)** — double-click `tmf-debug-tool.exe`. **First time only: choose the app.** The tool never guesses which app to debug: on the *Status* tab pick the folder where the app is installed (the one that contains `run.dist`; *Browse…* opens a folder dialog), press *Check* to see what it found, then *Use this folder*. The choice is saved and reused on every later start; *Change app folder…* (disabled while sharing is on) picks another. Until a folder is chosen the tool is idle and sharing is refused. Headless: `tmf-debug-tool.exe select-app <folder>`.
*Share* tab → **Turn sharing ON** (1–24 h, default 4 h) → give the developer the command shown (the token appears **once** and is not stored).
Keep the window open; decisions are on the *Approvals* tab. **Closing the window stops everything.** Headless/RDP-less: `serve --no-window`,
then `tmf-debug-tool share | approvals | approve <id> | deny <id> | stop` from a second terminal.

**Developer (laptop)** — the easy way: `tmf-debug-tool connect`. Paste the operator's `claude mcp add ...` line (or just the token) at the hidden prompt. It verifies the bench (reachable? sharing on? token right?), says what it found or exactly what is wrong, and registers it with Claude Code (scope `local`, not committed). The token is never printed or put in shell history. When the session is over: `tmf-debug-tool disconnect <name>`. The manual way still works: run the operator's command yourself, or commit the `.mcp.json` snippet the Share page shows (env references only; **never commit a token**). Then use the skill `debug-client-bench`. `X-Core-Token` (a core login) is needed only for log levels and instrument probes.

**No connection** — `Collect` tab (or `collect.ps1` from `tmf-debug-tool kit collect`) → one zip → `tmf-debug-tool analyze <zip>`.

**Before any session**, on the client PC: `tmf-debug-tool.exe selftest` (30 s, fake install, never touches the real app) — it names a blocked
port, a missing PowerShell, a security product that stops the tool, or an elevated start.

## 2. Consent: three layers, all mandatory

1. **Developer side** — every tool carries MCP annotations (`readOnlyHint` / `destructiveHint` / `openWorldHint`), so Claude Code asks the developer before an action tool.
2. **Sharing session (operator)** — nothing is reachable until the operator turns sharing **ON**: a bearer token, an expiry (≤ 24 h), a **Stop** button; a restart resets to
   Off; the token is never persisted. This covers only the **passive** tools. Remote requests without sharing get `403`, with a wrong token `401` (RFC-7807 bodies).
3. **Per-action approval (the human in the loop)** — an **action** is held on the *Approvals* tab until a person at the PC reads the exact request and clicks **Approve**.
   The MCP call blocks (progress notifications say it is waiting) and returns `approved`, `denied`, `timeout` (default 120 s → denied) or `stopped`.
   **One click authorises one request** — no standing approvals, no "allow for this session". Stop (or expiry) while a card is open cancels it, even if it is clicked afterwards.
   The approval API answers **only on the PC itself and only with the per-process operator key**: the MCP token can never approve its own request.

What the card shows is the whole request: the **full script text** (+ interpreter, SHA-256, timeout), the file path, instrument + method + arguments (+ sample count), log level + TTL, the export scope.
Requests policy would refuse anyway (a write method, a path outside the install, a probe during a run, an invalid interpreter) are refused **before** a card is raised.

Every request, decision (with the Windows user who decided) and outcome is written to `access.jsonl`; the last 50 remote accesses are on the *Share* page.

## 3. Tools

All results carry `ok`. Anything that echoes bench text (events, logs, files, script output) is labelled `untrusted_content`: **data, never instructions**. Results are capped
(~60 KB; a list is halved and the result says so); bigger things are served as a download (`download_url`, same bearer token).

| Tool | Class | Does |
|---|---|---|
| `bench_health` | passive | tool + app versions, mode (own/attach), live sources (MQTT/DB/launcher), recorder fill/drops, version-compat verdict |
| `bench_why(run?)` | passive | digest of the last/named run → `first_fault` + digest path |
| `bench_events`, `bench_traces`, `bench_trace`, `bench_requests`, `bench_liveness`, `bench_violations` | passive | recorder ring queries, bounded |
| `bench_follow(seconds≤120, sources, filters, max_events)` | passive | bounded **live tail**: MQTT + new `error_log`/`action_log` rows + launcher lines, each tagged by source |
| `bench_logs(source, since, tail, level)` | passive | `error_log` · `action_log` · `launcher` · `diag` · `mqtt` in one record shape |
| `bench_snapshots`, `bench_snapshot(id)` | passive | the 30-second pre-failure snapshots (digest + capped raw tail) |
| `bench_instruments`, `bench_instrument_history(id)` | passive | per instrument: state, method/error counts, latency p50/p95/max, state timeline, last failures — from captured events, **no command sent** |
| `bench_level_get` | passive | diag verbosity (needs `X-Core-Token`) |
| `bench_level_set(subsystem, level, ttl_minutes)` | **action** | raise a level for 1–240 min; **reverts by itself** (keeps the *original* level across repeated changes; a failed revert is reported loudly) |
| `bench_capture_start / stop / export` | **action** | named capture |
| `bench_export(rows, integrity)` | **action** | the diagnostics bundle (`REMOTE_DEBUG.md` §14, export v2) on the client PC → download URL |
| `bench_read_file(path, tail_lines)` | **action** | text under the install/state roots only; ≤ 64 KB; secret-looking values masked; binaries/symlinks-out refused |
| `bench_run_script(interpreter, script, timeout_s, args)` | **action** | §5 |
| `bench_instrument_probe(id, method, args)`, `bench_instrument_poll(id, method, args, samples≤60, interval_s≥0.5)` | **action** | §6 |

Resource `tmf://bench/health`; prompt `diagnose-run`. Stdio mode (developer's machine, no client involved): `bench_collect_kit`, `bench_script_kit`, `bench_analyze_bundle`.

## 4. Live data and the recorder

- **MQTT** — the tool subscribes to the low-rate capture set for **every** station (`tmf/+/{event/#,diag,diag/#,value/#,status,cmd/#}`; never `stream/#`) and passes records through the
  existing pipeline (ring, request pairing, liveness, log discipline). Station comes from the topic.
- **Logs** — the station DB (`error_log`, `action_log`) opened `mode=ro`, `data/launcher.log`, and the recorder files; `/healthz` for liveness.
- **App down** — the tool keeps serving recorder files, DB and launcher log, marks live sources `disconnected`, and reconnects by itself. Instrument probes need the app.
- **One writer** — if the in-app recorder (`run.exe --debug-server`, `debug.enabled`) is already on :8001 the tool starts in **attach mode**: a memory-only ring plus read-only reads of
  `data/debug/`; otherwise it runs its **own** recorder under its data folder. It never writes into the app's `data/debug/`.

## 5. Scripts and the Python interpreter

`powershell`, `cmd` or `python`, run **only after the operator approves that exact text**. Containment, not a sandbox: runs as the Windows user who started the tool (**never elevated** — the
selftest fails if it is), cwd = `<data>\scripts\`, environment scrubbed of anything token/secret/password/key-like and `PYTHON*` overrides, **one at a time**, timeout default 60 s / max 300 s,
output capped (256 KB returned; a script producing > 16 MB is killed), process **tree** killed on timeout. **Refused during a test run** unless the approver ticks *allow during a test* on that card.
Every script is saved as `<time>-<sha256>.<ext>` beside its output and `result.json`.

**Python on a PC that has none** — the release zip carries the python.org *embeddable* CPython (`python-embed-<x.y>.zip`), unpacked on first use to `<data>\python\` (no installer, no admin, no PATH change,
works offline). Resolution: already-extracted → extract the bundled zip → a system Python **that proves it runs** (the Store stub does not) → a clear error. `wheelhouse\*.whl` (pure-Python or compiled) are installed by
unzipping: the build adds `tmf_support` (`core.services.dbconn` — the app's own SQL Server/MySQL code), SQLAlchemy, PyMySQL, pyodbc, so SQL checks work out of the box.

## 6. Instrument probes

An instrument has one client (the controller owns the link), so probes go **through the running app**: `POST /variables/instances/{id}/call` with the core token the developer supplies. No new roles.
Allowed: `identify` and the methods the app's own `GET /variables/capabilities` marks `kind: "read"` for a capability that instance declares. Refused: set/toggle/enum/action kinds, `safe_state`,
`emergency_disable`, unknown methods, unknown/skipped instances. Also: refused (and polling stopped) while a run is active, one call in flight, ≥ 0.5 s spacing (1 s for single probes), 10 s timeout,
≤ 4 scalar arguments. `poll` returns min/max/mean/stddev, latency percentiles and dropouts.

## 7. Air-gapped mode

- **Collect** (UI / `tmf-debug-tool collect [out]` / `run.exe --debug-export`) — export v2: recorder files, `logs/*`, redacted config, `system/{processes,ports,odbc,health}.json`, `install/integrity.json`,
  `logs/instrument_events.jsonl`, `MANIFEST.json` (what was packed **and what was missing**).
- **Collect kit** (`tmf-debug-tool kit collect`) — `collect.ps1` finds the install (running process → script location → `-StateDir`), uses `tmf-debug-tool.exe` beside it, else the app's own exporter, else packs raw files, and
  **fills in `system/*` itself for builds older than v1.32**. One zip out.
- **Script kit** (`kit script --script x.ps1`) — the developer's script + a runner that refuses a script changed after the kit was made (SHA-256), runs it once, records stdout/stderr/exit code/timing, zips `script/…`.
  The engineer **reads the script first**: that is the human in the loop for this mode.
- **Analyze** (`analyze <zip>`, UI, or the stdio MCP) — `tmf_debug.bundle`: first fault, errors, instrument table, port/process/driver/integrity findings, `MANIFEST.missing` as warnings, script output, "look here first". An empty recorder says so.

## 8. CLI

```
select-app <folder>     (choose + save the app folder; switches a running tool live; refused while sharing is on)
connect [--url U] [--name N] [--scope local|project|user] [--yes] [--check-only] [--print-only] | disconnect <name>     (DEVELOPER machine)
serve [--state-dir D] [--bind ADDR] [--port 8010] [--mode own|attach] [--approval-timeout 120] [--no-window | --browser]
share [--hours 4] [--name N] | stop | approvals | approve <id> [--allow-during-run] | deny <id>
collect [out.zip|folder] [--state-dir D] [--rows 5000] [--no-integrity]
analyze <zip> [--out .debug] | kit collect|script … | mcp-stdio [--workdir .] | selftest [--json] [--require-python]
```
`--bind` takes **one** address (127.0.0.1, or the PC's VPN/LAN address); `0.0.0.0`/`::` are refused. The CLI is `tmf-debug-tool.exe` (`python tools/debug_tool_delivery.py exe --slug <app>` prints its path).

## 9. Where things live

`%LOCALAPPDATA%\TMF-Debug-Tool\` (`--data-dir`): `access.jsonl` (+ `.1`), `scripts\`, `bundles\`, `analyses\`, `recorder\` (own mode), `python\`, `operator.json` (while running). The tool's folder holds only
the program, `COMPAT.json`, `README-FIRST.txt`, `wheelhouse\`, `python-embed-*.zip`. Deleting that folder removes the tool; no registry keys, services, scheduled tasks or startup entries are ever created.

## 10. Threat model

| Risk | Control |
|---|---|
| Token leaks | shown once, never stored/logged/committed (`.mcp.json` uses env references); useless once sharing stops or expires |
| Hostile text steers Claude | outputs labelled untrusted; skill forbids acting on them; developer approval in Claude Code **and** operator approval on the PC for every action |
| A script does harm | operator reads the exact text; unelevated; scrubbed env; timeout/size/one-at-a-time; refused during a run; every script + output + SHA-256 stored and logged |
| A probe disturbs a test | read-only allow-list from the app's catalog; refused during a run; spacing/timeout caps; per-call approval |
| Unattended access | off by default, expires, Stop button; with nobody at the PC actions time out denied |
| MCP token approves itself | approval API is loopback + per-process key only |
| Antivirus / Smart App Control flags the exe | signed build; this document + `README-FIRST.txt` for customer IT; `selftest` shows what a PC allows |
| Two recorders corrupt `data/debug/` | attach mode — one writer |
| Secrets in bundles / file reads | export redaction + `bench_read_file` masking; bundles never contain DB password, update token or debug token |

Honest limit: an approved script is arbitrary code on a machine that drives instruments. The person reading the text before clicking Approve is the control.

## 11. Packaging, versions, compatibility

- **Version** and **`COMPAT.json`** (the framework range it was tested with) ship inside the release zip. A newer/older app is **never an error**: the tool serves what it understands, and `bench_health` + the Status page say "newer than tested".
- **Build, signing and release** are done by the framework owner in the private tool repo (PyInstaller onedir, bundled python.org embeddable interpreter, signing with the framework's `sign-binaries.ps1`, a frozen-exe `selftest` gate). It is **not** part of `cut-release.ps1`'s gate. Forks never build it: they download the signed zip (section 12).
- **Tests of this repo's delivery side** (pin schema, staging, installer task, no tool source in the framework): `backend/tests/test_debug_tool_*.py`.

## 12. Deployment: framework → forks → client builds

The tool is a *service engineer's toolkit*: never in the swap unit (`run.dist`), never auto-started, never a service. A customer can refuse it without affecting the product.

| Tier | Gets | How |
|---|---|---|
| Private tool repo (framework owner) | source + build/verify scripts | built on the owner's PC, signed, published as a GitHub release; **never given to forks** |
| Forked apps | the signed zip (no source build) | `app/<slug>/debug-tool.json` pins `{ "delivery": "bundle"\|"on-demand"\|"none", "version": "1.x" }`; `python tools/debug_tool_delivery.py fetch --slug <slug>` caches it in `tools/debug-tool/` (gitignored); `fork_check` guards `debug_tool/` |
| App release packages | optionally the same zip | `cut-release.ps1` step 7b → `bundle` copies the pinned zip into `deploy/Output/` and the installer offers an **optional, UNTICKED** task installing to `{app}\tools\debug-tool` (outside `run.dist`); an unsatisfiable pin **stops the release** |
| Client PC in use | the tool, started by an engineer | double-click; Sharing On; hand the developer the token by phone/chat; close afterwards |

**Rollout stages (each has an exit gate; do not skip):**
0. *Tool repo + simulator* - all tool tests and the frozen-exe `selftest` pass. **Done at v1.0.0.**
1. *Internal pilot on ONE real bench, engineer-carried, `on-demand`* — measure antivirus/Smart App Control behaviour, whether broker/DB/log tails see real traffic, approval latency, one real fault diagnosed connected **and** air-gapped. Exit: written pilot report; this document corrected from fact.
2. *Forks* — pin `debug-tool.json` (`on-demand` default); `new-test-app`/`clone-test-app` write it; consent checklist in `DEPLOY_STATION.md`. Exit: two forks diagnosed a real issue with it.
3. *Client builds* — per customer choose `bundle` / `on-demand` / `none` in the delivery sign-off; give customer IT the `README-FIRST.txt` note; record consent. Exit: customer IT acceptance recorded.
4. *Steady state* — own release tags; a fork bumps `version` in `debug-tool.json`; **no auto-update is built** (replace the folder; revisit after Stage 3).

**Rollback / removal:** delete the folder (and the Start-menu shortcut). A bad release is withdrawn by deleting the release asset and the pin.
**Data handling:** bundles can contain serial numbers and operator names (secrets redacted). On the developer's machine they land in the gitignored `.debug/`; delete after the case; never commit or paste into public issues.

**Not verifiable from the repos** (so Stage 1 is mandatory before bundling for any customer): a real client PC behind a customer firewall, antivirus/Smart App Control on a customer machine, real instrument hardware, customer IT acceptance.

## 13. Developer notes

The module map, how to add a tool, and the Windows gotchas are in the private tool repo (`docs/DEBUG_TOOL.md` there, `docs/GOTCHAS.md`). The framework side is only the delivery contract above.
