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

## Adding a brand-new page

The 5 keys above only let you *replace* an existing screen. To *add* a new top-level page —
one framework `App.tsx`/`Layout.tsx` don't already have a route or nav entry for — export a
named `pages: AppPage[]` from any file here (alongside or instead of a `default` screen
override). Each entry becomes a route (permission-gated the same way built-in routes are) and
a nav-drawer item automatically — no framework file needs editing.

```tsx
// overrides/myAppPages.tsx
import type { AppPage } from "../registry";
import { GaugeBoard } from "./wire_feeder/GaugeBoard";
import { Speed } from "@mui/icons-material";

export const pages: AppPage[] = [
  { path: "/app/gauges", navLabel: "Gauges", navIcon: <Speed />, permission: "TEST.RUN", component: GaugeBoard },
];
```

Rules:
- `path` **must start with `"/app/"`** — reserved for app-contributed pages so they can never
  collide with a framework route added in a later release. A page whose path doesn't start
  with `/app/` (or that's missing `navLabel`/`component`) is skipped with a console warning.
- `permission` is optional (omit to always show, like `Dashboard`). `component` renders full-page
  inside the normal drawer `Layout` — the same as any framework screen.
