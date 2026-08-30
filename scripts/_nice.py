"""Shared helpers for the rule builders."""
import re
import sys
from pathlib import Path

WB = Path(".workbench/nice")


def quote(slug: str, rec: str, end_marker: str | None = None) -> str:
    """Pull recommendation `rec` from guideline `slug`, verbatim, whitespace-collapsed.

    The NICE UK Open Content Licence forbids amending the wording of a published
    recommendation, so slicing beats transcription: fidelity holds by construction.
    """
    for block in (WB / f"{slug}.txt").read_text().split("\n\n"):
        m = re.match(rf"\[{re.escape(rec)}\]", block)
        if not m:
            continue
        body = re.sub(r"\s+", " ", block[m.end():]).strip()
        body = re.sub(rf"^{re.escape(rec)}\s*", "", body)
        if end_marker:
            idx = body.find(end_marker)
            if idx == -1:
                sys.exit(f"FAIL {slug} {rec}: end marker {end_marker!r} not found")
            body = body[:idx].strip()
        return body
    sys.exit(f"FAIL {slug} {rec}: recommendation not found")


def y(s: str) -> str:
    """Quote a string for YAML."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
