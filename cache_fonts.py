#!/usr/bin/env python3
"""Cache the two Google Fonts used by index.html as local WOFF2 assets.

Only needed once. The HTML itself never requests Google Fonts or any CDN.
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
CSS = "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400..800&family=Space+Grotesk:wght@400..700&display=swap"


def main() -> None:
    req = urllib.request.Request(CSS, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=30) as r:
        css = r.read().decode("utf-8")
    ASSETS.mkdir(exist_ok=True)
    for family, filename in [("DM Sans", "dm-sans-latin.woff2"), ("Space Grotesk", "space-grotesk-latin.woff2")]:
        blocks = re.findall(r"/\* latin \*/\s*(@font-face\s*\{[^}]+\})", css, re.S)
        block = next((b for b in blocks if f"font-family: '{family}'" in b), None)
        if not block:
            raise ValueError(f"No latin WOFF2 for {family}; inspect Google Fonts CSS")
        url = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        if not url:
            raise ValueError(f"No WOFF2 URL for {family}")
        with urllib.request.urlopen(url.group(1), timeout=30) as r:
            data = r.read()
        if len(data) < 10000:
            raise ValueError(f"Font download too small for {family}")
        (ASSETS / filename).write_bytes(data)
        print(f"Cached {family}: {filename} ({len(data):,} bytes)")
    (ASSETS / "FONT_SOURCES.txt").write_text(
        "Google Fonts cached for offline use.\n"
        "DM Sans: https://fonts.google.com/specimen/DM+Sans\n"
        "Space Grotesk: https://fonts.google.com/specimen/Space+Grotesk\n"
        "Fonts are distributed under the SIL Open Font License 1.1.\n")


if __name__ == "__main__":
    main()
