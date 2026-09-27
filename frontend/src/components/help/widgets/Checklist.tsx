/** `tmf:checklist` — a progress checklist authored right in the markdown (one item per line of the
 * block). Ticks persist in this browser only (localStorage; never required for anything). */
import { Box, Checkbox, FormControlLabel, LinearProgress, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";

function keyFor(items: string[]): string {
  let h = 0;
  for (const c of items.join("\n")) h = (h * 31 + c.charCodeAt(0)) | 0;
  return `tmf.help.checklist.${(h >>> 0).toString(36)}`;
}

function load(key: string): boolean[] {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
}

export function ChecklistWidget({ arg }: { arg: string }) {
  const items = arg.split("\n").map((l) => l.replace(/^[-*]\s*(\[.\]\s*)?/, "").trim()).filter(Boolean);
  const key = keyFor(items);
  const [done, setDone] = useState<boolean[]>(() => load(key));
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(done)); } catch { /* private mode: progress just isn't saved */ }
  }, [key, done]);
  const n = items.filter((_, i) => done[i]).length;
  const toggle = (i: number) => setDone((d) => { const c = items.map((_, k) => Boolean(d[k])); c[i] = !c[i]; return c; });

  return (
    <Box sx={{ my: 2, p: 2, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 1 }}>
        <Typography variant="subtitle2">Your progress</Typography>
        <LinearProgress variant="determinate" value={items.length ? (100 * n) / items.length : 0} sx={{ flex: 1, height: 8, borderRadius: 4 }} />
        <Typography variant="caption">{n}/{items.length}</Typography>
      </Stack>
      <Stack>
        {items.map((it, i) => (
          <FormControlLabel key={it} label={<Typography variant="body2" sx={{ textDecoration: done[i] ? "line-through" : "none" }}>{it}</Typography>}
            control={<Checkbox size="small" checked={Boolean(done[i])} onChange={() => toggle(i)} />} />
        ))}
      </Stack>
    </Box>
  );
}
