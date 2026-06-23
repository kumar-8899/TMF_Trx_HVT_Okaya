# Glossary

- **Recipe** — an ordered list of tests run against a unit; versioned.
- **Run** — one execution of a recipe against a unit (identified by serial).
- **Test Bench** — the operator window where runs are started and watched.
- **Verdict** — the run result: PASS / FAIL / ABORTED.
- **FPY** — First-Pass Yield: fraction passing on the first attempt.
- **Cycle time** — time taken by a test / run.
- **MTBF** — Mean Time Between Failures (health trend metric).
- **Flaky** — a check that oscillates pass↔fail (often a loose connection).
- **MES interlock** — cross-station gate/publish so a unit flows stage to stage.
- **Maintenance mode** — a controller-owned state allowing disruptive checks + writes.
- **Transport** — how an instrument connects (VISA, Modbus, CAN, NI-DAQmx, …).
- **Bridge** — the MQTT link between the web/Python app and the LabVIEW controller.
- **Role / Permission** — your role grants a set of permissions; the API enforces them.
- **super_admin** — the protected root account; full access, cannot be deleted.
