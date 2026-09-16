/** App screen override: replace the framework recipe editor with the Okaya HVT hipot
 * AC-withstand recipe form (TEMPLATE.md §1.3). Registered by ../registry.ts. */
import type { ScreenOverride } from "../registry";
import { HipotRecipeEditor } from "./okaya_hvt/HipotRecipeEditor";

const override: ScreenOverride = { key: "recipe-editor", component: HipotRecipeEditor };
export default override;
