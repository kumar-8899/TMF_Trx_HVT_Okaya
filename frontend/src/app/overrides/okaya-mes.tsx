/** App-contributed page (registry.ts "pages"): the MES (Okaya table) screen for the app-owned `okaya_mes`
 * module — a new top-level page under /app/ so no framework-owned route file is edited. */
import HubOutlined from "@mui/icons-material/HubOutlined";

import type { AppPage } from "../registry";
import { OkayaMesPage } from "./okaya_hvt/OkayaMesPage";

export const pages: AppPage[] = [
  {
    path: "/app/okaya-mes",
    navLabel: "MES (Okaya table)",
    navIcon: <HubOutlined />,
    permission: "SYSTEM.SETTINGS",
    component: OkayaMesPage,
  },
];
