import { Table, TableBody, TableCell, TableHead, TableRow } from "@mui/material";

import { EmptyState, Section, StatusChip, statusKind } from "../ui";
import { MONO_STACK } from "../../theme/theme";

export interface ResultRow {
  serial_no?: number; test_name?: string; expected?: any; measured?: any;
  result?: string; cycle_time_ms?: number;
}

/** The live test-result table (one row per `test-result` event). */
export function ResultsTable({ rows, subtitle }: { rows: ResultRow[]; subtitle?: string }) {
  return (
    <Section title="Test results" subtitle={subtitle} bodyPad={0}>
      {rows.length === 0 ? (
        <EmptyState message="No results yet." />
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
            {rows.map((r, i) => (
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
