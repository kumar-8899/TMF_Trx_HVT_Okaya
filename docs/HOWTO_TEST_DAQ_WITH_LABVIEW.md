# How-To — Test the DAQ Module with LabVIEW

Bring up the full DAQ vertical (broker → LabVIEW Bridge → Python → React UI) and
acquire AI / DI channels and drive DO points from the browser. This is the
hands-on companion to the contracts in
[`contracts/daq.md`](contracts/daq.md) and
[`LABVIEW_BRIDGE.md`](LABVIEW_BRIDGE.md).

---

## TL;DR — where the channel count is set

- **AI / DI (streamed inputs):** set **how many channels to acquire** in the DAQ
  screen, on each stream card. The **`channels`** field (and optional **`rate`**)
  is sent to LabVIEW in the start command
  `daq.{ai,di}.stream.start { rate?, channels? }` (LABVIEW_BRIDGE.md §5.1).
  Blank = let LabVIEW decide.
- **DO (digital outputs):** a DO is **not a stream** — it is an output you *set*.
  Drive it from the **Variables** panel on the same screen (Write), which issues
  `variable.write { name, value }`. There is no "number of DOs" to start; you
  address each output by name.
- **Permanent station inventory** (which channels physically exist, scaling,
  limits, direction) belongs in the **Variable Engine catalog**
  [`labview/variables.json`](../labview/variables.json), read by both sides at
  init. The UI `channels` field is the *runtime* "acquire N now" knob for
  testing; the catalog is the deferred source of truth (see
  [`decisions/0001-no-topic-mapping-window.md`](decisions/0001-no-topic-mapping-window.md)).

---

## 1. What LabVIEW must serve

The DAQ screen calls Python, Python relays to LabVIEW over MQTT. For the buttons
to do anything, the **LabVIEW Bridge must answer these commands** on
`tmf/{station}/cmd/{op}` and reply via the payload `reply_to` + `id`
(LABVIEW_BRIDGE.md §5, §5.1):

| UI action | Command (`op`) | args | ok result |
|---|---|---|---|
| AI/DI **Start** | `daq.ai.stream.start` / `daq.di.stream.start` | `{ rate?, channels? }` | `{ started: true }` |
| AI/DI **Stop** | `daq.ai.stream.stop` / `daq.di.stream.stop` | `{}` | `{ started: false }` |
| Variables **Read** (no retained value) | `variable.read` | `{ name }` | `{ value, ts }` |
| Variables **Write** (drive a DO/setpoint) | `variable.write` | `{ name, value }` | `{ written: true }` |

While a stream is running, LabVIEW publishes one frame per tick on
`tmf/{station}/stream/{ai,di}` at **QoS 0, not retained**:
`{ t, seq, values: { ai0: …, ai1: … } }`. Python keeps the latest frame and fans
it out to the browser WebSocket (latest-wins; dropped frames under load are
expected and correct — LABVIEW_BRIDGE.md §6).

> The Phase-0 stub ([`backend/tools/lv_stub.py`](../backend/tools/lv_stub.py))
> only answers `hello.echo` and emits a synthetic `stream/ai`. It does **not**
> serve `daq.*`, so against the stub the Start button returns **502**
> (`no reply … within timeout`). You need the **real LabVIEW Bridge** serving
> `daq.*` — or an extended stub — to drive the stream from the UI.

---

## 2. Bring the stack up (one terminal each)

1. **Broker** — Mosquitto on `127.0.0.1:1883`.
   ```powershell
   D:\tools\mosquitto\mosquitto.exe -v
   ```
   Verify with MQTT Explorer connected to `127.0.0.1:1883`.

2. **LabVIEW Bridge** — run the DQMH Bridge (or its Tester VI). On connect it
   must: set the LWT → connect → publish `status = online` retained → subscribe
   `cmd/+` → start the periodic status republish (LABVIEW_BRIDGE.md §8). Confirm
   in MQTT Explorer that `tmf/{station}/status` shows retained `{"state":"online"}`.

3. **Python backend**
   ```powershell
   cd D:\Experiment\Super_Test_App\backend
   python run.py
   ```
   `GET http://127.0.0.1:8000/readyz` should return **200** once the bridge link
   is online (it stays **503** until LabVIEW publishes `status = online`).

