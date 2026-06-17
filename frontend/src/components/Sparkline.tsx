import { useTheme } from "@mui/material";

/** Tiny dependency-free sparkline. Scales the series to fit; flat line if all
 * values equal. Used for per-channel DAQ trends. */
export function Sparkline({
  data, width = 120, height = 32, color,
}: { data: number[]; width?: number; height?: number; color?: string }) {
  const t = useTheme();
  const stroke = color ?? t.palette.primary.main;
  if (data.length < 2) {
    return <svg width={width} height={height} aria-hidden />;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const dx = width / (data.length - 1);
  const pts = data
    .map((v, i) => `${(i * dx).toFixed(1)},${(height - ((v - min) / span) * (height - 4) - 2).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline points={pts} fill="none" stroke={stroke} strokeWidth={1.5}
        strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
