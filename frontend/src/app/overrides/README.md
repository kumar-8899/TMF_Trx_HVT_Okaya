# App screen overrides (app-owned — TEMPLATE.md §1)

The framework ships this directory **empty** → every screen uses its framework default.

A **fork** customizes a screen by dropping a `*.tsx` file here that default-exports
`{ key, component }`. `../registry.ts` auto-registers it (eager `import.meta.glob`) and the
router (`src/App.tsx`) renders it in place of the framework screen. The framework never needs
the fork to edit shared files, so `git merge upstream/<version>` stays clean.

## Overridable keys

| key             | framework default        | route(s)                                   |
|-----------------|--------------------------|--------------------------------------------|
| `runs`          | `screens/Runs`           | `/runs`                                     |
| `recipes`       | `screens/Recipes`        | `/recipes`                                  |
| `recipe-editor` | `screens/RecipeEditor`   | `/recipes/new`, `/recipes/:id/edit`        |
| `recipe-detail` | `screens/RecipeDetail`   | `/recipes/:id`                             |
| `maintenance`   | `screens/Maintenance`    | `/maintenance`                             |

## Example (`overrides/runs.tsx`)

```tsx
import type { ScreenOverride } from "../registry";
import { WireFeederRuns } from "./wire_feeder/WireFeederRuns";

const override: ScreenOverride = { key: "runs", component: WireFeederRuns };
export default override;
```

Rules:
- Route wrappers (`RequirePermission` / `RequireRole`) stay in the framework `App.tsx` — an
  override only replaces the inner screen, never the permission gate.
- Put supporting components (gauges, panels) in a subfolder here (e.g. `overrides/wire_feeder/`)
  so one file per key stays the registered entry.
- Reuse the framework API client (`src/api`) and run-stream hooks — don't fork data access.
