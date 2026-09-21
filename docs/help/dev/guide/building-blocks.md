# Building blocks: driver → map → step → recipe

Every test in an app is built from four layers, and **each layer is the contract for the next**. So you
build bottom-up and verify each layer before starting the next.

```tmf:diagram
chain
```

| Layer | Lives in | Contract it defines |
|---|---|---|
| **Instrument driver** | `instrument_libs/` | which capability methods exist (`measure_voltage`, `set_output`…) |
| **Variable map** | `app/<name>/maps/<station>.json` | named signals/actions bound to a driver's capabilities (with scale/clamp/units) |
| **Step type** | core (8 built-in) or `app/<name>/<name>_steps/` | its `schema.json` **is** the parameter list a recipe may set |
| **Recipe** | `app/<name>/recipes/*.json` | ordered `{type, id, params}` steps + limits — pure data |

Rules that save you a day:

- A recipe can only set params a step type declared; a step can only use signals the map defined; the map
  can only bind capabilities the driver has.
- **Generic** tests (drive an output, settle, read, compare a window) use the **core step types — no code**.
  Only **product-specific** logic (non-scalar instruments, custom judgement) needs an app step type.
- The **sequencer computes the verdict** from the step's measurements — a handler never decides pass/fail.
- Every test gets a **spec** (`app/<name>/specs/<test>.md`): the human-readable source of truth; `spec_lint`
  keeps it in sync with the code.
- Use the **`add-bench-test`** skill — it walks this order and verifies at each gate.

## What the framework gives you

Core step types and their parameter schemas (click one):

```tmf:step-types
```

Instrument capabilities a driver can implement:

```tmf:facts
capabilities
```

## What *this* app has right now

Works in a fork too — it reads the running app:

```tmf:live-app
```

Contracts: [Step types](help:dev-step-types) · [Recipe](help:dev-recipe) ·
[Instrument library contract](help:dev-instrument-library-contract) · [Test specs](help:dev-test-specs) ·
[Python controller](help:dev-python-controller).
