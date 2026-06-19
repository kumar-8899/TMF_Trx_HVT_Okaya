import { Box, Typography, useTheme } from "@mui/material";
import { alpha } from "@mui/material/styles";

/** Big, unmistakable final-verdict banner for the operator window. */
export function VerdictBanner({ result }: { result?: string }) {
  const t = useTheme();
  if (!result) return null;
  const r = result.toUpperCase();
  const color =
    r === "PASS" ? t.palette.status.pass :
    r === "FAIL" ? t.palette.status.fail :
    r === "ABORTED" ? t.palette.status.running : t.palette.status.idle;
  return (
    <Box sx={{
      borderRadius: 2, py: 2, px: 3, textAlign: "center",
      bgcolor: alpha(color, 0.16), border: `2px solid ${color}`, color,
    }}>
      <Typography sx={{ fontWeight: 800, letterSpacing: "0.12em", fontSize: 40, lineHeight: 1 }}>{r}</Typography>
    </Box>
  );
}
