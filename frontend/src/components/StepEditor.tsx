import {
  Box, Button, Checkbox, FormControlLabel, IconButton, MenuItem, Paper, Select, Stack,
  TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api/client";

export interface StepType { type_id: string; composite: boolean }
export interface Step {
  step_id: string;
  step_type: string;
  name?: string;
  enabled?: boolean;
  params: Record<string, any>;
}

const STEP_LIST_KEYS = ["inner_steps", "then_steps", "else_steps"];
const isStepListProp = (key: string, prop: any) =>
  STEP_LIST_KEYS.includes(key) || (prop?.type === "array" && prop?.items?.["x-steps"]);

// ---- SchemaForm: render params inputs from a $ref-resolved JSON Schema --------

export function SchemaForm({ schema, value, onChange, types }: {
  schema: any; value: Record<string, any>; onChange: (v: Record<string, any>) => void; types: StepType[];
}) {
  const props: Record<string, any> = schema?.properties ?? {};
  const required: string[] = schema?.required ?? [];
  const set = (k: string, v: any) => onChange({ ...value, [k]: v });

  return (
    <Stack spacing={1.5}>
      {Object.entries(props).map(([key, prop]) => (
        <Field key={key} name={key} prop={prop} req={required.includes(key)}
          value={value?.[key]} onChange={(v) => set(key, v)} types={types} />
      ))}
    </Stack>
  );
}

function Field({ name, prop, req, value, onChange, types }: {
  name: string; prop: any; req: boolean; value: any; onChange: (v: any) => void; types: StepType[];
}) {
  const label = req ? `${name} *` : name;

  if (isStepListProp(name, prop)) {
    return (
      <Box sx={{ pl: 1, borderLeft: "2px solid #ddd" }}>
        <Typography variant="caption">{name}</Typography>
        <StepList steps={value ?? []} onChange={onChange} types={types} />
      </Box>
    );
  }
  if (Array.isArray(prop?.enum)) {
    return (
      <Select size="small" displayEmpty value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <MenuItem value=""><em>{label}</em></MenuItem>
        {prop.enum.map((o: any) => <MenuItem key={String(o)} value={o}>{String(o)}</MenuItem>)}
      </Select>
    );
  }
  if (prop?.type === "boolean") {
    return <FormControlLabel control={
      <Checkbox checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />} label={label} />;
  }
  if (prop?.type === "number" || prop?.type === "integer") {
    return <TextField size="small" type="number" label={label} value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />;
  }
  if (prop?.type === "object" && prop.properties) {
    return (
      <Box sx={{ pl: 1, borderLeft: "2px solid #eee" }}>
        <Typography variant="caption">{label}</Typography>
        <SchemaForm schema={prop} value={value ?? {}} onChange={onChange} types={types} />
      </Box>
    );
  }
  // string, oneOf (value_ref / compare.source), or unknown -> free text (numbers coerced)
  return <TextField size="small" label={label} value={value ?? ""}
    onChange={(e) => {
      const t = e.target.value;
      const n = Number(t);
      onChange(t !== "" && !Number.isNaN(n) && /^-?\d/.test(t) ? n : t);
    }} />;
}

// ---- StepList + StepCard -----------------------------------------------------

export function StepList({ steps, onChange, types }: {
  steps: Step[]; onChange: (s: Step[]) => void; types: StepType[];
}) {
  const add = (type_id: string) =>
    onChange([...steps, { step_id: `${type_id}_${steps.length + 1}`, step_type: type_id, params: {} }]);
  const update = (i: number, s: Step) => onChange(steps.map((x, j) => (j === i ? s : x)));
  const remove = (i: number) => onChange(steps.filter((_, j) => j !== i));
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= steps.length) return;
    const copy = [...steps];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };

  return (
    <Stack spacing={1}>
      {steps.map((s, i) => (
        <StepCard key={i} step={s} types={types}
          onChange={(s2) => update(i, s2)} onRemove={() => remove(i)}
          onUp={() => move(i, -1)} onDown={() => move(i, 1)} />
      ))}
      <AddStep types={types} onAdd={add} />
    </Stack>
  );
}

function AddStep({ types, onAdd }: { types: StepType[]; onAdd: (t: string) => void }) {
  const [pick, setPick] = useState("");
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <Select size="small" displayEmpty value={pick} onChange={(e) => setPick(e.target.value)}
        sx={{ minWidth: 200 }} inputProps={{ "aria-label": "step type" }}>
        <MenuItem value=""><em>add step…</em></MenuItem>
        {types.map((t) => <MenuItem key={t.type_id} value={t.type_id}>{t.type_id}</MenuItem>)}
      </Select>
      <Button size="small" variant="outlined" disabled={!pick}
        onClick={() => { onAdd(pick); setPick(""); }}>Add</Button>
    </Stack>
  );
}

function StepCard({ step, types, onChange, onRemove, onUp, onDown }: {
  step: Step; types: StepType[]; onChange: (s: Step) => void;
  onRemove: () => void; onUp: () => void; onDown: () => void;
}) {
  const [schema, setSchema] = useState<any>(null);
  useEffect(() => {
    api.get(`/recipes/step-types/${step.step_type}/schema?resolved=true`)
      .then(setSchema).catch(() => setSchema({ properties: {} }));
  }, [step.step_type]);

  const setField = (k: keyof Step, v: any) => onChange({ ...step, [k]: v });

  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="subtitle2" sx={{ minWidth: 160 }}>{step.step_type}</Typography>
        <TextField size="small" label="step_id" value={step.step_id}
          onChange={(e) => setField("step_id", e.target.value)} />
        <TextField size="small" label="name" value={step.name ?? ""}
          onChange={(e) => setField("name", e.target.value)} />
        <Box sx={{ flexGrow: 1 }} />
        <IconButton size="small" onClick={onUp} aria-label="up">↑</IconButton>
        <IconButton size="small" onClick={onDown} aria-label="down">↓</IconButton>
        <IconButton size="small" onClick={onRemove} aria-label="remove">✕</IconButton>
      </Stack>
      <Box sx={{ mt: 1 }}>
        {schema
          ? <SchemaForm schema={schema} value={step.params ?? {}}
              onChange={(p) => setField("params", p)} types={types} />
          : <Typography variant="caption">loading schema…</Typography>}
      </Box>
    </Paper>
  );
}
