import { Box } from "@mui/material";

import { useBranding } from "../hooks/useBranding";

/** The app glyph — a rounded tile with the branding initial (config-driven,
 * TEMPLATE.md §1: rebrand via app.json, never source). Reused in shell + login. */
export function BrandMark({ size = 28 }: { size?: number }) {
  const { short } = useBranding();
  return (
    <Box
      sx={{
        width: size, height: size, borderRadius: size / 5,
        background: (t) => `linear-gradient(135deg, ${t.palette.primary.light}, ${t.palette.primary.dark})`,
        display: "flex", alignItems: "center", justifyContent: "center",
        color: (t) => t.palette.primary.contrastText,
        fontWeight: 800, fontSize: size * 0.5, flexShrink: 0,
      }}
    >
      {short}
    </Box>
  );
}
