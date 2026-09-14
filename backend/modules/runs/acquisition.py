"""Run-start errors (runs §run.start).

Recipe-id resolution itself lives in the `config` module (Config → Barcode page,
`DefaultConfig.resolve_recipe_from_barcode`) — `runs` only needs the error type its
router already maps to HTTP 422.
"""

from __future__ import annotations


class AcquisitionError(Exception):
    """Could not resolve a recipe id from the run request. Maps to HTTP 422."""
