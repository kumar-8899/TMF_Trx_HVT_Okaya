"""CLI for the System Blueprint tooling (docs/SYSTEM_BLUEPRINT.md).

    python -m tools.blueprint make-template [PATH]
        Write a blank SystemBlueprint.template.xlsx (default: ./SystemBlueprint.template.xlsx).

    python -m tools.blueprint generate --workbook FILE --app-name NAME [--root DIR]
                                       [--prune] [--dry-run]
        Generate/reconcile app/<name>/maps/*.json + docs from a filled workbook.
        Exit 0 if clean, 2 if there are blocking validation errors.

Run from the `backend/` directory so `tools`, `modules`, and `instrumentlib` resolve.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _default_root() -> Path:
    # tools/blueprint/__main__.py -> tools -> backend -> repo root
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.blueprint")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("make-template", help="write a blank blueprint workbook")
    t.add_argument("path", nargs="?", default="SystemBlueprint.template.xlsx")

    g = sub.add_parser("generate", help="generate/reconcile artifacts from a filled sheet")
    g.add_argument("--workbook", required=True)
    g.add_argument("--app-name", required=True)
    g.add_argument("--root", default=None, help="repo root (default: this framework's root)")
    g.add_argument("--prune", action="store_true",
                   help="drop signals/actions removed from the sheet (default: keep+warn)")
    g.add_argument("--dry-run", action="store_true", help="validate + report, write nothing")

    args = ap.parse_args(argv)
    try:  # the report is UTF-8; a legacy Windows console would otherwise mangle it
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.cmd == "make-template":
        from .template import make_template

        out = make_template(args.path)
        print(f"wrote {out}")
        return 0

    if args.cmd == "generate":
        from .generate import generate_from_workbook

        root = Path(args.root) if args.root else _default_root()
        rep = generate_from_workbook(args.workbook, root, args.app_name,
                                     prune=args.prune, write=not args.dry_run)
        print(rep.to_markdown(args.app_name))
        return 0 if rep.ok else 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
