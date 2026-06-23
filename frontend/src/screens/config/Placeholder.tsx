/** Coming-soon Config sections (Barcode, Shift) — keep the cascaded menu complete
 * while the backend sections are built. */
import { Box } from "@mui/material";

import { EmptyState, PageHeader, Section } from "../../components/ui";

export function ConfigBarcode() {
  return (
    <Box>
      <PageHeader title="Barcode config" subtitle="Acquisition / serial parsing" />
      <Section><EmptyState message="Barcode configuration — coming soon." /></Section>
    </Box>
  );
}

export function ConfigShift() {
  return (
    <Box>
      <PageHeader title="Shift config" subtitle="Shift schedule & boundaries" />
      <Section><EmptyState message="Shift configuration — coming soon." /></Section>
    </Box>
  );
}
