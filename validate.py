#!/usr/bin/env python3
"""
validate.py
Post-generation sanity checks. Run after generate-manifest.py.
Exits with code 1 (fails the CI build) if anything is wrong.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT     = Path(__file__).parent
ERRORS   = []
WARNINGS = []


def err(msg: str):  ERRORS.append(f"  ✗  {msg}")
def warn(msg: str): WARNINGS.append(f"  ⚠  {msg}")
def ok(msg: str):   print(f"  ✓  {msg}")


# ── 1. image-manifest.json ────────────────────────────────────────────────────

manifest_path = ROOT / "image-manifest.json"
categories    = []

if not manifest_path.exists():
    err("image-manifest.json not found")
else:
    try:
        manifest    = json.loads(manifest_path.read_text(encoding="utf-8"))
        categories  = manifest.get("categories", [])
        if not isinstance(categories, list):
            err("image-manifest.json: 'categories' is not a list")
        else:
            ok(f"image-manifest.json valid  ({len(categories)} categories)")
    except json.JSONDecodeError as e:
        err(f"image-manifest.json is not valid JSON: {e}")

# ── 2. Per-image checks ───────────────────────────────────────────────────────

total = 0
for cat in categories:
    cat_name = cat.get("name", "?")
    for img in cat.get("images", []):
        total += 1
        file_val = img.get("file", "")

        # Required fields
        for field in ("file", "alt", "added"):
            if field not in img:
                err(f"[{cat_name}] image missing field '{field}': {img}")

        # Path must stay inside images/
        if file_val and not file_val.startswith("images/"):
            err(f"[{cat_name}] image path escapes images/ dir: {file_val}")
            continue

        # File must exist on disk
        disk_path = ROOT / file_val
        if not disk_path.exists():
            err(f"[{cat_name}] file not found on disk: {file_val}")
        elif disk_path.stat().st_size == 0:
            err(f"[{cat_name}] file is empty: {file_val}")

        # animated flag must only appear on .gif or .webp
        if img.get("animated") and not file_val.lower().endswith((".gif", ".webp")):
            err(f"[{cat_name}] animated:true on non-GIF/WebP file: {file_val}")

if categories:
    ok(f"All {total} image entries checked")

# ── 3. og-preview.jpg ────────────────────────────────────────────────────────

og = ROOT / "og-preview.jpg"
if total == 0:
    pass  # no images yet, og-preview is optional
elif not og.exists():
    warn("og-preview.jpg missing — social sharing preview will be broken")
elif og.stat().st_size == 0:
    err("og-preview.jpg exists but is empty")
else:
    # Verify it's actually a JPEG (magic bytes FF D8)
    magic = og.read_bytes()[:2]
    if magic != b"\xff\xd8":
        err(f"og-preview.jpg is not a valid JPEG (magic bytes: {magic.hex()})")
    else:
        ok(f"og-preview.jpg exists  ({og.stat().st_size // 1024} KB)")

# ── 4. sitemap.xml ────────────────────────────────────────────────────────────

sitemap_path = ROOT / "sitemap.xml"
if not sitemap_path.exists():
    warn("sitemap.xml not found")
else:
    try:
        tree = ET.parse(sitemap_path)
        urls = tree.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url")
        if not urls:
            warn("sitemap.xml has no <url> entries")
        else:
            ok(f"sitemap.xml valid  ({len(urls)} url entr{'ies' if len(urls) != 1 else 'y'})")
    except ET.ParseError as e:
        err(f"sitemap.xml is not valid XML: {e}")

# ── 5. image-hashes.json ─────────────────────────────────────────────────────

hashes_path = ROOT / "image-hashes.json"
if not hashes_path.exists():
    warn("image-hashes.json not found — all images will be re-processed next run")
else:
    try:
        hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
        ok(f"image-hashes.json valid  ({len(hashes)} entries)")
    except json.JSONDecodeError as e:
        err(f"image-hashes.json is not valid JSON: {e}")

# ── 6. image-dates.json ───────────────────────────────────────────────────────

dates_path = ROOT / "image-dates.json"
if not dates_path.exists():
    warn("image-dates.json not found")
else:
    try:
        json.loads(dates_path.read_text(encoding="utf-8"))
        ok("image-dates.json valid")
    except json.JSONDecodeError as e:
        err(f"image-dates.json is not valid JSON: {e}")

# ── Summary ───────────────────────────────────────────────────────────────────

print()
for w in WARNINGS: print(w)
for e in ERRORS:   print(e)

if ERRORS:
    print(f"\n✗  Validation failed — {len(ERRORS)} error{'s' if len(ERRORS) != 1 else ''}.")
    sys.exit(1)
else:
    status = f"  ({len(WARNINGS)} warning{'s' if len(WARNINGS) != 1 else ''})" if WARNINGS else ""
    print(f"✓  All checks passed{status}")
    sys.exit(0)
