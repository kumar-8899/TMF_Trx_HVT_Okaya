"""Bounded, redacted text reads for `bench_read_file` (an approved action) - and nothing else.

Reads only under the roots it is given (the app's state root and install), refuses binaries and anything outside, resolves
symlinks first, caps the bytes, and masks values that look like secrets. A path the operator approves is shown on the card exactly
as asked; what is returned is still redacted because a config file is the likeliest thing to be requested and the least safe
thing to hand over verbatim.
"""

from __future__ import annotations

import re
from pathlib import Path

MAX_BYTES = 64 * 1024
_SECRET_LINE = re.compile(r"""(?ix)
    (?P<k>"?[A-Za-z0-9_.\-]*(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|credential|connection[_-]?string)[A-Za-z0-9_.\-]*"?)
    (?P<sep>\s*[=:]\s*)
    (?P<v>"[^"]*"|'[^']*'|[^\s,;}]+)""")


class FileRefused(Exception):
    pass


def redact_text(text: str) -> tuple[str, int]:
    n = 0

    def sub(m: re.Match) -> str:
        nonlocal n
        n += 1
        q = '"' if m.group("v").startswith('"') else "'" if m.group("v").startswith("'") else ""
        return f"{m.group('k')}{m.group('sep')}{q}***redacted***{q}"
    return _SECRET_LINE.sub(sub, text), n


def under(path: Path, roots: list[Path]) -> bool:
    rp = path.resolve()
    return any(rp == r.resolve() or r.resolve() in rp.parents for r in roots if r)


def read_text(path: str | Path, roots: list[Path], *, tail_lines: int | None = None, max_bytes: int = MAX_BYTES) -> dict:
    p = Path(path)
    if not p.is_absolute():
        for r in roots:
            if r and (Path(r) / p).exists():
                p = Path(r) / p
                break
    if not under(p, roots):
        raise FileRefused(f"{path!s} is outside the app's install/state folders - only those can be read")
    if not p.is_file():
        raise FileRefused(f"{p} is not a file (or does not exist)")
    size = p.stat().st_size
    with p.open("rb") as fh:
        if tail_lines:
            fh.seek(max(0, size - max_bytes * 4))
            data = b"\n".join(fh.read().splitlines()[-int(tail_lines):])
        else:
            data = fh.read(max_bytes + 1)
    if b"\x00" in data[:4096]:
        raise FileRefused(f"{p.name} looks binary - only text files can be read")
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    text, masked = redact_text(text)
    return {"path": str(p), "bytes_on_disk": size, "text": text, "truncated": truncated or (bool(tail_lines) and size > max_bytes * 4),
            "redacted_values": masked}
