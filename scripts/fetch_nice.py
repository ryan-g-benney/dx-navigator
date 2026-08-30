#!/usr/bin/env python3
"""Fetch NICE guidance pages and extract numbered recommendations verbatim.

Writes one .txt per guideline to .workbench/nice/. Respects the 1s crawl-delay
in nice.org.uk/robots.txt. Output is a working copy -- the verbatim text that
reaches data/ is checked back against these files by verify_quotes.py.
"""
import html
import re
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / ".workbench" / "nice"
OUT.mkdir(parents=True, exist_ok=True)
UA = "dx-navigator-research/0.1"

REC = re.compile(r"(?=(?:^|\s)(\d+\.\d+(?:\.\d+)?)\s+[A-Z(])")


def clean(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|nav|footer)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"[ \t\xa0]+", " ", html.unescape(raw)).strip()


def fetch(url: str) -> str:
    r = subprocess.run(
        ["curl", "-sSL", "-m", "60", "-A", UA, url],
        capture_output=True, text=True, check=False,
    )
    return r.stdout


def main(targets: list[tuple[str, str]]) -> None:
    for slug, url in targets:
        text = clean(fetch(url))
        parts = REC.split(text)
        recs = []
        for i in range(1, len(parts) - 1, 2):
            num, body = parts[i], parts[i + 1].strip()
            if len(body) > 40:
                recs.append(f"[{num}] {body[:1600]}")
        path = OUT / f"{slug}.txt"
        path.write_text(f"SOURCE_URL: {url}\nCHARS: {len(text)}\nRECS: {len(recs)}\n\n"
                        + "\n\n".join(recs))
        print(f"{slug:14s} {len(text):>7} chars  {len(recs):>3} recs  -> {path.name}")
        time.sleep(1)


if __name__ == "__main__":
    main([tuple(a.split("=", 1)) for a in sys.argv[1:]])
