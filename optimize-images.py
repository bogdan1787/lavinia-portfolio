#!/usr/bin/env python3
"""
optimize-images.py
Resizes, compresses, and watermarks images in-place for web delivery.

Run:     python optimize-images.py
Requires: pip install Pillow  (installed automatically if missing)

Pipeline per image (runs exactly once per unique file, tracked by SHA-256):
  1. Resize to max 2400 px on longest side
  2. Compress  (JPEG/WebP quality 85, PNG lossless)
  3. Burn watermark: "© Lavinia Gabriela Enache" — bottom-right, Playfair Display Italic
  4. Record SHA-256 of final file → stored in image-hashes.json

On subsequent runs the hash is unchanged → step skipped entirely.
To re-process an image (e.g. after changing watermark text), delete its
entry from image-hashes.json or delete the file entirely.
"""

import hashlib
import json
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    import subprocess, sys
    print("Installing Pillow…")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "-q"])
    from PIL import Image, ImageDraw, ImageFont

# ── Configuration ─────────────────────────────────────────────────────────────

IMAGES_DIR    = Path(__file__).parent / "images"
HASHES_FILE   = Path(__file__).parent / "image-hashes.json"
FONT_DIR      = Path(__file__).parent / "fonts"

WATERMARK_TEXT = "© Lavinia Gabriela Enache"
MAX_PX         = 2400    # max width or height for full images
THUMB_PX       = 400     # max width or height for grid thumbnails
JPEG_Q         = 85      # JPEG / WebP quality

# Font search order — first found wins
# The Action installs fonts-urw-base35 (URW Palladio = Palatino-class serif)
FONT_CANDIDATES = [
    FONT_DIR / "PlayfairDisplay-Italic.ttf",                                    # bundled
    Path("/usr/share/fonts/opentype/urw-base35/URWPalladio-Ita.otf"),           # Ubuntu (Action)
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),    # Ubuntu fallback
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),            # Ubuntu fallback
    Path("C:/Windows/Fonts/georgiai.ttf"),                                      # Windows (Georgia Italic)
    Path("C:/Windows/Fonts/timesi.ttf"),                                        # Windows (Times Italic)
    Path("/System/Library/Fonts/Supplemental/Georgia Italic.ttf"),              # macOS
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def find_font() -> Path | None:
    """Return the first available font path from FONT_CANDIDATES."""
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    return None


def get_font(size: int) -> ImageFont.FreeTypeFont:
    path = find_font()
    if path:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    return ImageFont.load_default()


def apply_watermark(img: Image.Image) -> Image.Image:
    """Burn watermark text into the bottom-right corner."""
    w, h = img.size

    # Font size: 2.5% of shorter side, clamped 18–52 px
    font_size = max(18, min(52, int(min(w, h) * 0.025)))
    font      = get_font(font_size)

    # Measure text on a scratch surface
    scratch = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox    = scratch.textbbox((0, 0), WATERMARK_TEXT, font=font)
    tw, th  = bbox[2] - bbox[0], bbox[3] - bbox[1]

    margin = int(min(w, h) * 0.018)   # ~1.8% of shorter side
    x = w - tw - margin
    y = h - th - margin

    # Work in RGBA for transparency
    rgba   = img.convert("RGBA")
    layer  = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw   = ImageDraw.Draw(layer)

    shadow = max(1, font_size // 20)
    # Shadow pass (dark, semi-transparent)
    draw.text((x + shadow, y + shadow), WATERMARK_TEXT,
              font=font, fill=(0, 0, 0, 130))
    # Main text (white, semi-transparent)
    draw.text((x, y), WATERMARK_TEXT,
              font=font, fill=(255, 255, 255, 195))

    return Image.alpha_composite(rgba, layer)


def save_image(result: Image.Image, path: Path):
    """Save RGBA result to path in its native format."""
    fmt = path.suffix.lower()
    if fmt in {".jpg", ".jpeg"}:
        rgb = Image.new("RGB", result.size, (255, 255, 255))
        rgb.paste(result, mask=result.split()[3])
        rgb.save(path, "JPEG", quality=JPEG_Q, optimize=True)
    elif fmt == ".png":
        result.save(path, "PNG", optimize=True)
    elif fmt == ".webp":
        result.save(path, "WEBP", quality=JPEG_Q, method=6)


def generate_thumb(rgba_img: Image.Image, original_path: Path) -> Path:
    """Save a small thumbnail (no watermark) and return its path."""
    thumb_dir = original_path.parent / "thumbs"
    thumb_dir.mkdir(exist_ok=True)
    thumb_path = thumb_dir / original_path.name

    thumb = rgba_img.copy()
    thumb.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
    save_image(thumb, thumb_path)
    return thumb_path


# ── Main ──────────────────────────────────────────────────────────────────────

used_font = find_font()
print(f"  Font: {used_font or 'PIL default (no system font found)'}")

hashes: dict = {}
if HASHES_FILE.exists():
    try:
        hashes = json.loads(HASHES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass

changed = 0
skipped = 0

for img_path in sorted(IMAGES_DIR.rglob("*")):
    # Skip thumbnails (they live in thumbs/ subdirs and are auto-generated)
    if "thumbs" in img_path.parts:
        continue
    if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        continue

    key          = img_path.relative_to(IMAGES_DIR.parent).as_posix()
    current_hash = sha256(img_path)

    # Support both old (string) and new (dict) hash format
    stored = hashes.get(key)
    stored_hash = stored if isinstance(stored, str) else (stored or {}).get("hash")
    if stored_hash == current_hash:
        skipped += 1
        continue  # already processed — never re-compress or re-watermark

    orig_size = img_path.stat().st_size

    try:
        with Image.open(img_path) as img:
            w, h = img.size
            if max(w, h) > MAX_PX:
                img.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
            final_w, final_h = img.size

            result = apply_watermark(img)

        save_image(result, img_path)
        generate_thumb(result, img_path)   # 400px thumbnail, no watermark

        new_size    = img_path.stat().st_size
        saving      = round((1 - new_size / orig_size) * 100) if orig_size else 0
        hashes[key] = {"hash": sha256(img_path), "w": final_w, "h": final_h}
        print(f"  ✓  {key}  {orig_size // 1024} KB → {new_size // 1024} KB  (−{saving}%)")
        changed += 1

    except Exception as e:
        print(f"  ⚠  {img_path.name}: {e}")

# Prune stale hashes for deleted images (exclude thumbs from live_keys)
live_keys = {
    img_path.relative_to(IMAGES_DIR.parent).as_posix()
    for img_path in IMAGES_DIR.rglob("*")
    if "thumbs" not in img_path.parts
    and img_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
}
pruned = {k for k in hashes if k not in live_keys}
if pruned:
    hashes = {k: v for k, v in hashes.items() if k in live_keys}
    print(f"  Pruned {len(pruned)} stale hash entr{'ies' if len(pruned) != 1 else 'y'}.")

HASHES_FILE.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if changed:
    print(f"\n✓  Processed {changed} image{'s' if changed != 1 else ''}  "
          f"({skipped} already up-to-date).")
else:
    print(f"✓  All {skipped} image{'s' if skipped != 1 else ''} already up-to-date — nothing to do.")

