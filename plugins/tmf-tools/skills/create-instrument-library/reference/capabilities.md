# Capability interfaces (method sets to implement)

Mirror of `Super_Test_App/backend/instrumentlib/interfaces.py`. A library declares
`capabilities=[...]` and implements **every** method of **each** declared capability
(a composite/multi-function instrument mixes in several over one connection). Verify
against that file if unsure (it is the source of truth; `interface_version` bumps on a
breaking change).

Scalar = reachable via the variable engine. Non-scalar = `capability.request` only,
never bound in the variable map.

## Scalar

**power_source** (`IPowerSource`, v1)
- `set_voltage(volts)` · `get_voltage_setpoint() -> volts`
- `measure_voltage() -> volts` · `measure_current() -> amps`
- `set_current_limit(amps)` · `output_enable(on: bool)`

**electronic_load** (`IElectronicLoad`, v1)
- `set_mode(mode)`  mode ∈ "cc"|"cv"|"cr"|"cp"
- `set_setpoint(value)` · `load_enable(on: bool)`
- `measure_voltage() -> volts` · `measure_current() -> amps` · `measure_power() -> watts`

**analog_input** (`IAnalogInput`, v1)  — instrument readbacks, NOT NI-DAQ
- `read_voltage(channel) -> volts`

**digital_input** (`IDigitalInput`, v1)
- `read_digital(channel) -> bool`

**digital_output** (`IDigitalOutput`, v1)
- `write_digital(channel, state: bool)` · `read_digital_setpoint(channel) -> bool`

**temperature** (`ITemperature`, v1)
- `measure_temperature(channel) -> degrees`

**resistance** (`IResistance`, v1)
- `measure_resistance(channel) -> ohms`

**frequency** (`IFrequency`, v1)
- `measure_frequency(channel) -> hz`

## Non-scalar (capability.request only)

**multiplexer** (`Multiplexer`, v1)
- `set_route(channel, bus)` · `open_all()` · `get_routes() -> [{channel, bus}]`

**dso** (`DSO`, v1)
- `configure(**kw)` · `capture() -> WaveformRecord`  (wire shape is an open item —
  defer unless the user specifies it)

## Mandatory base surface (every library, from InstrumentBase)
- `identify() -> str`  — return `*IDN?`/equivalent; set `EXPECTED_IDN` (substring).
- `safe_state()`  — drive to a known-safe state (outputs off).
- `emergency_disable()`  — cut ALL outputs now (platform fans out in parallel).
- sim: `simulated=True` → connect no-op, plausible reads, inspectable writes.

## Errors (import from `instrumentlib`)
`GarbageResponse` (implausible/unparseable read), `DeviceError` (device error queue),
`NotConnected`, `NotSupported`, `CommandTimeout`. Reads that can't be parsed MUST raise,
never return.
