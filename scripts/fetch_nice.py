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

REC = re.compile(r"(?=(?:^|\s)(\d+\.\d+(?:\.\d+){0,2})\s+[A-Z(])")
TABLE = re.compile(r"(?is)<table[^>]*>.*?</table>")
# Recommendation bodies run long -- the CRB65 and Wells boxes are hundreds of
# characters each. Truncating loses the criteria, which is the part we quote.
MAX_BODY = 12000


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
        raw = fetch(url)

        # A points column reads exactly like a recommendation number: "1.5
        # Immobilisation for more than 3 days" splits the Wells table mid-row
        # and loses one. Hide tables from the splitter, then put them back.
        tables: list[str] = []

        def stash(m: re.Match[str]) -> str:
            tables.append(clean(m.group(0)))
            return f" \x01{len(tables) - 1}\x01 "

        text = clean(TABLE.sub(stash, raw))
        restore = lambda s: re.sub(  # noqa: E731
            r"\x01(\d+)\x01", lambda m: tables[int(m.group(1))], s)

        parts = REC.split(text)
        recs, truncated = [], 0
        for i in range(1, len(parts) - 1, 2):
            num, body = parts[i], restore(parts[i + 1]).strip()
            if len(body) > MAX_BODY:
                truncated += 1
            if len(body) > 40:
                recs.append(f"[{num}] {body[:MAX_BODY]}")
        text = restore(text)
        if truncated:
            print(f"  WARNING {truncated} recommendation(s) hit the {MAX_BODY} "
                  f"char cap and were cut")
        path = OUT / f"{slug}.txt"
        path.write_text(f"SOURCE_URL: {url}\nCHARS: {len(text)}\nRECS: {len(recs)}\n\n"
                        + "\n\n".join(recs))
        print(f"{slug:14s} {len(text):>7} chars  {len(recs):>3} recs  -> {path.name}")
        time.sleep(1)


if __name__ == "__main__":
    main([tuple(a.split("=", 1)) for a in sys.argv[1:]])
