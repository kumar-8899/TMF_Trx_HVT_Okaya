"""Best-effort PDF text extraction (pure-Python `pypdf`) so library documents are searchable.

Never fatal: a scanned drawing, an encrypted or corrupt file simply yields no text — the document is
still stored and viewable, it just isn't full-text searchable (the UI says so). Text is capped so one
huge manual can't bloat the index."""

from __future__ import annotations

import io

try:                                     # optional at import time; a missing wheel degrades to "no text"
    import pypdf
except ImportError:                      # pragma: no cover
    pypdf = None

MAX_CHARS = 400_000


def extract_text(data: bytes, max_chars: int = MAX_CHARS) -> tuple[str, int | None]:
    """(text, page_count). ("", None) when nothing could be read."""
    if pypdf is None:
        return "", None
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return "", len(reader.pages) if reader.decrypt("") else None
        pages = len(reader.pages)
        chunks: list[str] = []
        total = 0
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
            except Exception:            # noqa: BLE001 — one bad page must not lose the rest
                continue
            chunks.append(t)
            total += len(t)
            if total >= max_chars:
                break
        return "\n".join(chunks)[:max_chars].strip(), pages
    except Exception:                    # noqa: BLE001 — corrupt / unsupported PDF
        return "", None
