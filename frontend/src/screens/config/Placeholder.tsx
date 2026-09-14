/** Coming-soon Config sections — keep the cascaded menu complete while the backend
 * sections are built. (This `ConfigShift` is dead: the real one lives in Shift.tsx.) */
import { Box } from "@mui/material";

import { EmptyState, PageHeader, Section } from "../../components/ui";

export function ConfigShift() {
  return (
    <Box>
      <PageHeader title="Shift config" subtitle="Shift schedule & boundaries" />
      <Section><EmptyState message="Shift configuration — coming soon." /></Section>
    </Box>
  );
}
