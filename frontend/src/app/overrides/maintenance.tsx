/** App screen override: replace the framework Maintenance Console with the Okaya HVT
 * bench-specific manual relay + hipot control page (TEMPLATE.md §1.3). */
import type { ScreenOverride } from "../registry";
import { OkayaMaintenance } from "./okaya_hvt/OkayaMaintenance";

const override: ScreenOverride = { key: "maintenance", component: OkayaMaintenance };
export default override;
