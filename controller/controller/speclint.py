"""Test-spec drift gate (GitHub #5 — literate test authoring).

Each test in a recipe has an authoritative, human-editable procedure spec at
`app/<name>/specs/<test>.md`. The engineer reads and edits that `.md`; the AI reconciles the
code to it. This module is the deterministic gate that keeps them honest: it parses the spec's
structured front-matter + tables and checks them against what actually runs, so an edit to the
`.md` can't silently diverge from the handler / schema / recipe.

The spec is the source of truth. `check_specs` never rewrites code or spec — it reports drift;
the AI (or the engineer) resolves it, then this goes green.

Framework-side + dependency-light (stdlib only): the caller supplies the built step-type
`catalog`, the `recipe`, the map's signal names, and a `{step_id: [measurement names]}` map
collected from a sim run (the app's `run_sim` harness produces this — a step that expands
`params["points"]` only reveals its real measurement names at run time)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Section headings whose markdown table's FIRST column is a set of names we check.
# Matching is prefix + case-insensitive so the human wording after the "—" can vary.
_PARAM_H = "input"          # "## Input — recipe parameters"
_MEAS_H = "output"          # "## Output — report measurements"
_SIG_H = "signals"          # "## Signals / actions"
_TIMING_H = "timing"        # "## Timing / delays"


@dataclass
class Spec:
    test: str                                   # logical test id = recipe group id
    type: str = ""                              # step type
    kind: str = "core"                          # "authored" | "core"
    spec_source: str = ""
    params: set[str] = field(default_factory=set)
    measurements: set[str] = field(default_factory=set)
    signals: set[str] = field(default_factory=set)
    path: Path | None = None


@dataclass
class DriftReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return "spec-lint: all specs in sync"
        lines = [f"spec-lint: {len(self.errors)} error(s), {len(self.warnings)} warning(s)"]
        lines += [f"  ERROR   {e}" for e in self.errors]
        lines += [f"  warning {w}" for w in self.warnings]
        return "\n".join(lines)


# ---- parsing --------------------------------------------------------------

def _front_matter(text: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'").split("#", 1)[0].strip()
    return out


def _sections(text: str) -> dict[str, str]:
    """Map a lowercased first-word-after-'## ' → the section body."""
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        h = re.match(r"^##\s+(.*)$", line)
        if h:
            if cur is not None:
                out[cur] = "\n".join(buf)
            title = h.group(1).strip().lower()
            cur = re.split(r"[\s/—-]", title, 1)[0]      # first token: input/output/signals/timing…
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


def _first_column(section_body: str) -> list[str]:
    """First data column of the first markdown table in a section (skips header + `---` rows)."""
    rows: list[str] = []
    seen_header = False
    for line in section_body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if rows:           # table ended
                break
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        first = cells[0] if cells else ""
        if set(first) <= set("-: "):          # separator row |---|---|
            continue
        if not seen_header:                    # the header row (Param / Measurement / Name…)
            seen_header = True
            continue
        # strip markdown emphasis/backticks around the name
        first = first.strip("`* ").strip()
        if first:
            rows.append(first)
    return rows


def parse_spec(text: str, path: Path | None = None) -> Spec:
    fm = _front_matter(text)
    secs = _sections(text)
    def col(key: str) -> set[str]:
        return {c for c in _first_column(secs.get(key, ""))}
    return Spec(
        test=fm.get("test", ""), type=fm.get("type", ""), kind=(fm.get("kind") or "core").lower(),
        spec_source=fm.get("spec_source", ""),
        params=col(_PARAM_H), measurements=col(_MEAS_H), signals=col(_SIG_H), path=path,
    )


def load_specs(specs_dir: Path) -> dict[str, Spec]:
    """Every specs/*.md except index.md, keyed by front-matter `test`."""
    out: dict[str, Spec] = {}
    for p in sorted(Path(specs_dir).glob("*.md")):
        if p.name.lower() == "index.md":
            continue
        sp = parse_spec(p.read_text(encoding="utf-8"), p)
        if sp.test:
            out[sp.test] = sp
    return out


# ---- recipe walking -------------------------------------------------------

def recipe_tests(recipe: dict) -> dict[str, list[dict]]:
    """Top-level groups = tests: {group_id: [descendant leaf steps]}. Leaves are the
    non-group/repeat steps (measure_and_compare, hipot_*, set_output, wait, …)."""
    out: dict[str, list[dict]] = {}
    for top in recipe.get("steps", []):
        if top.get("type") in ("group", "repeat"):
            leaves: list[dict] = []
            _collect_leaves(top.get("params", {}).get("steps", []), leaves)
            out[top.get("id", top.get("type"))] = leaves
    return out


def _collect_leaves(steps: list[dict], acc: list[dict]) -> None:
    for s in steps or []:
        if s.get("type") in ("group", "repeat"):
            _collect_leaves(s.get("params", {}).get("steps", []), acc)
        else:
            acc.append(s)


# ---- the check ------------------------------------------------------------

def check_specs(specs_dir: Path, recipe: dict, catalog: list[dict],
                emitted_by_step: dict[str, list[str]], map_signals: set[str]) -> DriftReport:
    """Compare every test's spec `.md` against the code/recipe.

    catalog:         controller.registry.catalog() — type_id → schema + required_*
    emitted_by_step: {step_id: [measurement names]} from a sim run of `recipe`
    map_signals:     signal names defined in the station's variable map
    """
    rep = DriftReport()
    specs = load_specs(specs_dir)
    cat = {c["type_id"]: c for c in catalog}
    tests = recipe_tests(recipe)

    # measurements actually produced per test group (from the sim run)
    step_group = {sid: gid for gid, leaves in tests.items() for s in leaves if (sid := s.get("id"))}
    emitted_by_test: dict[str, set[str]] = {gid: set() for gid in tests}
    for sid, names in emitted_by_step.items():
        gid = step_group.get(sid)
        if gid is not None:
            emitted_by_test[gid].update(names)

    judged_tests = {gid for gid, names in emitted_by_test.items() if names}

    # a judged test with no spec is an error; a spec for a missing test is a warning
    for gid in judged_tests:
        if gid not in specs:
            rep.errors.append(f"{gid}: test produces results but has no specs/{gid}.md")
    for tid, sp in specs.items():
        if tid not in tests:
            rep.warnings.append(f"{tid}: specs/{sp.path.name if sp.path else tid+'.md'} has no matching recipe group")
            continue
        _check_one(tid, sp, tests[tid], cat, emitted_by_test.get(tid, set()), map_signals, rep)
    return rep


def _check_one(tid: str, sp: Spec, leaves: list[dict], cat: dict,
               emitted: set[str], map_signals: set[str], rep: DriftReport) -> None:
    def diff(kind: str, spec_set: set[str], real_set: set[str]) -> None:
        for extra in sorted(spec_set - real_set):
            rep.errors.append(f"{tid}: spec lists {kind} '{extra}' not in the code/recipe")
        for missing in sorted(real_set - spec_set):
            rep.errors.append(f"{tid}: {kind} '{missing}' in the code/recipe is missing from the spec")

    # Output measurements — always checkable from the sim run.
    if emitted:
        diff("measurement", sp.measurements, emitted)

    if sp.kind == "authored":
        types = {s.get("type") for s in leaves} & set(cat)
        # the authored type named in front-matter should be one of the group's steps
        if sp.type and sp.type not in {s.get("type") for s in leaves}:
            rep.warnings.append(f"{tid}: spec type '{sp.type}' not used by any step in the recipe group")
        entry = cat.get(sp.type)
        if entry:
            props = set((entry.get("schema") or {}).get("properties", {}))
            diff("parameter", sp.params, props)
            reqs = set(entry.get("required_signals", [])) | set(entry.get("required_actions", []))
            # actions used at runtime (e.g. hipot) come from params; accept the union
            for s in leaves:
                if s.get("type") == sp.type:
                    act = s.get("params", {}).get("action")
                    if act:
                        reqs.add(act)
            diff("signal/action", sp.signals, reqs)
        else:
            rep.warnings.append(f"{tid}: authored type '{sp.type}' not in the step catalog")
        _ = types
    else:  # core
        params: set[str] = set()
        sigs: set[str] = set()
        for s in leaves:
            p = s.get("params", {})
            if s.get("type") == "measure_and_compare":
                if p.get("signal"):
                    sigs.add(p["signal"])
                    if p["signal"] not in map_signals:
                        rep.errors.append(f"{tid}: signal '{p['signal']}' not in the variable map")
            if s.get("type") == "set_output" and p.get("signal"):
                sigs.add(p["signal"])
        diff("signal/action", sp.signals, sigs)
        _ = params
