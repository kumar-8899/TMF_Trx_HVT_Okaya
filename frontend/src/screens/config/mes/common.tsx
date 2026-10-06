/** Shared pieces of the MES database "process": listings that degrade to manual entry, the name field,
 * and the connection payload. Auto-listing is a convenience, NEVER a requirement — when a server or its
 * permissions can't enumerate databases/tables/columns the field simply accepts typed text. */
import { Autocomplete, TextField } from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";

import type { ServerConn } from "../../../components/DbServerForm";

export interface Listing {
  items: string[];
  /** false = the server couldn't list them (or the request failed): the UI asks the user to type. */
  ok: boolean;
  detail: string;
  loaded: boolean;
  loading: boolean;
  reload: () => void;
}

type Loader = () => Promise<{ ok: boolean; items: any[]; detail?: string }>;

/** Run `load` whenever `deps` change (null = not ready yet). Never throws: a failure becomes ok=false. */
export function useListing(load: Loader | null, deps: unknown[], pick: (x: any) => string = String): Listing {
  const [s, setS] = useState({ items: [] as string[], ok: true, detail: "", loaded: false, loading: false });
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    const fn = loadRef.current;
    if (!fn) { setS({ items: [], ok: true, detail: "", loaded: false, loading: false }); return; }
    const mine = ++seq.current;
    setS((p) => ({ ...p, loading: true }));
    fn().then((r) => {
      if (mine === seq.current) setS({ items: (r.items ?? []).map(pick), ok: r.ok, detail: r.detail ?? "", loaded: true, loading: false });
    }).catch((e: any) => {
      if (mine === seq.current) setS({ items: [], ok: false, detail: e?.message ?? "request failed", loaded: true, loading: false });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...s, reload };
}

interface NameFieldProps {
  label: string;
  /** What is being listed, for the fallback note: "databases", "tables", "columns". */
  what: string;
  value: string;
  onChange: (v: string) => void;
  list: Listing;
  hint?: string;
  width?: number;
  disabled?: boolean;
}

export function NameField({ label, what, value, onChange, list, hint, width = 260, disabled }: NameFieldProps) {
  const manual = list.loaded && !list.ok;
  const helper = list.loading ? "Loading…"
    : manual ? `Couldn't list ${what}${list.detail ? ` (${list.detail})` : ""} — type the name.`
    : hint;
  return (
    <Autocomplete freeSolo size="small" options={list.items} inputValue={value} disabled={disabled}
      sx={{ width }} loading={list.loading}
      onInputChange={(_, v) => onChange(v)}
      renderInput={(p) => (
        <TextField {...p} label={label} helperText={helper} error={false}
          FormHelperTextProps={{ sx: { color: manual ? "warning.main" : undefined } }} />
      )} />
  );
}

/** The connection part of a request body: only server fields, plus the password only when one was typed
 * (a blank password means "use the stored one" on the backend, and only for the same server). */
export function connBody(c: ServerConn, password: string) {
  const { provider, host, port, user, odbc_driver } = c;
  return { provider, host, port, user, odbc_driver, ...(password ? { password } : {}) };
}
