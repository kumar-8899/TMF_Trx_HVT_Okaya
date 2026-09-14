import { useState } from "react";
import {
  FormControlLabel, Switch, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";

import { EmptyState, Section, StatusChip, statusKind } from "../ui";
import { MONO_STACK } from "../../theme/theme";

export interface ResultRow {
  serial_no?: number; test_name?: string; expected?: any; measured?: any;
  result?: string; cycle_time_ms?: number;
}

/** The live test-result table (one row per `test-result` event).
 *
 * Setup/actuation measurements — status "INFO" (no limits/context, not pass/fail; e.g.
 * `set_output` recording the value it wrote for traceability) — are hidden by default so
 * the operator sees only graded PASS/FAIL rows, matching what this table exists to show.
 * "Show setup steps" reveals them without losing anything: `rows` is always the full,
 * untruncated stream this component receives — nothing is discarded here, so persistence
 * / report export (which read the same underlying record, not this component's state)
 * are completely unaffected either way. This is display-only. */
export function ResultsTable({ rows, subtitle }: { rows: ResultRow[]; subtitle?: string }) {
  const [showInfo, setShowInfo] = useState(false);
  const hiddenCount = rows.filter((r) => r.result === "INFO").length;
  const visible = showInfo ? rows : rows.filter((r) => r.result !== "INFO");

  return (
    <Section
      title="Test results"
      subtitle={subtitle}
      bodyPad={0}
      actions={hiddenCount > 0 && (
        <FormControlLabel
          sx={{ color: "inherit", m: 0 }}
          control={<Switch size="small" checked={showInfo}
            onChange={(e) => setShowInfo(e.target.checked)} />}
          label={
            <Typography variant="caption" sx={{ color: "inherit" }}>
              {showInfo ? "Showing setup steps" : `Show setup steps (${hiddenCount} hidden)`}
            </Typography>
          }
        />
      )}
    >
      {visible.length === 0 ? (
        <EmptyState message={
          rows.length === 0
            ? "No results yet."
            : `No graded results yet (${rows.length} setup step${rows.length === 1 ? "" : "s"} recorded).`
        } />
      ) : (
        <Table stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 64 }}>S.No</TableCell>
              <TableCell>Test name</TableCell>
              <TableCell align="right">Expected</TableCell>
              <TableCell align="right">Measured</TableCell>
              <TableCell>Result</TableCell>
              <TableCell align="right">Cycle time</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {visible.map((r, i) => (
              <TableRow key={i}>
                <TableCell sx={{ fontFamily: MONO_STACK }}>{r.serial_no ?? i + 1}</TableCell>
                <TableCell>{r.test_name}</TableCell>
                <TableCell align="right" sx={{ fontFamily: MONO_STACK }}>{String(r.expected ?? "")}</TableCell>
                <TableCell align="right" sx={{ fontFamily: MONO_STACK }}>{String(r.measured ?? "")}</TableCell>
                <TableCell>{r.result ? <StatusChip label={r.result} kind={statusKind(r.result)} /> : "—"}</TableCell>
                <TableCell align="right" sx={{ fontFamily: MONO_STACK }}>{r.cycle_time_ms != null ? `${r.cycle_time_ms} ms` : ""}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Section>
  );
}
