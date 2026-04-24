#!/usr/bin/env python3
"""
optimize-images.py
Resizes, compresses, and watermarks images and videos in-place for web delivery.

Run:     python optimize-images.py
Requires: pip install Pillow  (installed automatically if missing)
          ffmpeg on PATH       (required for MP4 processing)

Pipeline per image (runs exactly once per unique file, tracked by SHA-256):
  1. Resize to max 2400 px on longest side
  2. Compress  (JPEG/WebP quality 85, PNG lossless)
  3. Burn watermark: "© Lavinia Gabriela Enache" — bottom-right, Playfair Display Italic
  4. Record SHA-256 of final file → stored in image-hashes.json

Animated GIF / animated WebP:
  - Every frame is resized to max 2400 px.
  - Watermark is burned onto frame 0 only.
  - A static WebP thumbnail (no watermark) is generated from frame 0.
  - Per-frame timing/loop/disposal metadata is preserved on re-save.

MP4 video:
  - First frame is extracted and used to create a WebP thumbnail with a
    play-button icon overlaid in the centre.
  - Watermark text is burned onto every frame using ffmpeg's drawtext filter.
  - Re-encoded with libx264 / yuv420p for broad browser compatibility.
  - Requires ffmpeg on PATH; files are skipped (with a warning) if not found.

On subsequent runs the hash is unchanged → step skipped entirely.
To re-process a file (e.g. after changing watermark text), delete its
entry from image-hashes.json or delete the file entirely.
"""

import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence
except ImportError:
    import sys
    print("Installing Pillow…")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "-q"])
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence

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


def find_ffmpeg() -> str | None:
    """Return the ffmpeg executable path if it is on PATH."""
    return shutil.which("ffmpeg")


def escape_drawtext(s: str) -> str:
    """Escape a string for use as a value in an ffmpeg drawtext filter.

    Order matters: backslash must be escaped first.
    expansion=none (set in the filter) disables % expansion, so % is safe.
    """
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


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
    elif fmt == ".avif":
        result.save(path, "AVIF", quality=JPEG_Q)
    elif fmt == ".gif":
        rgba_to_palette(result).save(path, "GIF", transparency=255)


_AVIF_AVAILABLE = None

def avif_available() -> bool:
    """Detect whether Pillow can write AVIF."""
    global _AVIF_AVAILABLE
    if _AVIF_AVAILABLE is not None:
        return _AVIF_AVAILABLE
    try:
        Image.new("RGB", (1, 1)).save(io.BytesIO(), "AVIF")
        _AVIF_AVAILABLE = True
    except Exception:
        _AVIF_AVAILABLE = False
    return _AVIF_AVAILABLE


def generate_avif(rgba_img: Image.Image, original_path: Path) -> Path | None:
    """Save an AVIF version next to the original and return its path."""
    if not avif_available():
        return None
    avif_path = original_path.with_suffix(".avif")
    try:
        rgba_img.save(avif_path, "AVIF", quality=JPEG_Q)
        return avif_path
    except Exception:
        return None


def generate_thumb(rgba_img: Image.Image, original_path: Path) -> Path:
    """Save a 400px WebP thumbnail (no watermark) and return its path."""
    thumb_dir = original_path.parent / "thumbs"
    thumb_dir.mkdir(exist_ok=True)
    thumb_path = thumb_dir / (original_path.stem + ".webp")

    # Remove old same-stem non-webp thumb if it exists
    for old in thumb_dir.glob(original_path.stem + ".*"):
        if old.suffix.lower() != ".webp":
            old.unlink()

    thumb = rgba_img.copy()
    thumb.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
    save_image(thumb, thumb_path)
    return thumb_path


def is_animated(img: Image.Image) -> bool:
    """Return True if the image has more than one frame."""
    try:
        return getattr(img, "n_frames", 1) > 1
    except Exception:
        return False


def rgba_to_palette(img: Image.Image) -> Image.Image:
    """Convert an RGBA image to palette (P) mode suitable for GIF output.

    Pillow's quantize() silently drops the alpha channel on RGBA images,
    so p.info["transparency"] is never set and any default is a guess.
    This helper:
      1. Composites RGB channels onto white so quantisation picks good colours.
      2. Quantises to 255 colours (palette index 255 is left free).
      3. Stamps pixels with alpha < 128 back to index 255.
      4. Sets info["transparency"] = 255 so the GIF encoder writes it correctly.
    """
    if img.mode != "RGBA":
        return img.convert("P")
    alpha = img.split()[3]
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img.convert("RGB"), mask=alpha)
    p = bg.quantize(colors=255)
    px = list(p.getdata())
    for i, a_val in enumerate(alpha.getdata()):
        if a_val < 128:
            px[i] = 255
    p.putdata(px)
    p.info["transparency"] = 255
    return p


