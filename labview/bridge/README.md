# LabVIEW Bridge (DQMH) — Phase-0 stub

The single DQMH module that owns the MQTT connection and every topic
(LABVIEW_BRIDGE.md §8). Phase-0 implements the **stub** of §12; the real DAQ +
controller replace its producers later.

## Executable contract

The byte-for-byte wire behaviour this VI must produce is implemented and tested
in Python at [`backend/tools/lv_stub.py`](../../backend/tools/lv_stub.py). Treat
it as the spec: run it, watch `tmf/#` in MQTT Explorer, and make the LabVIEW
output identical. The Python platform cannot tell the two apart — that is the
whole point of the contract (`LABVIEW_BRIDGE.md` §13).

```
python -m tools.lv_stub --station st1 --host 127.0.0.1 --port 1883   # from backend/
```

## What the stub does (LABVIEW_BRIDGE.md §12)

Connect sequence (§8): **set LWT → connect → publish status online (retained) →
subscribe `cmd/+` → start the periodic-status timer.**

| Behaviour | Topic (`tmf/st1/…`) | QoS | Retain | Payload |
|---|---|---|---|---|
| LWT (registered at connect) | `status` | 1 | yes | `{"state":"offline"}` |
| Online + periodic health (~5 s) | `status` | 1 | yes | `{state:"online", ts, uptime_s, publishes, cmd_pending}` |
| Reply to `hello.echo` | response-topic | 1 | no | `{id, ok:true, result:{echoed, station, ts}}` |
| Synthetic AI stream (~10 Hz) | `stream/ai` | 0 | no | `{t, seq, values:{ai0}}` |
| Last-value | `value/vbus_main` | 1 | yes | `{value, ts}` |
| Diagnostics heartbeat | `diag` | 1 | no | `{seq, ts, level, subsystem, message, context, exception}` |

Command reply uses MQTT-5 **response-topic + correlation-data** (echo the
correlation bytes back); the 3.1.1 fallback is the `id` in the payload
(`LABVIEW_BRIDGE.md` §5).

## DQMH mapping (LABVIEW_BRIDGE.md §8)

- One Bridge module owns the MQTT client; internal modules never touch MQTT.
- **Broadcast (1→N) ≡ PUB:** producers (DAQ, controller, safety) broadcast; the
  Bridge is registered and publishes each to the right topic. In the stub the
  producers are the synthetic stream/value/diag loops.
- **Request-and-Wait-for-Reply ≡ cmd/reply:** the Bridge receives on `cmd/+`,
  issues the matching DQMH request to the owning module, waits, and publishes the
  reply with the same correlation data. In the stub, `hello.echo` is answered
  inline.

Suggested MQTT library: a JSON-over-MQTT toolkit with MQTT-5 support; JSON via
JSONtext (matches recipes + the wire). Keep one publish path that is safe to call
from any thread (§13.1).

## DQMH Tester VI

Auto-generated DQMH Tester VI (LABVIEW_BRIDGE.md §8, work-rule 6). Manual
Phase-0 checks:

1. Run the Tester → broker shows `status` retained `online`.
2. From MQTT Explorer publish a `cmd/hello.echo` with a response-topic → a reply
   comes back with the echoed args.
3. `stream/ai` ticks ~10 Hz; `value/vbus_main` shows a retained value.
4. Abort the Tester (ungraceful) → broker auto-publishes the LWT, `status`
   flips `offline`. Confirm Python `/readyz` goes not-ready.

The automated equivalent of (1)–(4) runs in CI against the Python stub
([`backend/tests/test_lv_stub.py`](../../backend/tests/test_lv_stub.py)).

## Build

Build the EXE by hand for now: open the project and use the LabVIEW
**Application Builder** build spec. LabVIEW CI is deferred — when it is wanted,
add a g-cli build script + a self-hosted Windows runner (LabVIEW + g-cli) and a
`labview.yml` workflow (work-rule 5).
