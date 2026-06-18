"""Recipe-id acquisition strategies (runs §run.start).

How a run learns which recipe to run varies by bench:
- EOL benches scan a barcode whose leading characters encode the model/recipe.
- Endurance benches pass the recipe id directly (operator picks from a list).

Strategies are pluggable; phase-1 ships `prefix` (first N barcode chars). Add a
customer-specific strategy by extending `resolve_recipe_id` (or a registry later).
"""

from __future__ import annotations


class AcquisitionError(Exception):
    """Could not resolve a recipe id from the run request. Maps to HTTP 422."""


def resolve_recipe_id(barcode: str, *, strategy: str = "prefix", length: int = 3) -> str:
    """Resolve a recipe id from a scanned barcode.

    `prefix`: take the first `length` characters (the default EOL convention,
    where the recipe id is the leading model code in the barcode).
    """
    barcode = (barcode or "").strip()
    if not barcode:
        raise AcquisitionError("empty barcode")
    if strategy == "prefix":
        rid = barcode[:length]
        if not rid:
            raise AcquisitionError("barcode too short for prefix strategy")
        return rid
    raise AcquisitionError(f"unknown acquisition strategy '{strategy}'")
