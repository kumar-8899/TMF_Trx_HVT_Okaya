# Instruments (Config)

Set up the station's instruments and test their connection. **This page is the single
source of truth for instruments**: nothing in the application — the variable engine,
the test controller, health checks — can reach an instrument (even a *simulated* one)
until it is configured and enabled here. A fresh app starts with none.

Two kinds of instrument live here, chosen by **owner**:

- **LabVIEW-owned** — LabVIEW does the device I/O. You capture a **connection
  profile** by picking a **transport** (VISA, Modbus, CAN, NI-DAQmx, Serial, Raw TCP).
  (Hidden on an app that runs the Python controller.)
- **Python-owned** — backed by an instrument **library** (a driver copied into the
  app's `instrument_libs/`), reached by the app's variable engine. You pick a
  **library** + fill its connection fields. The Library dropdown lists the app's
  copied drivers automatically.

## Add / edit an instrument
1. **Add instrument** → choose the **owner** (fixed after creation), give an **id**
   (lowercase, immutable) and a **label**.
2. LabVIEW-owned → pick a **transport**; Python-owned → pick a **library** (+ a
   **Simulated** toggle).
3. Fill the connection fields (**resource**, etc.) — **these are editable**; the
   **resource preview** shows the address. Save.
4. **Test connection** — LabVIEW-owned asks LabVIEW to open the device
   (**unavailable** when the controller is offline — honest, not a hang);
   Python-owned reports the **live instance state**.
5. **Family / capabilities** feed hardware health checks.

**Python instruments connect at startup.** After adding or editing one, **restart the
backend** to (re)build it; then it binds its variables and shows *connected*. On a
Python-controller app the restart also hands the controller the updated instrument
set — test runs use exactly what this page defines.

Adding a new transport or library type later is a backend/library change — the form
adapts automatically from the transport catalog / library index.
