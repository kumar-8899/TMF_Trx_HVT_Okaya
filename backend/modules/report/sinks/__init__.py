"""Report sinks — the pluggable destinations a finished report is routed to.

RP1: sqlite only. RP2 adds the folder sink + make_sink(config). The sqlite sink
is always present (the queryable store); other sinks are result-routed mirrors.
"""

from __future__ import annotations


def when_matches(when: str, is_pass: bool) -> bool:
    return when == "all" or (when == "pass" and is_pass) or (when == "fail" and not is_pass)
