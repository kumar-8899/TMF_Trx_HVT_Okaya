# Variable Map (Config)

*Super admin only.* Bind your project's **physical parameters** (cell voltage, coolant
temperature, …) to the **signals** a Python-owned instrument exposes. The variable
engine names those signals, so recipes and analytics reference a **name**, never the
hardware — swapping a vendor is one binding edit and zero recipe changes.

![Variable map — the station's signals and their bindings](asset:config-variables)

## What a binding is
A **variable** maps a name to one instrument's read and/or write method:

- **Read signal** — what a `read` returns (e.g. `measure_voltage`, `measure_temperature`).
- **Write setpoint** — what a `write` drives (e.g. `set_voltage`, `set_current_limit`).
- **Fixed args** — leading arguments the signal needs, e.g. a **channel** number.
- **Units** and optional **scale** / **clamp**: `value = raw × gain + offset`; writes are
  clamped to `[min, max]`.

The list of read/write methods is **driven by the instrument's library** — its declared
capabilities decide what's bindable, so you never type a method name that doesn't exist.
Only numeric scalar signals bind here; toggles, mode enums, multiplexers and scopes are
hands-on controls on the **Test Bench**, not the variable map.

## Add / edit a variable
1. Pick an **instrument** on the left (Python-owned instances built at startup).
2. **Add variable** → give it a **name** (lowercase, e.g. `cell_voltage`).
3. Choose a **Read signal**, a **Write setpoint**, or both; fill any **fixed args**
   (e.g. `channel`). The **Resolves to** line previews the actual call.
4. Optionally set **units**, **gain/offset**, and **clamp min/max**. Save.

Saved bindings **apply live** — no restart needed. Bindings declared in `app.json` show
as **read-only** (`app.json` tag); edit those in the app config file.

If an instrument isn't listed, add it under **Config → Instruments** (owner *Python*,
pick its library) and **restart the backend** so the instance builds — then it appears
here with its capabilities.
