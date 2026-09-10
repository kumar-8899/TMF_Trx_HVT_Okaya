"""Validate a blueprint, generate the app's canonical artifacts, and reconcile in place.

Outputs (all under `app/<name>/`):
  maps/<station>.json        the controller-side variable map (signals + actions)
  maps/.blueprint.lock.json  the tag ledger — the reconcile key store
  docs/INSTRUMENTS.md        the Instruments-page setup checklist (+ a paste-ready
                             controller.json `instances[]` block for standalone/sim runs)
  docs/MULTIPLEXING.md       the composite-driver build spec (create-instrument-library
                             handoff), when the Multiplexing sheet has rows
  blueprint-report.md        the added / changed / removed / pending report

Reconcile is keyed on each row's stable `tag`: a fuller sheet UPDATES what exists
(fill TBDs, rename by tag, add new) rather than clobbering it. A tag dropped from the
sheet is kept-and-warned by default (a signal may be referenced by a recipe); pass
`prune=True` to drop it. A signal with neither `read` nor `write` is tracked as PENDING
and not emitted (the engine requires a direction) so a later sheet completes it.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog
from .reader import Blueprint, read_workbook

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")  # variable / instrument id rule
OWNERS = {"labview", "python"}
NONSCALAR_CAPS = {"multiplexer", "dso"}
LEDGER_VERSION = 1


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    mux: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_markdown(self, app_name: str) -> str:
        def block(title: str, items: list[str]) -> str:
            if not items:
                return f"### {title}\n_none_\n"
            return f"### {title}\n" + "".join(f"- {i}\n" for i in items)

        out = [f"# System Blueprint report — `{app_name}`", ""]
        out.append(f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')}._")
        out.append("")
        if self.errors:
            out.append("> ⚠️ **Blocking problems below — no files were written.**\n")
        out.append(block("Errors (must fix)", self.errors))
        out.append(block("Warnings", self.warnings))
        out.append(block("Added", self.added))
        out.append(block("Changed", self.changed))
        out.append(block("Removed (dropped from the sheet)", self.removed))
        out.append(block("Pending (address not known yet — not emitted)", self.pending))
        out.append(block("Multiplexing (composite-driver handoff)", self.mux))
        out.append(block("Files written", self.written))
        return "\n".join(out)


# ---------------------------------------------------------------------------- helpers


def _num(v):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def _bool(v, default=None):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _channel_args(raw) -> list:
    """A `channel` cell → the fixed leading args list. Comma-separated for multi-arg
    methods; each token coerced to int/float where it looks numeric."""
    if raw is None:
        return []
    tokens = [t.strip() for t in str(raw).split(",") if t.strip()]
    out = []
    for t in tokens:
        n = _num(t)
        out.append(n if n is not None else t)
    return out


def _parse_params(raw) -> dict:
    """A `connection` cell like `resource=TCPIP::… ; timeout_ms=5000` → dict."""
    if raw is None:
        return {}
    out: dict[str, object] = {}
    for part in re.split(r"[;\n]+", str(raw)):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        n = _num(v)
        out[k] = n if n is not None and str(n) == v else v
    return out


def _csv_list(raw) -> list[str]:
    if raw is None:
        return []
    return [t.strip() for t in re.split(r"[,\n]+", str(raw)) if t.strip()]


def _binding(sig: dict, args: list) -> dict:
    """Build the controller-side variable binding (matches controller.instruments.variables)."""
    b: dict[str, object] = {"instance": sig["_instance_id"]}
    if sig.get("read"):
        b["read"] = sig["read"]
    if sig.get("write"):
        b["write"] = sig["write"]
    if args:
        b["args"] = args
    scale = {}
    gain, offset = _num(sig.get("gain")), _num(sig.get("offset"))
    if gain is not None and gain != 1.0:
        scale["gain"] = gain
    if offset is not None and offset != 0.0:
        scale["offset"] = offset
    if scale:
        b["scale"] = scale
    clamp = {}
    cmin, cmax = _num(sig.get("clamp_min")), _num(sig.get("clamp_max"))
    if cmin is not None:
        clamp["min"] = cmin
    if cmax is not None:
        clamp["max"] = cmax
    if clamp:
        b["clamp"] = clamp
    rng = {}
    rmin, rmax = _num(sig.get("range_min")), _num(sig.get("range_max"))
    if rmin is not None:
        rng["min"] = rmin
    if rmax is not None:
        rng["max"] = rmax
    if rng:
        b["range"] = rng
    dead = _num(sig.get("deadband"))
    if dead is not None:
        b["deadband"] = dead
    if sig.get("units"):
        b["units"] = sig["units"]
    return b


# ------------------------------------------------------------------------- validation


def _index_instruments(bp: Blueprint, rep: Report) -> dict[str, dict]:
    """tag -> normalized instrument record; validates each and reports problems."""
    by_tag: dict[str, dict] = {}
    seen_ids: dict[str, str] = {}
    transports = catalog.transports()
    for row in bp.instruments:
        tag = row.get("tag")
        if not tag:
            rep.errors.append("Instruments: a row is missing its `tag`.")
            continue
        if tag in by_tag:
            rep.errors.append(f"Instruments: duplicate tag `{tag}`.")
            continue
        inst_id = row.get("id") or str(tag)
        if not NAME_RE.match(str(inst_id)):
            rep.errors.append(
                f"Instruments `{tag}`: id `{inst_id}` must match ^[a-z][a-z0-9_]{{0,63}}$."
            )
        if inst_id in seen_ids:
            rep.errors.append(
                f"Instruments `{tag}`: id `{inst_id}` already used by `{seen_ids[inst_id]}`."
            )
        seen_ids[inst_id] = tag
        owner = (row.get("owner") or "labview").lower()
        if owner not in OWNERS:
            rep.errors.append(f"Instruments `{tag}`: owner `{owner}` must be labview|python.")
        caps = _csv_list(row.get("capabilities"))
        params = _parse_params(row.get("connection"))
        rec = {
            "tag": tag, "id": inst_id, "label": row.get("label") or inst_id,
            "owner": owner, "model": row.get("model") or "",
            "family": row.get("family") or "", "capabilities": caps,
            "library": row.get("library"), "transport": row.get("transport"),
            "params": params, "stations": _csv_list(row.get("stations")),
            "simulated": _bool(row.get("simulated"), default=True),
            "status": (row.get("status") or "known"),
        }
        if owner == "python" and not rec["library"] and rec["status"] != "TBD":
            rep.warnings.append(f"Instruments `{tag}`: python-owned but no `library` yet.")
        if owner == "labview" and rec["transport"]:
            t = transports.get(rec["transport"])
            if t is None:
                rep.errors.append(
                    f"Instruments `{tag}`: unknown transport `{rec['transport']}` "
                    f"(one of {catalog.all_transport_ids()})."
                )
            else:
                missing = [k for k in t["required"] if k not in params]
                if missing and rec["status"] != "TBD":
                    rep.warnings.append(
                        f"Instruments `{tag}`: transport `{rec['transport']}` still needs "
                        f"connection param(s): {missing}."
                    )
        by_tag[tag] = rec
    return by_tag


def _validate_signal(sig: dict, inst: dict | None, rep: Report) -> list | None:
    """Returns the fixed-arg list if the signal is emittable, or None if it is not
    (pending / error). Appends problems to `rep`."""
    tag = sig["tag"]
    if not NAME_RE.match(str(sig.get("name") or "")):
        rep.errors.append(f"Signals `{tag}`: name `{sig.get('name')}` must match "
                          f"^[a-z][a-z0-9_]{{0,63}}$.")
        return None
    if inst is None:
        rep.errors.append(f"Signals `{tag}`: instrument_tag `{sig.get('instrument_tag')}` "
                          f"not found on the Instruments sheet.")
        return None
    read, write = sig.get("read"), sig.get("write")
    if not read and not write:
        rep.pending.append(f"`{sig.get('name')}` ({tag}) — no read/write method yet "
                          f"on `{inst['id']}`.")
        return None
    args = _channel_args(sig.get("channel"))
    if inst["owner"] == "labview":
        # LabVIEW-owned: methods are logical, not from our scalar catalog — inventory only.
        return args
    caps = inst["capabilities"]
    reads = catalog.read_methods_for(caps)
    writes = catalog.write_methods_for(caps)
    fixed_expect = None
    if read:
        if caps and read not in reads:
            rep.errors.append(f"Signals `{tag}`: read `{read}` is not a read method of "
                              f"`{inst['id']}` capabilities {caps} (have {sorted(reads)}).")
        elif caps:
            fixed_expect = reads[read]
    if write:
        if caps and write not in writes:
            rep.errors.append(f"Signals `{tag}`: write `{write}` is not a write method of "
                              f"`{inst['id']}` capabilities {caps} (have {sorted(writes)}).")
        elif caps:
            wf = writes[write]
            if fixed_expect is not None and wf != fixed_expect:
                rep.errors.append(f"Signals `{tag}`: read/write disagree on fixed-arg count "
                                  f"({fixed_expect} vs {wf}).")
            fixed_expect = wf if fixed_expect is None else fixed_expect
    if not caps:
        rep.warnings.append(f"Signals `{tag}`: instrument `{inst['id']}` lists no "
                           f"capabilities yet — method not validated.")
    if fixed_expect is not None and len(args) != fixed_expect:
        rep.errors.append(f"Signals `{tag}`: method needs {fixed_expect} channel/arg value(s), "
                          f"got {len(args)} ({args or 'none'}).")
        return None
    cmin, cmax = _num(sig.get("clamp_min")), _num(sig.get("clamp_max"))
    if cmin is not None and cmax is not None and cmin > cmax:
        rep.errors.append(f"Signals `{tag}`: clamp min {cmin} > max {cmax}.")
    return args


# --------------------------------------------------------------------------- generate


def _load_ledger(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"schema_version": LEDGER_VERSION, "signals": {}, "instruments": {},
            "actions": {}, "mux": {}}


def generate(bp: Blueprint, root: str | Path, app_name: str, *,
             prune: bool = False, write: bool = True) -> Report:
    root = Path(root)
    app_dir = root / "app" / app_name
    maps_dir = app_dir / "maps"
    docs_dir = app_dir / "docs"
    ledger_path = maps_dir / ".blueprint.lock.json"
    rep = Report()

    instruments = _index_instruments(bp, rep)
    prev = _load_ledger(ledger_path)

    # ---- signals -> per-station maps ----
    cur_sig: dict[str, dict] = {}      # tag -> {station, name, binding}
    seen_names: dict[tuple, str] = {}  # (station, name) -> tag
    seen_sig_tags: set[str] = set()
    for sig in bp.signals:
        tag = sig.get("tag")
        if not tag:
            rep.errors.append("Signals: a row is missing its `tag`.")
            continue
        if tag in seen_sig_tags:
            rep.errors.append(f"Signals: duplicate tag `{tag}`.")
            continue
        seen_sig_tags.add(tag)
        inst = instruments.get(sig.get("instrument_tag"))
        sig["_instance_id"] = inst["id"] if inst else (sig.get("instrument_tag") or "?")
        station = sig.get("station") or "st1"
        name = sig.get("name")
        key = (station, name)
        if name and key in seen_names:
            rep.errors.append(f"Signals `{tag}`: name `{name}` already used on {station} "
                              f"by `{seen_names[key]}`.")
        args = _validate_signal(sig, inst, rep)
        if args is None:
            continue  # pending or error (already reported)
        if inst and inst["owner"] == "labview":
            rep.warnings.append(f"`{name}` ({tag}) is on LabVIEW-owned `{inst['id']}` — "
                               f"captured as inventory, not emitted to the controller map.")
            continue
        seen_names[key] = tag
        cur_sig[tag] = {"station": station, "name": name, "binding": _binding(sig, args)}

    # ---- actions ----
    cur_act: dict[str, dict] = {}
    known_caps = set(catalog.all_capability_ids()) | NONSCALAR_CAPS
    for act in bp.actions:
        tag = act.get("tag")
        if not tag:
            rep.errors.append("Actions: a row is missing its `tag`.")
            continue
        inst = instruments.get(act.get("instrument_tag"))
        if inst is None:
            rep.errors.append(f"Actions `{tag}`: instrument_tag "
                              f"`{act.get('instrument_tag')}` not found.")
            continue
        cap = act.get("capability")
        if not cap:
            rep.errors.append(f"Actions `{tag}`: `capability` is required.")
            continue
        if cap not in known_caps:
            rep.warnings.append(f"Actions `{tag}`: capability `{cap}` is not a known "
                               f"capability id.")
        station = act.get("station") or "st1"
        cur_act[tag] = {"station": station, "name": act.get("name"),
                        "binding": {"instance": inst["id"], "capability": cap}}

    if rep.errors:
        # Nothing is written on a blocking error; the report explains why.
        return rep

    _reconcile("signal", prev["signals"], cur_sig, rep,
               label=lambda v: f"`{v['name']}` on {v['station']}")
    _reconcile("action", prev.get("actions", {}), cur_act, rep,
               label=lambda v: f"action `{v['name']}` on {v['station']}")

    # ---- build station maps (active + kept-removed) ----
    stations: dict[str, dict] = {}

    def _emit(collection_prev, cur, kind):
        for tag, v in cur.items():
            st = stations.setdefault(v["station"], {"signals": {}, "actions": {}})
            st[kind][v["name"]] = v["binding"]
        if prune:
            return
        for tag, pv in collection_prev.items():  # carry over tags dropped from the sheet
            if tag in cur:
                continue
            st = stations.setdefault(pv["station"], {"signals": {}, "actions": {}})
            st[kind][pv["name"]] = pv["binding"]

    _emit(prev["signals"], cur_sig, "signals")
    _emit(prev.get("actions", {}), cur_act, "actions")

    # ---- multiplexing -> composite-driver spec ----
    mux_specs = _mux_specs(bp, instruments, cur_sig, rep)

    # ---- instruments checklist ----
    inst_md = _instruments_md(app_name, instruments)
    mux_md = _mux_md(app_name, mux_specs) if mux_specs else None

    # ---- ledger ----
    new_ledger = {
        "schema_version": LEDGER_VERSION,
        "generated_ts": time.time(),
        "signals": _merge_ledger(prev["signals"], cur_sig, prune),
        "actions": _merge_ledger(prev.get("actions", {}), cur_act, prune),
        "instruments": {r["tag"]: {"id": r["id"], "owner": r["owner"],
                                   "status": "active"} for r in instruments.values()},
        "mux": {m["tag"]: {"logical_signal": m["logical_signal"], "status": "active"}
                for m in mux_specs},
    }

    if write:
        maps_dir.mkdir(parents=True, exist_ok=True)
        docs_dir.mkdir(parents=True, exist_ok=True)
        for station, body in sorted(stations.items()):
            path = maps_dir / f"{station}.json"
            payload = {"schema_version": 1, "signals": body["signals"],
                       "actions": body["actions"]}
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            rep.written.append(str(path.relative_to(root)))
        ledger_path.write_text(json.dumps(new_ledger, indent=2) + "\n", encoding="utf-8")
        rep.written.append(str(ledger_path.relative_to(root)))
        (docs_dir / "INSTRUMENTS.md").write_text(inst_md, encoding="utf-8")
        rep.written.append(str((docs_dir / "INSTRUMENTS.md").relative_to(root)))
        if mux_md:
            (docs_dir / "MULTIPLEXING.md").write_text(mux_md, encoding="utf-8")
            rep.written.append(str((docs_dir / "MULTIPLEXING.md").relative_to(root)))
        report_path = app_dir / "blueprint-report.md"
        report_path.write_text(rep.to_markdown(app_name), encoding="utf-8")
    return rep


def _reconcile(kind: str, prevmap: dict, cur: dict, rep: Report, *, label) -> None:
    for tag, v in cur.items():
        pv = prevmap.get(tag)
        if pv is None or pv.get("status") == "removed":
            rep.added.append(f"{kind} {label(v)}")
        elif (pv.get("name"), pv.get("station")) != (v["name"], v["station"]):
            rep.changed.append(
                f"{kind} `{pv.get('name')}`→{label(v)} (renamed/moved by tag `{tag}`)")
        elif pv.get("binding") != v["binding"]:
            rep.changed.append(f"{kind} {label(v)} (binding updated)")
    for tag, pv in prevmap.items():
        if pv.get("status") == "removed":
            continue
        if tag not in cur:
            rep.removed.append(
                f"{kind} `{pv.get('name')}` on {pv.get('station')} — dropped from the "
                f"sheet (tag `{tag}`); kept in the map with a warning.")


def _merge_ledger(prevmap: dict, cur: dict, prune: bool) -> dict:
    out = {tag: {**v, "status": "active"} for tag, v in cur.items()}
    for tag, pv in prevmap.items():
        if tag in out:
            continue
        if prune:
            continue
        out[tag] = {**pv, "status": "removed"}
    return out


# --------------------------------------------------------------------------- mux + md


def _mux_specs(bp: Blueprint, instruments: dict, cur_sig: dict, rep: Report) -> list[dict]:
    name_to_tag = {(v["station"], v["name"]): tag for tag, v in cur_sig.items()}
    specs = []
    for row in bp.mux:
        tag = row.get("tag")
        if not tag:
            rep.errors.append("Multiplexing: a row is missing its `tag`.")
            continue
        logical = row.get("logical_signal")
        sig_tag = next((t for (st, nm), t in name_to_tag.items() if nm == logical), None)
        if sig_tag is None:
            rep.warnings.append(f"Multiplexing `{tag}`: logical_signal `{logical}` does not "
                               f"match a Signals row — recorded, but check the name.")
        composite = None
        if sig_tag:
            composite = cur_sig[sig_tag]["binding"]["instance"]
        sel = instruments.get(row.get("selector_instrument_tag"))
        meas = instruments.get(row.get("measure_instrument_tag"))
        if sel is None:
            rep.warnings.append(f"Multiplexing `{tag}`: selector_instrument_tag "
                               f"`{row.get('selector_instrument_tag')}` not on Instruments.")
        if meas is None:
            rep.warnings.append(f"Multiplexing `{tag}`: measure_instrument_tag "
                               f"`{row.get('measure_instrument_tag')}` not on Instruments.")
        select_by = (row.get("select_by") or "mux_route").lower()
        if select_by == "mux_route" and not row.get("route"):
            rep.warnings.append(f"Multiplexing `{tag}`: select_by=mux_route needs a `route`.")
        if select_by == "relay_pattern" and not row.get("relay_pattern"):
            rep.warnings.append(f"Multiplexing `{tag}`: select_by=relay_pattern needs a "
                               f"`relay_pattern`.")
        specs.append({
            "tag": tag, "logical_signal": logical,
            "composite_instance": composite or "?",
            "measure": (meas["id"] if meas else row.get("measure_instrument_tag")),
            "measure_method": row.get("measure_method"),
            "measure_channel": row.get("measure_channel"),
            "selector": (sel["id"] if sel else row.get("selector_instrument_tag")),
            "select_by": select_by, "route": row.get("route"),
            "relay_pattern": row.get("relay_pattern"),
            "settle_ms": _num(row.get("settle_ms")), "notes": row.get("notes") or "",
        })
    for m in specs:
        rep.mux.append(f"`{m['logical_signal']}` via `{m['composite_instance']}` "
                       f"({m['select_by']} "
                       f"{m['route'] or m['relay_pattern']}, settle {m['settle_ms']}ms)")
    return specs


def _instruments_md(app_name: str, instruments: dict) -> str:
    out = [f"# Instruments — `{app_name}`", "",
           "Generated from the System Blueprint. Instrument **instances are DB records** —",
           "create each on **Config → Instruments** (ids must match the variable map's",
           "`instance` names). This is a checklist, not a config file.", "",
           "| id | owner | model | library / transport | connection | capabilities | "
           "stations | simulated |",
           "|----|-------|-------|---------------------|------------|--------------|"
           "----------|-----------|"]
    py_instances = []
    for r in sorted(instruments.values(), key=lambda r: r["id"]):
        lt = r["library"] if r["owner"] == "python" else (r["transport"] or "")
        conn = "; ".join(f"{k}={v}" for k, v in r["params"].items())
        caps = ", ".join(r["capabilities"])
        st = ", ".join(r["stations"]) or "(all)"
        out.append(f"| `{r['id']}` | {r['owner']} | {r['model']} | {lt} | {conn} | "
                   f"{caps} | {st} | {r['simulated'] if r['owner']=='python' else '—'} |")
        if r["owner"] == "python" and r["library"]:
            inst = {"id": r["id"], "library": r["library"], "params": r["params"],
                    "simulated": r["simulated"]}
            if r["stations"]:
                inst["stations"] = r["stations"]
            py_instances.append(inst)
    out += ["", "## Standalone / sim runs (`controller.json`)", "",
            "Under app supervision the Instruments page is the source of truth and a",
            "`controller.json` `instances` list is ignored. For a standalone",
            "`python -m controller` or `run_sim.py` run, paste this block into",
            "`controller.json`:", "", "```json",
            json.dumps({"instances": py_instances}, indent=2), "```", ""]
    return "\n".join(out) + "\n"


def _mux_md(app_name: str, specs: list[dict]) -> str:
    out = [f"# Multiplexing — `{app_name}`", "",
           "Build spec for **composite drivers** (create-instrument-library handoff). Each",
           "scanned reading is an ordinary variable on its composite instrument; the relay",
           "switching + settle live INSIDE that driver, never in the variable map. A digital",
           "output used to steer the mux is a selector element here, not a signal.", ""]
    by_comp: dict[str, list[dict]] = {}
    for m in specs:
        by_comp.setdefault(m["composite_instance"], []).append(m)
    for comp, rows in sorted(by_comp.items()):
        out += [f"## Composite instrument `{comp}`", "",
                "| logical signal | measure | method | channel | select by | route / "
                "relay pattern | settle (ms) | notes |",
                "|----------------|---------|--------|---------|-----------|--------------"
                "-|-------------|-------|"]
        for m in rows:
            out.append(f"| `{m['logical_signal']}` | {m['measure']} | "
                       f"{m['measure_method'] or ''} | {m['measure_channel'] or ''} | "
                       f"{m['select_by']} | {m['route'] or m['relay_pattern'] or ''} | "
                       f"{m['settle_ms'] if m['settle_ms'] is not None else ''} | "
                       f"{m['notes']} |")
        out.append("")
    return "\n".join(out) + "\n"


def generate_from_workbook(workbook: str | Path, root: str | Path, app_name: str,
                           *, prune: bool = False, write: bool = True) -> Report:
    return generate(read_workbook(workbook), root, app_name, prune=prune, write=write)
