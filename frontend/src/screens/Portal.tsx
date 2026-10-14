/** User Portal — the ONE customer-facing documentation surface (replaces the printed manual AND
 * the separate user "Help" page; the context-help drawer on F1 stays).
 *   Manual         the in-app manual (framework user pages + the app's own pages), with screenshots
 *   Library        searchable PDFs: hardware manuals, wiring drawings
 *   Test Sequence  what each step of THIS product's test does — authored per application, shown
 *                  only to PORTAL.SEQUENCE holders. The framework ships a placeholder; a fork supplies
 *                  the view through the screen registry (key "portal-test-sequence").
 * The whole screen is overridable too (key "portal"). The assistant / troubleshooting center joins
 * as a further tab in a later release. */
import { Box, Tab, Tabs } from "@mui/material";
import { useSearchParams } from "react-router-dom";

import { screen } from "../app/registry";
import { useAuth } from "../auth/AuthContext";
import { PortalLibrary } from "../components/portal/PortalLibrary";
import { TestSequence } from "../components/portal/TestSequence";
import { PageHeader } from "../components/ui";
import { Help } from "./Help";

export function Portal() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const showSequence = can("PORTAL.SEQUENCE");
  const asked = params.get("tab");
  const tab = asked === "library" ? "library" : asked === "sequence" && showSequence ? "sequence" : "manual";
  const Sequence = screen("portal-test-sequence", TestSequence);
  return (
    <Box>
      <PageHeader title="User Portal" subtitle="Manual, hardware documents and help for this station" />
      <Tabs value={tab} onChange={(_, v) => setParams({ tab: v })} sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}>
        <Tab value="manual" label="Manual" />
        <Tab value="library" label="Library" />
        {showSequence && <Tab value="sequence" label="Test Sequence" />}
      </Tabs>
      {tab === "manual" ? <Help embedded /> : tab === "library" ? <PortalLibrary /> : <Sequence />}
    </Box>
  );
}
