# Maintenance Console

Hands-on hardware operation. **Maintenance mode is owned by the LabVIEW controller** — the web only requests it.

## Enter / exit
- Press **Enter maintenance** (with a reason). The controller accepts or refuses (it refuses while a run is active).
- The mode indicator flips only when the controller confirms.

## What it gates
- **Read** variables any time.
- **Write** variables and run **disruptive** health checks **only while maintenance is on**.

## If it won't turn on
- The controller must be online and answer the request.
- You need the **HEALTH.MAINTENANCE** permission.
- See Troubleshooting for the MQTT details.

## Calibration (analog inputs and outputs)
Needs the **MAINTENANCE.CALIBRATE** permission (the *maintenance* role and *super_admin* have it).
Use it when a reference meter shows an analog channel has drifted. Nothing in the shipped
configuration is edited — your calibration is stored separately, and **Reset to factory** removes it.

1. **Pick the signal** (and the station, on a multi-socket PC). A ✓ marks one already calibrated.
2. **Analog input:** apply a known stimulus, press **Capture raw reading**, type what the reference
   meter shows, press **Add point**.
   **Analog output:** enter a raw value, press **Drive output** (needs maintenance mode on), type what
   the meter measures, press **Add point**.
3. Add **two or more points at clearly different values**. The fitted gain, offset and the largest
   error show live; remove any bad point with the bin icon.
4. **Apply calibration.** It takes effect immediately — no restart. If a test is running, the
   screen says the change is *saved* and applies after the run.

If the stored calibration file is damaged the station falls back to the factory scale and logs an
error — it never silently runs half-calibrated.

## Instrument test bench (super_admin)
For `super_admin`, this page also embeds a hands-on panel for **Python-owned instruments** —
set outputs, read measurements, toggle the output, and drive a unit to a safe state. It's the
in-app version of bench bring-up: exactly the commands a recipe would issue, run by hand.

Python-owned instruments are driven directly by the app, so this panel does **not** need
maintenance mode — every control is live as soon as the instrument is connected (maintenance
mode above is a LabVIEW-owned concept and only applies to LabVIEW-owned hardware).

- **Pick an instrument** — the picker lists exactly the Python-owned instruments configured
  under **Config → Instruments** (owner = *python*). Each shows its live state (`connected`,
  `reconnecting`, `faulted`, …) and a `sim` tag when simulated. Controls only work on a
  **connected** unit. An instrument you just added shows as **not loaded** until the app
  restarts — Python instruments open at startup.
- **Controls** render from the instrument's own capability, so every instrument type shows the
  right controls with no per-model setup: **Read** / **Auto-poll** for readings, **Set** +
  **Apply** for outputs, an **On/Off** toggle, **Mode** (`cc`/`cv`/`cr`/`cp` on an electronic
  load), and **Safe state** / **Emergency disable** for safety.
- Every command runs through the same guarded path as automated tests: one at a time per
  instrument, fail-fast if the link is down, a per-command timeout, and an automatic
  diagnostics entry.

> LabVIEW-owned instruments are not driven here — use **Config → Instruments → Test
> connection** to check them.
