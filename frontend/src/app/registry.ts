/** App screen-override registry (TEMPLATE.md §1 — the frontend app-owned boundary).
 *
 * Some screens (Runs, Recipes, the recipe editor/detail, Maintenance) must look different per
 * application. Instead of editing the framework `screens/*` (which would conflict on every
 * framework upgrade), a fork drops a file under **`frontend/src/app/overrides/`** that
 * default-exports `{ key, component }`. It is auto-registered here and the router uses it in
 * place of the framework default. The framework never needs the fork to edit shared files, so
 * `git merge upstream/<version>` stays clean.
 *
 * Overridable keys: "runs" · "recipes" · "recipe-editor" · "recipe-detail" · "maintenance".
 * The framework ships `overrides/` empty → defaults are used. */
import type { ComponentType } from "react";

export interface ScreenOverride {
  key: string;
  component: ComponentType<any>;
}

// eager glob so overrides register at load; empty dir → {} → all framework defaults.
const modules = import.meta.glob("./overrides/*.tsx", { eager: true }) as Record<
  string, { default?: ScreenOverride }
>;

export const APP_SCREENS: Record<string, ComponentType<any>> = {};
for (const mod of Object.values(modules)) {
  const o = mod.default;
  if (o && o.key && o.component) APP_SCREENS[o.key] = o.component;
}

/** The app override for `key`, or the framework `fallback`. */
export function screen(key: string, fallback: ComponentType<any>): ComponentType<any> {
  return APP_SCREENS[key] ?? fallback;
}
