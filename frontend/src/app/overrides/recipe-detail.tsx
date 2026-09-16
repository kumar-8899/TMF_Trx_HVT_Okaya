/** App screen override: replace the framework recipe detail (view) with the hipot read-only
 * view so viewing a recipe matches the custom editor (TEMPLATE.md §1.3). */
import type { ScreenOverride } from "../registry";
import { HipotRecipeDetail } from "./okaya_hvt/HipotRecipeDetail";

const override: ScreenOverride = { key: "recipe-detail", component: HipotRecipeDetail };
export default override;
