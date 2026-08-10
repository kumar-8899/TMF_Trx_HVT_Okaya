"""TMF core — the application platform modules plug into (CORE.md).

__version__ is the FRAMEWORK release (semver; git tag v<version>). It is stamped
into every record + diag event as `source_version`. Policy (docs/TEMPLATE.md):
MAJOR = a module contract_version or locked-contract breaking change;
MINOR = new modules/features; PATCH = fixes.
"""

__version__ = "1.8.1"
