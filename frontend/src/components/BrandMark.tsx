import { Box } from "@mui/material";

/** The app logo — an oscilloscope waveform on a navy tile (the framework identity
 * mark). Reused in the shell top-bar and the login page. Self-contained colors so it
 * reads on both light and dark. A fork can still show its own client logo alongside
 * this via Config → App identity (logo_client); this stays the app glyph. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <Box
      component="svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label="app logo"
      sx={{ display: "block", flexShrink: 0 }}
    >
      <rect width="64" height="64" rx="15" fill="#0E2C40" />
      <path
        d="M7 39 H19 L25 21 L33 47 L39 33 H57"
        fill="none"
        stroke="#3DDC84"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Box>
  );
}