def draw_play_icon(img: Image.Image) -> Image.Image:
    """Overlay a semi-transparent play-button (circle + triangle) in the centre."""
    rgba   = img.convert("RGBA")
    w, h   = rgba.size
    r      = max(20, min(80, int(min(w, h) * 0.18)))   # radius ≈ 18% of shorter side
    cx, cy = w // 2, h // 2

    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0, 170))

    # Triangle shifted slightly right for optical centering
    offset = int(r * 0.1)
    half   = int(r * 0.55)
    draw.polygon(
        [(cx - half + offset, cy - half),
         (cx - half + offset, cy + half),
         (cx + half + offset, cy)],
        fill=(255, 255, 255, 230),
    )

    return Image.alpha_composite(rgba, overlay)


def extract_video_frame(video_path: Path, frame_path: Path, ffmpeg_bin: str) -> None:
    """Extract a representative frame (≈1 s in, fallback frame 0) for the thumbnail."""
    for seek in ("1", "0"):
        result = subprocess.run(
            [ffmpeg_bin, "-ss", seek, "-i", str(video_path),
             "-vframes", "1", "-q:v", "2", "-y", str(frame_path)],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0:
            return
    raise subprocess.CalledProcessError(
        result.returncode, result.args, stderr=result.stderr
    )


def watermark_video(video_path: Path, ffmpeg_bin: str,
                    video_w: int, video_h: int) -> None:
    """Burn watermark text onto every frame of a video using ffmpeg drawtext.

    Re-encodes to H.264/yuv420p for maximum browser compatibility.
    Writes atomically via a temp file so partial failures leave the original intact.
    """
    font_size = max(18, min(52, int(min(video_w, video_h) * 0.025)))
    margin    = int(min(video_w, video_h) * 0.018)
    shadow    = max(1, font_size // 20)

    parts = [
        "expansion=none",                          # disable % variable expansion
        f"text='{escape_drawtext(WATERMARK_TEXT)}'",
        f"fontsize={font_size}",
        "fontcolor=white@0.76",
        "shadowcolor=black@0.51",
        f"shadowx={shadow}",
        f"shadowy={shadow}",
        f"x=w-text_w-{margin}",
        f"y=h-text_h-{margin}",
    ]

    font_path = find_font()
    if font_path and font_path.exists():
        # Convert to forward slashes; escape colon (Windows drive letters: C: → C\:)
        fp = str(font_path).replace("\\", "/").replace(":", "\\:")
        parts.insert(1, f"fontfile='{fp}'")

    vf = "drawtext=" + ":".join(parts)

    with tempfile.NamedTemporaryFile(
        dir=video_path.parent, delete=False, suffix=video_path.suffix
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        subprocess.run(
            [ffmpeg_bin, "-i", str(video_path),
             "-vf", vf,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             "-c:a", "copy",
             "-y", str(tmp_path)],
            capture_output=True, check=True, timeout=600,
        )
        tmp_path.replace(video_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def process_video(video_path: Path, ffmpeg_bin: str) -> tuple[int, int]:
    """Process an MP4 video in-place:
      - Extract a representative frame → WebP thumbnail (no baked-in icon; badge handles that).
      - Burn watermark text onto every frame (re-encode with libx264).
    Returns (w, h) of the video.
    """
    # ── 1. Extract frame to a temp JPEG ──────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        frame_path = Path(tmp.name)

    try:
        extract_video_frame(video_path, frame_path, ffmpeg_bin)

        with Image.open(frame_path) as frame_img:
            frame_img.load()
            video_w, video_h = frame_img.size
            thumb_rgba = frame_img.convert("RGBA")
            thumb_rgba.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
    finally:
        frame_path.unlink(missing_ok=True)

    # ── 2. Save thumbnail (plain frame — badge-video in the gallery indicates video) ──
    generate_thumb(thumb_rgba, video_path)

    # ── 3. Burn watermark onto every frame ────────────────────────────────────
    watermark_video(video_path, ffmpeg_bin, video_w, video_h)

    return video_w, video_h


def process_animated(img_path: Path) -> tuple[int, int]:
    """
    Process a multi-frame GIF or animated WebP in-place:
      - Resize every frame to MAX_PX.
      - Watermark frame 0 only.
      - Re-save the animated file preserving timing/loop metadata (atomic).
      - Generate a static WebP thumbnail from frame 0.
    Returns (w, h) of the first frame after resizing.
    """
    fmt = img_path.suffix.lower()

    with Image.open(img_path) as src:
        src.load()
        info = src.info.copy()  # loop, background, duration, etc.

        frames      = []
        durations   = []
        disposals   = []

        for frame in ImageSequence.Iterator(src):
            frame_info = frame.info
            dur  = frame_info.get("duration", info.get("duration", 100))
            # disposal_method is an attribute on the frame object, not in .info
            disp = getattr(frame, "disposal_method", frame_info.get("disposal_method", 2))
            durations.append(dur)
            disposals.append(disp)

            # Convert to RGBA for uniform processing
            rgba = frame.convert("RGBA")

            # Resize every frame (preserves aspect ratio)
            if max(rgba.width, rgba.height) > MAX_PX:
                rgba.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)

            frames.append(rgba)

    if not frames:
        raise ValueError("No frames found")

    final_w, final_h = frames[0].size

    # Watermark frame 0 only
    frames[0] = apply_watermark(frames[0])

    # Re-save all frames back to the original file — write atomically via temp file
    loop = info.get("loop", 0)

    with tempfile.NamedTemporaryFile(
        dir=img_path.parent, delete=False, suffix=img_path.suffix
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        if fmt == ".gif":
            # rgba_to_palette() preserves transparency correctly (quantize() drops alpha)
            p_frames = [rgba_to_palette(f) for f in frames]
            p_frames[0].save(
                tmp_path, format="GIF", save_all=True,
                append_images=p_frames[1:],
                loop=loop,
                duration=durations,
                disposal=disposals,
                optimize=False,
                transparency=255,
            )
        else:
            # Animated WebP
            frames[0].save(
                tmp_path, format="WEBP", save_all=True,
                append_images=frames[1:],
                loop=loop,
                duration=durations,
                quality=JPEG_Q,
                method=6,
            )
        tmp_path.replace(img_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    # Thumbnail written after main file is committed to disk
    generate_thumb(frames[0].copy(), img_path)

    return final_w, final_h


# ── Main ──────────────────────────────────────────────────────────────────────

used_font  = find_font()
ffmpeg_bin = find_ffmpeg()
print(f"  Font:   {used_font or 'PIL default (no system font found)'}")
print(f"  ffmpeg: {ffmpeg_bin or 'not found — MP4 files will be skipped'}")

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

    suffix = img_path.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4"}:
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
        if suffix == ".mp4":
            if ffmpeg_bin is None:
                print(f"  ⚠  {img_path.name}: ffmpeg not found — skipping (install ffmpeg and re-run).")
                continue   # Don't store hash; file will be retried on next run
            final_w, final_h = process_video(img_path, ffmpeg_bin)
            new_size = img_path.stat().st_size
            saving   = round((1 - new_size / orig_size) * 100) if orig_size else 0
            hashes[key] = {"hash": sha256(img_path), "w": final_w, "h": final_h, "video": True}
            print(f"  ✓  {key} [video]  {orig_size // 1024} KB → {new_size // 1024} KB  (−{saving}%)")
            changed += 1

        else:
            with Image.open(img_path) as img:
                animated = is_animated(img)

            if animated:
                final_w, final_h = process_animated(img_path)
            else:
                with Image.open(img_path) as img:
                    img = ImageOps.exif_transpose(img)  # fix camera rotation
                    if max(img.width, img.height) > MAX_PX:
                        img.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
                    final_w, final_h = img.size
                    result = apply_watermark(img)

                # Write atomically via temp file — prevents double-watermark on partial failure
                with tempfile.NamedTemporaryFile(
                    dir=img_path.parent, delete=False, suffix=img_path.suffix
                ) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    save_image(result, tmp_path)
                    tmp_path.replace(img_path)
                    generate_thumb(result, img_path)
                    avif_path = generate_avif(result, img_path)
                except Exception:
                    tmp_path.unlink(missing_ok=True)
                    raise

            new_size    = img_path.stat().st_size
            saving      = round((1 - new_size / orig_size) * 100) if orig_size else 0
            avif_generated = avif_path is not None and avif_path.exists()
            hashes[key] = {"hash": sha256(img_path), "w": final_w, "h": final_h,
                           **({"animated": True} if animated else {}),
                           **({"avif": True} if avif_generated else {})}
            tag = " [animated]" if animated else ""
            avif_tag = " +avif" if avif_generated else ""
            print(f"  ✓  {key}{tag}{avif_tag}  {orig_size // 1024} KB → {new_size // 1024} KB  (−{saving}%)")
            changed += 1

    except Exception as e:
        print(f"  ⚠  {img_path.name}: {e}")

# Prune stale hashes for deleted images/videos (exclude thumbs from live_keys)
live_keys = {
    img_path.relative_to(IMAGES_DIR.parent).as_posix()
    for img_path in IMAGES_DIR.rglob("*")
    if "thumbs" not in img_path.parts
    and img_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4"}
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

