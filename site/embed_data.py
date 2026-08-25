#!/usr/bin/env python3
"""
Embed analysis/summary.json into site/index.html.

The site is deliberately dependency-free and backend-free: rather than
fetch() the summary at runtime (which browsers block under file://, and which
adds a request for ~12KB of data), the JSON is inlined into a
<script type="application/json"> block at publish time.

Run this after re-running analysis/analyze_results.py so the published page
matches the current data:

    python3 analysis/analyze_results.py
    python3 site/embed_data.py

Idempotent — safe to run repeatedly.
"""

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "analysis" / "summary.json"
SITE = ROOT / "site"
INDEX = SITE / "index.html"
DATA_COPY = SITE / "data" / "summary.json"

BLOCK_RE = re.compile(
    r'(<script id="summary-data" type="application/json">\n).*?(\n</script>)',
    re.S,
)


def main() -> int:
    if not SUMMARY.exists():
        print(f"ERROR: {SUMMARY} not found — run analysis/analyze_results.py first")
        return 1

    raw = SUMMARY.read_text()

    # Fail loudly on invalid JSON rather than shipping a page that renders
    # blank. (A bare NaN in this file is exactly what broke the page once:
    # it is valid Python-emitted output but invalid JSON, and JSON.parse
    # throws on it, killing every chart silently.)
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: {SUMMARY} is not valid JSON: {exc}")
        return 1

    # Keep the standalone copy in sync — it is not what the page reads, but it
    # is a useful published artifact for anyone who wants the raw numbers.
    DATA_COPY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SUMMARY, DATA_COPY)

    html = INDEX.read_text()
    new_html, n = BLOCK_RE.subn(lambda m: m.group(1) + raw + m.group(2), html)
    if n != 1:
        print(f"ERROR: expected exactly 1 summary-data block in {INDEX}, found {n}")
        return 1

    INDEX.write_text(new_html)
    print(f"Embedded {len(raw)} bytes of summary JSON into {INDEX.relative_to(ROOT)}")
    print(f"Synced {DATA_COPY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
