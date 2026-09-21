# Barcode (Config)

Configure the **shape** of the barcode or serial label operators scan or type when
starting a test, and which slice of it is the **recipe id**. This decides what the
Start-test popup shows: a serial-number field (barcode enabled) or a recipe dropdown
(barcode disabled) — never both.

![Barcode — barcode structure and recipe-id extraction](asset:config-barcode)

## The model

A barcode is a fixed **total length**, divided into named **parts** — each part is a
slice at a **start** position and a **length**. One part is marked as the **recipe id**;
its value is used directly as the recipe to run.

Example — an 8-character barcode `INV12345` made of a 3-character model code followed by
a 5-digit serial:

| Part | Start | Length | Value (for `INV12345`) |
|---|---|---|---|
| model | 0 | 3 | `INV` |
| serial | 3 | 5 | `12345` |

Marking **model** as the recipe id means scanning `INV12345` runs the recipe whose id is
`INV`.

## Set it up

1. Turn **Barcode enabled** on (or leave it off if operators should pick a recipe by
   hand instead).
2. Set the **Total length** — every scanned barcode must match this length exactly.
3. **Add part** for each field in the barcode; give it a **Name**, a **Start** (0-based),
   and a **Length**.
4. Mark exactly one part as the **Recipe ID** (the radio button in its row).
5. **Save.**

## What it changes

- **Enabled:** the Start-test popup shows one field, **Serial number** — the operator
  scans or types the full barcode there. The recipe is resolved automatically from the
  part marked Recipe ID (a live preview shows which recipe it resolves to as you type/scan).
  No manual recipe picker is shown.
- **Disabled:** the popup shows a **Recipe** dropdown instead — the operator picks the
  recipe by hand, and no serial number is captured.

A barcode that doesn't match the configured length, or resolves to an empty recipe id, is
rejected with an error — it never silently starts the wrong test.
