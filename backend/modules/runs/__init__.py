"""runs module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.runs.contract import RunsContract
from modules.runs.variants.default import DefaultRuns


@register_module(
    "runs",
    contract=RunsContract,
    contract_version=1,
    display_name="Runs",
)
class RunsModule:
    """Marker for the runs module; variants carry the implementation."""


register_variant("runs", "default", display_name="Default (LabVIEW)")(DefaultRuns)
