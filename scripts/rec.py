#!/usr/bin/env python3
"""Print one recommendation from a fetched guideline, whitespace-collapsed."""
import re, sys
from pathlib import Path
f = Path(".workbench/nice") / f"{sys.argv[1]}.txt"
want = sys.argv[2:]
blocks = f.read_text().split("\n\n")
for b in blocks:
    m = re.match(r"\[(\d+\.\d+(?:\.\d+)?)\]", b)
    if m and m.group(1) in want:
        body = re.sub(r"\s+", " ", b[m.end():]).strip()
        body = re.sub(r"^" + re.escape(m.group(1)) + r"\s*", "", body)
        print(f"--- {m.group(1)}\n{body[:900]}\n")