4. **Frontend**
   ```powershell
   cd D:\Experiment\Super_Test_App\frontend
   npm run dev
   ```
   Open the dev URL, log in (dev: `admin` / `admin`).

The station id must match across all four (`backend/config/app.json` →
`station`; the same id in the LabVIEW Bridge and the `tmf/{station}/…` topics).

---

## 3. Acquire AI / DI channels from the UI

1. Go to the **DAQ** screen.
2. On the **AI stream** card (same for **DI stream**):
   - **channels** — number of channels to acquire, e.g. `4` → LabVIEW returns
     `ai0..ai3` in each frame. Leave blank to let LabVIEW use its default.
   - **rate (Hz)** — optional sample rate; blank = LabVIEW default.
3. Click **Start**. The card chip turns **open**, the WebSocket connects, and
   live frames render (`values` + `seq`). Behind the scenes:
   `POST /instruments/daq/ai/stream/start` with body `{ "channels": 4, "rate": … }`
   → `daq.ai.stream.start`.
4. Click **Stop** to end (`daq.ai.stream.stop`); the chip returns to **stopped**.

> The **Start / Stop** controls and the Variables **Write** box only appear for
> users with the **`TEST.RUN`** permission. Read-only users see the live values
> but no controls.

What "channels" means on the wire: it is passed straight through to LabVIEW as
`channels` in the start args. The semantics (a count `4` ⇒ `ai0..ai3`, vs. an
explicit list) are owned by the LabVIEW DAQ producer — keep both sides agreed.
The UI sends an integer count.

---

## 4. Read inputs / drive outputs (incl. DO) — Variables panel

The **Variables** panel addresses points by **name** (not by count):

- **Read** `name` → `GET /variables/{name}/value`. Returns the retained
  `value/{name}` snapshot if present, else issues `variable.read`.
- **Write** `name` = `value` → `PUT /variables/{name}/value` →
  `variable.write { name, value }`. **This is how you toggle a DO** or push a
  setpoint, e.g. write `do0 = 1`.

Define the names (and, later, scaling/limits/direction) in
[`labview/variables.json`](../labview/variables.json) so the catalog, the UI, and
LabVIEW agree on what `do0`, `vbus_main`, etc. are.

---

## 5. Troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| Start → **502** `no reply … within timeout` | Broker up, but no responder for `daq.*` | Run the real LabVIEW Bridge serving `daq.*` (the Phase-0 stub does not) |
| Start → **503** `bridge not connected` | Python can't reach the broker | Start Mosquitto; check host/port `127.0.0.1:1883` |
| `/readyz` **503** | LabVIEW link not online | Ensure LabVIEW published retained `status = online`; check station id matches |
| WS closes **4409** `stream not running` | Connected to the stream WS before Start | Click Start first; the UI does this automatically |
| Read → **502** `unknown variable` | LabVIEW rejected `variable.read` | Check the name exists in the LabVIEW catalog / `variables.json` |
| No live frames after Start | Frames not arriving on `stream/{signal}` | In MQTT Explorer watch `tmf/{station}/stream/ai`; confirm LabVIEW publishes `{ t, seq, values }` at QoS 0 |

Use **MQTT Explorer** on `tmf/#` throughout — it shows every command, reply,
stream frame, and retained value crossing the seam, which is the fastest way to
tell whether a problem is on the LabVIEW side or the Python side.

---

## 6. Related

- Wire contract & command catalogue: [`LABVIEW_BRIDGE.md`](LABVIEW_BRIDGE.md) §5.1, §6
- Module contract & HTTP surface: [`contracts/daq.md`](contracts/daq.md)
- LabVIEW Bridge stub (executable spec): [`backend/tools/lv_stub.py`](../backend/tools/lv_stub.py) and [`labview/bridge/README.md`](../labview/bridge/README.md)
- Why channel/topic definitions live in the catalog, not a topic map: [`decisions/0001-no-topic-mapping-window.md`](decisions/0001-no-topic-mapping-window.md)
</content>
</invoke>
