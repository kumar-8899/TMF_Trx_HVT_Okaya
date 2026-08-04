/** Station selector — renders ONLY on a multi-socket PC (MULTI_STATION.md §6). On a
 * single-station system it returns null, so every screen that mounts it stays
 * station-unaware. `allowAll` adds an "All stations" option for filter contexts. */
import { MenuItem, TextField } from "@mui/material";

import { useStations } from "../hooks/useStations";

export function StationPicker({
  value, onChange, allowAll = false, label = "Station", sx,
}: {
  value: string | null;
  onChange: (station: string | null) => void;
  allowAll?: boolean;
  label?: string;
  sx?: object;
}) {
  const { stations, multi } = useStations();
  if (!multi) return null;
  return (
    <TextField select size="small" label={label} sx={{ minWidth: 160, ...sx }}
      value={value ?? (allowAll ? "" : stations[0])}
      onChange={(e) => onChange(e.target.value || null)}
      inputProps={{ "aria-label": "station" }}>
      {allowAll && <MenuItem value=""><em>All stations</em></MenuItem>}
      {stations.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
    </TextField>
  );
}
