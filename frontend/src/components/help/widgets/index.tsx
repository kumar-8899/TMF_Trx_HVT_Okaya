/** Widget registry for help markdown directives.
 *
 * A page embeds a live widget with a fenced block whose language is `tmf:<name>`; the block body is
 * the widget's argument (plain text, one value or a few words):
 *
 *     ```tmf:facts
 *     modules
 *     ```
 *
 * An unknown name renders a loud, visible error box (never silently nothing) so a typo or a widget
 * removed from the registry is caught the first time the page is opened — and by the catalog test that
 * scans every page for `tmf:` directives. */
import { Alert } from "@mui/material";
import type { ComponentType } from "react";

export interface WidgetProps { arg: string }

export const WIDGETS: Record<string, ComponentType<WidgetProps>> = {};

export function registerWidget(name: string, component: ComponentType<WidgetProps>): void {
  WIDGETS[name] = component;
}

export function HelpWidget({ name, arg }: { name: string; arg: string }) {
  const W = WIDGETS[name];
  if (!W) {
    return <Alert severity="error" sx={{ my: 1 }}>Unknown help widget <code>tmf:{name}</code>.</Alert>;
  }
  return <W arg={arg} />;
}
