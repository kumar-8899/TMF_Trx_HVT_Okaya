# Test Bench (Runs)

The operator's main testing window. Full-width, side menu hidden so you can focus on the unit under test.

## Start a test
- **Barcode** — scan/type the unit serial. The model and recipe are derived from it (by default, the first characters select the recipe).
- **Select recipe** — pick a recipe directly.

Press **Start**. The controller (LabVIEW) runs the sequence.

## What you see
- **Verdict banner** — large PASS / FAIL / ABORTED on finish.
- **Message line** — current step / status, errors in red.
- **Live results table** — S.No, Test name, Expected, Measured, Result, Cycle time, updated as each test completes.
- **Live values** — key station readings streamed live.
- **Today strip** — pass / fail / yield for today + recent-run dots. Hover a dot to see the **Serial number** (falls back to the run id). Click a dot to load that run's results.

## Abort
Press **Abort** to stop the current run. The verdict shows **ABORTED**.

## Notes
- If a run is blocked by an MES interlock, you'll see a message that the unit did not pass the previous stage.
- Identity (Serial / Model) shows in the header for the active run.
