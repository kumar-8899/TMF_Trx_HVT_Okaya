/** App screen-override + page registry (TEMPLATE.md §1 — the frontend app-owned boundary).
 *
 * Some screens (Runs, Recipes, the recipe editor/detail, Maintenance) must look different per
 * application. Instead of editing the framework `screens/*` (which would conflict on every
 * framework upgrade), a fork drops a file under **`frontend/src/app/overrides/`** that
 * default-exports `{ key, component }`. It is auto-registered here and the router uses it in
 * place of the framework default. The framework never needs the fork to edit shared files, so
 * `git merge upstream/<version>` stays clean.
 *
 * Overridable keys: "runs" · "recipes" · "recipe-editor" · "recipe-detail" · "maintenance".
 * The framework ships `overrides/` empty → defaults are used.
 *
 * The same directory also lets a fork ADD a brand-new top-level page — something the 5 fixed
 * override keys above can't do — without editing framework-owned `App.tsx` / `Layout.tsx`
 * (issue: a fork needing a new page had no choice but to patch those files, which breaks the
 * clean-merge boundary). An override module exports a named `pages: AppPage[]` alongside (or
 * instead of) its `default` screen override; each entry becomes a route + nav item, gated the
 * same way built-in routes are. `path` MUST start with `"/app/"` — reserved for app-contributed
 * pages so they can never collide with a framework route added in a later release. */
import type { ComponentType, ReactNode } from "react";

export interface ScreenOverride {
  key: string;
  component: ComponentType<any>;
}

export interface AppPage {
  /** Route path. MUST start with "/app/" (reserved for app-contributed pages). */
  path: string;
  /** Label shown in the nav drawer. */
  navLabel: string;
  /** Icon shown in the nav drawer; an MUI icon element, e.g. <ScienceOutlined />. Optional. */
  navIcon?: ReactNode;
  /** Permission required to see the nav entry/route (RequirePermission). Omit to always show. */
  permission?: string;
  component: ComponentType<any>;
}

type OverrideModule = { default?: ScreenOverride; pages?: AppPage[] };

/** Pure so it's unit-testable without Vite's `import.meta.glob` — see registry.test.ts. */
export function buildRegistry(modules: Record<string, OverrideModule>): {
  screens: Record<string, ComponentType<any>>;
  pages: AppPage[];
} {
  const screens: Record<string, ComponentType<any>> = {};
  const pages: AppPage[] = [];
  for (const mod of Object.values(modules)) {
    const o = mod.default;
    if (o && o.key && o.component) screens[o.key] = o.component;

    for (const p of mod.pages ?? []) {
      if (p && typeof p.path === "string" && p.path.startsWith("/app/") && p.navLabel && p.component) {
        pages.push(p);
      } else {
        // eslint-disable-next-line no-console -- surfaces a fork's misconfigured page at load
        console.warn(
          '[app/registry] ignoring invalid app page (needs path starting with "/app/", navLabel, component):',
          p,
        );
      }
    }
  }
  return { screens, pages };
}

// eager glob so overrides register at load; empty dir → {} → all framework defaults, no app pages.
const modules = import.meta.glob("./overrides/*.tsx", { eager: true }) as Record<string, OverrideModule>;
const built = buildRegistry(modules);

export const APP_SCREENS: Record<string, ComponentType<any>> = built.screens;
/** App-contributed top-level pages (path always starts with "/app/"). Empty in the framework. */
export const APP_PAGES: AppPage[] = built.pages;

/** The app override for `key`, or the framework `fallback`. */
export function screen(key: string, fallback: ComponentType<any>): ComponentType<any> {
  return APP_SCREENS[key] ?? fallback;
}
