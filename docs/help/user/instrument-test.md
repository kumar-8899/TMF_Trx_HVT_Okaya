# Instrument Test Bench

Hands-on manual control of a Python-owned instrument — set outputs, read
measurements, toggle the output, and drive a unit to a safe state. It is the in-app
version of bench bring-up: exactly the commands a recipe would issue, run by hand.

Reachable at **Test Bench** in the sidebar. **Restricted to the `super_admin` role** — the
route, the nav entry, and the command endpoint all require it. (The panel also appears inside
the Maintenance Console for super_admins.)

## Pick an instrument
The **Instrument** picker lists exactly the Python-owned instruments configured under
**Config → Instruments** (owner = *python*) — add, edit, or remove them there and they
appear here. Each shows its live state (`connected`, `reconnecting`, `faulted`, …) and a
`sim` tag when simulated. Controls only work on a **connected** unit.

An instrument you just added on the config page shows as **not loaded** until the app is
restarted — Python instruments are opened at startup. Restart to bring it online.

## No maintenance mode needed
Python-owned instruments are driven directly by the app, so the Test Bench does **not**
require maintenance mode — every control is live as soon as the instrument is connected.
(Maintenance mode is a LabVIEW-owned concept and only applies to LabVIEW-owned hardware.)
Access is still restricted to users with the **Maintenance** permission.

## Controls (built from the instrument's capability)
The panel renders itself from the instrument's capability, so every instrument type
shows the right controls with no per-model setup:

- **Readings** — press **Read** for a value; **Auto-poll** refreshes the no-argument
  readings about once a second.
- **Set** — type a value and press **Apply** (units shown on the field).
- **Output / Load** — **On** / **Off** toggle.
- **Mode** (electronic load) — pick `cc` / `cv` / `cr` / `cp` and **Apply**.
- **Safety** — **Safe state** (outputs off, known-safe) and **Emergency disable**
  (cut all outputs now).

## Safety
Every command runs through the same guarded path as automated tests: one command at a
time per instrument, fail-fast if the link is down, a per-command timeout, and an
automatic diagnostics entry. A dropped link never hangs the UI — the command fails and
the instrument reconnects in the background.

> LabVIEW-owned instruments are not driven here — use **Config → Instruments →
> Test connection** to check them.
