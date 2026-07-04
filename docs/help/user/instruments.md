# Instruments (Config)

Set up the station's instruments and test their connection. Two kinds of instrument
live here, chosen by **owner**:

- **LabVIEW-owned** — LabVIEW does the device I/O. You capture a **connection
  profile** by picking a **transport** (VISA, Modbus, CAN, NI-DAQmx, Serial, Raw TCP).
- **Python-owned** — backed by an instrument **library** (e.g. the Keysight PSU),
  reached by the app's variable engine. You pick a **library** + fill its connection
  fields.

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
backend** to (re)build it; then it binds its variables and shows *connected*.

Adding a new transport or library type later is a backend/library change — the form
adapts automatically from the transport catalog / library index.
