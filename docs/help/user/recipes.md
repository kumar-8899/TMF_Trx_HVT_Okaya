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
Each step has an **id**, a **step type**, and the type's own parameters. The step-type
list comes from the **controller's catalog**: the 8 core types (`set_output`,
`measure_and_compare`, `wait`, `group`, `repeat`, `sweep`, `if`, `prompt_operator`)
plus any **application step types** the app ships (its step-type package). The right
pane renders each type's parameters from its schema — number/text/select fields for
scalars; composite parameters (e.g. a `group`'s `steps`) edit as JSON.

- Step **ids must be unique within the recipe**.
- Hover a step in the left rail to **clone** it.
- **Validate** before publishing; errors are listed and the offending steps flagged.
- Limits (min/max) live in the step parameters — they come from the product
  specification, and the sequencer judges results against them.

## Import/export note
The export is a **ZIP bundle** (versioned + hash-verified), not plain JSON. Editing the zip by hand corrupts it. To clone, use **Duplicate**.
