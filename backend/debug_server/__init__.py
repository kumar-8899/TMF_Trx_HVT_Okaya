"""Debug Server — standalone dev sidecar (DEBUG_SERVER.md).

A pure MQTT subscriber that correlates a station's low-rate bus traffic
(event/#, diag/#, value/#, status, cmd req/reply) on one cross-language
timeline. Separate process + port from the core; never a runtime dependency
of any module (§2). stream/# is never captured (§0).
"""

__version__ = "1.0.0"
