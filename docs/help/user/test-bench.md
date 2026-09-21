# Test Bench (Runs)

The operator's main testing window. Full-width, side menu hidden so you can focus on the unit under test.

![Test Bench — the operator run window in its idle state](asset:runs)

## Start a test

What the Start popup shows depends on **Config → Barcode** (see its help page):

- **Barcode enabled** — one **Serial number** field. Scan or type the unit's barcode;
  the recipe is resolved automatically from the barcode part configured as the recipe id.
- **Barcode disabled** — one **Recipe** dropdown. Pick the recipe directly.

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
