"""System I/O Blueprint — app-authoring tooling (docs/SYSTEM_BLUEPRINT.md).

An Excel authoring surface a test engineer fills in to declare an application's I/O
system: its instruments and every input/output signal with the address relative to an
instrument. A deterministic generator turns a filled workbook into the framework's
canonical artifacts (the controller-side variable map + an instrument setup checklist),
reconciling in place against a stable per-row `tag` when a fuller sheet arrives later.

This is *authoring-time* tooling. Nothing here runs on a station; the blueprint is never
a runtime data source. It generates `app/<name>/maps/<station>.json` (loaded by the
controller's variable engine) and companion docs, exactly as if hand-authored.

Modules:
  catalog   — closed vocabularies (capability methods, transports) read live from the
              framework code, so the template stays in lock-step with the engine.
  template  — build the blank SystemBlueprint.template.xlsx.
  reader    — parse a filled workbook into normalized rows.
  generate  — validate + generate the map/checklist + reconcile via the tag ledger.
"""

from __future__ import annotations

__all__ = ["catalog", "template", "reader", "generate"]
