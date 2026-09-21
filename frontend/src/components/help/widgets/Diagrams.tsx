/** `tmf:diagram <architecture|boundary|chain|release>` — theme-aware inline SVG diagrams (no chart
 * dependency; they follow the light/dark palette). Kept structural on purpose: numbers and lists live in
 * the generated facts widgets so a diagram never has a count that can rot. */
import { Alert, Box } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import type { ReactNode } from "react";

type Tone = "neutral" | "primary" | "success" | "warning" | "info";

function useInk() {
  const t = useTheme();
  const tone = (k: Tone) => (k === "neutral" ? t.palette.text.secondary : t.palette[k].main);
  return { t, tone, text: t.palette.text.primary, sub: t.palette.text.secondary, line: t.palette.divider, fill: t.palette.action.hover };
}

function NodeBox({ x, y, w, h, title, lines = [], k = "neutral" }:
  { x: number; y: number; w: number; h: number; title: string; lines?: string[]; k?: Tone }) {
  const ink = useInk();
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={8} fill={ink.fill} stroke={ink.tone(k)} strokeWidth={1.5} />
      <text x={x + w / 2} y={y + 20} textAnchor="middle" fontSize={13} fontWeight={700} fill={ink.text}>{title}</text>
      {lines.map((l, i) => (
        <text key={l} x={x + w / 2} y={y + 38 + i * 15} textAnchor="middle" fontSize={11} fill={ink.sub}>{l}</text>
      ))}
    </g>
  );
}

function Arrow({ x1, y1, x2, y2, label, both = false }:
  { x1: number; y1: number; x2: number; y2: number; label?: string; both?: boolean }) {
  const ink = useInk();
  const id = `ah-${x1}-${y1}-${x2}-${y2}`;
  return (
    <g>
      <defs>
        <marker id={id} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill={ink.sub} />
        </marker>
      </defs>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={ink.sub} strokeWidth={1.5}
        markerEnd={`url(#${id})`} markerStart={both ? `url(#${id})` : undefined} />
      {label && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 7} textAnchor="middle" fontSize={10.5} fill={ink.sub}>{label}</text>}
    </g>
  );
}

function Frame({ label, w, h, children }: { label: string; w: number; h: number; children: ReactNode }) {
  return (
    <Box sx={{ my: 2, overflowX: "auto" }}>
      {/* min-width keeps the text legible on a narrow pane: the box scrolls (overflowX) instead of shrinking. */}
      <svg role="img" aria-label={label} viewBox={`0 0 ${w} ${h}`} width="100%"
        style={{ maxWidth: w, minWidth: Math.round(w * 0.85), display: "block" }}>
        {children}
      </svg>
    </Box>
  );
}

function Architecture() {
  return (
    <Frame label="Three tiers: controller, Python backend, React frontend" w={760} h={250}>
      <NodeBox x={10} y={40} w={200} h={90} title="Controller" k="warning"
        lines={["owns test execution + hardware", "LabVIEW  or  Python (controller.kind)", "the app can't tell them apart"]} />
      <NodeBox x={280} y={40} w={200} h={90} title="Python backend" k="primary"
        lines={["the only web edge", "modules · core services · SQLite", "supervises the Python controller"]} />
      <NodeBox x={550} y={40} w={200} h={90} title="React frontend" k="success"
        lines={["talks only to the backend", "REST + WebSocket, never MQTT", "screens · overrides · Help"]} />
      <Arrow x1={212} y1={85} x2={278} y2={85} both label="MQTT" />
      <Arrow x1={482} y1={85} x2={548} y2={85} both label="HTTP + WS" />
      <NodeBox x={280} y={170} w={200} h={60} title="Modules" lines={["runs · recipe · report · health …", "depend on core only"]} />
      <Arrow x1={380} y1={132} x2={380} y2={168} />
      <text x={10} y={170} fontSize={11} fill="currentColor">tmf/{"{station}"}/cmd · query · stream · value · event · diag · status</text>
      <text x={10} y={188} fontSize={11} fill="currentColor">request/reply via payload reply_to + id (MQTT 3.1.1-safe)</text>
    </Frame>
  );
}

function Boundary() {
  return (
    <Frame label="Ownership boundary between the framework and an app fork" w={760} h={270}>
      <NodeBox x={10} y={20} w={330} h={170} title="Framework-owned — read-only in a fork" k="warning"
        lines={["backend/core · backend/instrumentlib", "standard backend/modules/*", "controller/ · frontend/ (except overrides)", "docs/ · deploy/ · tools/ · station.py", "→ change it upstream, cut a release"]} />
      <NodeBox x={420} y={20} w={330} h={170} title="App-owned — yours" k="success"
        lines={["app/<name>/  (steps · maps · recipes · specs)", "instrument_libs/  (copied drivers)", "backend/modules/<app>_*/", "frontend/src/app/overrides/ · labview/App/", "live config: app.json · license.json"]} />
      <Arrow x1={340} y1={105} x2={418} y2={105} label="git merge" />
      <text x={380} y={222} textAnchor="middle" fontSize={12} fill="currentColor">
        git fetch upstream --tags  →  git merge vX.Y.Z   (clean, because the boundary was respected)
      </text>
    </Frame>
  );
}

function Chain() {
  return (
    <Frame label="Build order: driver, variable map, step type, recipe, run" w={760} h={150}>
      {[
        ["Driver", "capabilities"], ["Variable map", "named signals"], ["Step type", "its schema = params"],
        ["Recipe", "params + limits"], ["Run", "verdict from data"],
      ].map(([t, s], i) => (
        <g key={t}>
          <NodeBox x={8 + i * 150} y={30} w={128} h={62} title={t} lines={[s]} k={i === 4 ? "success" : "primary"} />
          {i < 4 && <Arrow x1={138 + i * 150} y1={61} x2={156 + i * 150} y2={61} />}
        </g>
      ))}
      <text x={380} y={125} textAnchor="middle" fontSize={12} fill="currentColor">
        each layer is the CONTRACT for the next — build bottom-up, verify each before the next
      </text>
    </Frame>
  );
}

function Release() {
  return (
    <Frame label="Release flow from a framework change to a fork" w={760} h={200}>
      {[["Doc", "the contract"], ["Red test", "fails first"], ["Code", "make it green"], ["Suites", "backend · controller · frontend"], ["CHANGELOG + tag", "vX.Y.Z"]]
        .map(([t, s], i) => (
          <g key={t}>
            <NodeBox x={8 + i * 150} y={20} w={128} h={62} title={t} lines={[s]} k="warning" />
            {i < 4 && <Arrow x1={138 + i * 150} y1={51} x2={156 + i * 150} y2={51} />}
          </g>
        ))}
      <Arrow x1={670} y1={84} x2={670} y2={118} label="fork" />
      <NodeBox x={470} y={120} w={280} h={62} title="App fork" k="success"
        lines={["git fetch upstream --tags · git merge vX.Y.Z", "config_doctor --apply · re-login"]} />
    </Frame>
  );
}

const DIAGRAMS: Record<string, () => JSX.Element> = { architecture: Architecture, boundary: Boundary, chain: Chain, release: Release };

export function DiagramWidget({ arg }: { arg: string }) {
  const name = arg.trim();
  const D = DIAGRAMS[name];
  if (!D) return <Alert severity="error" sx={{ my: 1 }}>Unknown diagram <code>{name}</code> (have: {Object.keys(DIAGRAMS).join(", ")}).</Alert>;
  return <D />;
}
