# Recipes

A recipe is an ordered list of **tests**. Recipes are versioned — publishing changes creates a new version; old versions stay for traceability.

## Browse
Search, filter (active/draft/deprecated), and sort. Count cards summarise the library.

## Per-recipe actions
- **View** — read-only, with version list and **compare** between versions.
- **Edit (new version)** — opens the editor; publishing increments the version (same recipe id).
- **Duplicate** — copies the recipe into a new, **editable recipe id** (use this to clone, e.g. R02 → R04).
- **Deactivate** — marks the recipe **deprecated**.
- **Export** — downloads a `.zip` bundle. **Import** accepts that `.zip` (not hand-edited).

## Recipe fields
Besides Recipe ID and Name, set the **Model** — the DUT type name your company gives this
product. Runs of this recipe tag their reports with the Model (a Report column + filter).

## Authoring
Each test is a `parametric_test` with fixed fields (Test ID, Name, **Test group**, Enabled, Timeout, Retry, On-fail, Safety-critical) and a **Parameter name / value / unit** table.

- **Parameter names must be unique within a test** (validation blocks duplicates). The same name may repeat in another test.
- Hover a test in the left rail to **clone** it (duplicates with an incremented Test ID).
- **Validate** before publishing; errors are listed and the offending tests flagged.

## Import/export note
The export is a **ZIP bundle** (versioned + hash-verified), not plain JSON. Editing the zip by hand corrupts it. To clone, use **Duplicate**.
