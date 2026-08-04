"""Handler conformance checks (PYTHON_CONTROLLER.md §7.3).

A step handler may touch hardware ONLY through `ctx` (§7.2): no instrument, socket, file, DB,
or bridge; no bare sleeps; no unbounded loops; no module/class-level mutable state. These are
the mechanically-checkable rules, run in CI over every core and app step type so a
non-conforming handler fails the suite instead of a run. The value/limit/Measurement rules
(§7.3 r5–r7) are semantic — they're enforced by the simulation-with-failure-modes review
(§13), not by this static pass, so this checker never issues a false PASS on them.

    check_source(source)  -> list[str]   # violations, empty == conforms
    check_handler(cls)    -> list[str]   # convenience: checks the class's own source

Each violation is prefixed with its rule number."""

from __future__ import annotations

import ast
import inspect
import textwrap

# rule 2 — no direct instrument / socket / file / db / bridge access
_FORBIDDEN_IMPORTS = {
    "socket", "requests", "http", "urllib", "ftplib", "telnetlib",
    "sqlite3", "pymysql", "psycopg2", "sqlalchemy", "pymongo",
    "paho", "serial", "pyvisa", "visa", "nidaqmx", "usbtmc",
}
_FILE_CALLS = {"open"}


def check_source(source: str, *, name: str = "handler") -> list[str]:
    try:
        tree = ast.parse(textwrap.dedent(source))   # a class nested in a def is indented
    except SyntaxError as exc:
        return [f"parse: {name} did not parse: {exc}"]
    errors: list[str] = []

    for node in ast.walk(tree):
        # rule 2 — forbidden imports
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in _FORBIDDEN_IMPORTS:
                    errors.append(f"rule2: forbidden import '{a.name}' (use ctx)")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _FORBIDDEN_IMPORTS:
                errors.append(f"rule2: forbidden import from '{node.module}' (use ctx)")
        # rule 1 — no bare time.sleep;  rule 2 — no open()
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "sleep" \
                    and isinstance(f.value, ast.Name) and f.value.id == "time":
                errors.append("rule1: bare time.sleep — use ctx.wait")
            if isinstance(f, ast.Name) and f.id in _FILE_CALLS:
                errors.append("rule2: file access via open() — handlers touch no files")
        # rule 3 — no unbounded loop
        elif isinstance(node, ast.While) and _is_true(node.test):
            body = ast.dump(node)
            if "aborted" not in body and "deadline_exceeded" not in body and not _has_break(node):
                errors.append("rule3: unbounded 'while True' with no ctx.aborted()/"
                              "deadline_exceeded()/break")

    # rule 4 — no module- or class-level mutable state
    errors += _mutable_state(tree.body, "module")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            errors += _mutable_state(node.body, f"class {node.name}")

    return errors


def check_handler(cls) -> list[str]:
    return check_source(inspect.getsource(cls), name=getattr(cls, "__name__", "handler"))


def _is_true(test) -> bool:
    return (isinstance(test, ast.Constant) and test.value is True) \
        or (isinstance(test, ast.NameConstant) and getattr(test, "value", None) is True)  # noqa: SIM101


def _has_break(loop) -> bool:
    # A break anywhere in the body counts as a bound — the heuristic errs toward not
    # flagging a loop that has an exit, since a false rule3 would block a valid handler.
    return any(isinstance(n, ast.Break) for n in ast.walk(loop))


def _mutable_state(body, scope: str) -> list[str]:
    out = []
    for node in body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
                getattr(node, "value", None), (ast.List, ast.Dict, ast.Set)):
            out.append(f"rule4: mutable state at {scope} level")
    return out
