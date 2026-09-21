/** User Portal — the customer-facing support surface that replaces the printed software manual.
 *   Manual   the in-app manual (framework user pages + the app's own pages), with screenshots
 *   Library  searchable PDFs: hardware manuals, wiring drawings
 * The assistant / troubleshooting center joins as a third tab in a later release. */
import { Box, Tab, Tabs } from "@mui/material";
import { useSearchParams } from "react-router-dom";

import { PortalLibrary } from "../components/portal/PortalLibrary";
import { PageHeader } from "../components/ui";
import { Help } from "./Help";

export function Portal() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "library" ? "library" : "manual";
  return (
    <Box>
      <PageHeader title="User Portal" subtitle="Manual, hardware documents and help for this station" />
      <Tabs value={tab} onChange={(_, v) => setParams({ tab: v })} sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}>
        <Tab value="manual" label="Manual" />
        <Tab value="library" label="Library" />
      </Tabs>
      {tab === "manual" ? <Help embedded /> : <PortalLibrary />}
    </Box>
  );
}
