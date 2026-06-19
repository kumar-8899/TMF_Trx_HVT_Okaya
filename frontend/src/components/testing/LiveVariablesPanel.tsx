import { Box, Grid, Typography } from "@mui/material";

import { Section } from "../ui";
import { MONO_STACK } from "../../theme/theme";
import type { ValueFrame } from "../../hooks/useValues";

export interface LiveVariable { name: string; label?: string; unit?: string; format?: string }

/** Format a value with an optional "0.0"-style decimal hint. */
function fmt(v: ValueFrame["value"] | undefined, format?: string): string {
  if (v === undefined || v === null) return "—";
  if (typeof v === "number" && format) {
    const m = /0\.(0+)/.exec(format);
    if (m) return v.toFixed(m[1].length);
  }
  return String(v);
}

/** Continuously-displayed station variables (config-driven). One tile each. */
export function LiveVariablesPanel({
  variables, values,
}: { variables: LiveVariable[]; values: Record<string, ValueFrame> }) {
  if (!variables.length) return null;
  return (
    <Section title="Live values">
      <Grid container spacing={1.5}>
        {variables.map((v) => (
          <Grid item xs={6} sm={4} md={3} key={v.name}>
            <Box sx={{ p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
              <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {v.label || v.name}
              </Typography>
              <Typography sx={{ fontFamily: MONO_STACK, fontSize: 24, fontWeight: 600, lineHeight: 1.2 }}>
                {fmt(values[v.name]?.value, v.format)}
                {v.unit && <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5 }}>{v.unit}</Typography>}
              </Typography>
            </Box>
          </Grid>
        ))}
      </Grid>
    </Section>
  );
}
