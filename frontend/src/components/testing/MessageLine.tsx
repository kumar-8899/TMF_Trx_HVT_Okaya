import { CheckCircleOutline, ErrorOutline } from "@mui/icons-material";
import { Paper, Stack, Typography } from "@mui/material";

/** LabVIEW-style message + status/error line. */
export function MessageLine({ message, error }: { message?: string; error?: string }) {
  return (
    <Paper sx={{ p: 1.5 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase" }}>Message</Typography>
          <Typography variant="body2" noWrap>{message || "System ready. Awaiting command…"}</Typography>
        </Stack>
        <Stack direction="row" spacing={0.75} alignItems="center">
          {error
            ? <><ErrorOutline fontSize="small" color="error" /><Typography variant="body2" color="error">{error}</Typography></>
            : <><CheckCircleOutline fontSize="small" color="success" /><Typography variant="body2" color="success.main">No error</Typography></>}
        </Stack>
      </Stack>
    </Paper>
  );
}
