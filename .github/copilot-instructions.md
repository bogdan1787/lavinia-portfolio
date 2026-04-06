# Copilot Instructions

## What this project is

Static artist portfolio for Lavinia Gabriela Enache — no framework, no bundler, no package manager. The site is a single HTML/CSS/JS page served from GitHub Pages at `laviniaenache.com`.

## Commands

```bash
# Process new images (resize → watermark → generate thumbnails)
python optimize-images.py

# Rebuild the manifest and sitemap (run after optimize-images.py)
python generate-manifest.py

# Both steps together (local workflow scripts)
./update-gallery.sh            # macOS/Linux
update-gallery.bat             # Windows

# Validate generated output (same checks CI runs)
python validate.py
```

`validate.py` exits with code 1 on errors — it is the CI gate. No other test runner exists.

**Preferred workflow for publishing:** use the `publish_gallery` tool (Copilot CLI skill — see below). It handles git sync, all Python steps, commit, and push in one call.

## Architecture

The gallery is data-driven: `script.js` fetches `image-manifest.json` at runtime and renders everything dynamically. `index.html` is just the shell.

```
images/
  <category-slug>/          ← each subfolder = one gallery category
    01-painting.jpg         ← numeric prefix controls sort order
    thumbs/
      01-painting.webp      ← 400 px WebP thumbnail (auto-generated)
image-manifest.json         ← generated; consumed by script.js via fetch()
image-hashes.json           ← {hash, w, h, animated?} per image (idempotency state)
image-dates.json            ← first-seen date per image (drives "New" badge)
.github/extensions/
  update-gallery/
    extension.mjs           ← Copilot CLI skill: one-command publish tool
```

**CI pipeline** (`.github/workflows/update-manifest.yml`) triggers on pushes to `main` that touch `images/**`, `index.html`, `style.css`, `script.js`, or the Python scripts:
1. `optimize-images.py` — resize to max 2400 px, burn watermark, create `thumbs/*.webp`
2. `generate-manifest.py` — scan `images/`, write manifest + sitemap + OG preview
3. `validate.py` — sanity-check all outputs
4. Commit changed assets back to `main`, then deploy to GitHub Pages

## Key conventions

### Image processing
- `optimize-images.py` is **idempotent**: it skips any image whose SHA-256 is already in `image-hashes.json`. To force reprocessing, delete the entry from that file.
- Thumbnails live at `images/<category>/thumbs/<stem>.webp`. `script.js` uses the thumbnail for the grid and the full image in the lightbox.
- `image-hashes.json` stores `{hash, w, h, animated?}` per image. `w`/`h` are embedded in the manifest so the browser can pre-reserve aspect-ratio space (prevents CLS). `animated: true` is written by the optimizer and read by `generate-manifest.py` — Pillow is not imported in the manifest script.
- Writes are **atomic**: images are saved to a `tempfile.NamedTemporaryFile` in the same directory, then atomically renamed. The thumbnail is written only *after* the main file is committed, so a failed write never leaves the thumb ahead of the image.
- EXIF orientation is normalised with `ImageOps.exif_transpose()` before any resize or watermark.

### Animated GIF / animated WebP
- `is_animated()` checks `img.n_frames > 1`. Animated files are routed to `process_animated()` instead of the static pipeline.
- Every frame is resized to `MAX_PX`; the watermark is burned onto **frame 0 only**.
- The static WebP thumbnail is generated from watermarked frame 0 (no watermark on frames 1+).
- GIF frames are converted RGBA → palette via `rgba_to_palette()`, which composites onto white, quantizes to 255 colours, then stamps transparent pixels to palette index 255. Do **not** use `quantize()` directly on RGBA — Pillow silently drops alpha.
- `animated: true` is set in `image-hashes.json` and propagated to `image-manifest.json`. In `script.js`, this field must be threaded through **both** `buildGallery()` and `buildRenderQueue()` — both reconstruct image objects from raw manifest data. The lightbox uses a native `<img>` tag for animated files; the browser handles playback.
- A `▶` badge (`.badge-anim` in CSS) is rendered in the grid for animated images.

### Gallery categories
- Each subfolder of `images/` becomes a category. The slug is the folder name; the display label is derived by splitting on `-`/`_` and capitalising each word.
- Files with a leading numeric prefix (`01-`, `02_`, `003 `, etc.) are sorted by that number; the prefix is stripped from the displayed alt text.
- Images placed directly in `images/` (no subfolder) appear under "General".

### Theming
- Dark/light theme is stored in `localStorage` under key `lgfe-theme` and applied via `document.documentElement.dataset.theme` before CSS loads (inline `<script>` in `<head>` prevents flash).
- All theme colours are CSS custom properties on `:root` and `[data-theme="light"]`; accent colour is `--accent: #c9a96e` (dark) / `#b5843a` (light).

### Front-end
- The gallery renders in batches of 24 (`BATCH_SIZE`) using `IntersectionObserver` on a sentinel element for infinite scroll.
- Layout is pure CSS masonry: `columns: 3 280px; column-gap: var(--gap)`.
- Image right-click and drag are suppressed (artist copyright protection).
- "New" badge appears on images added within the last 30 days (date tracked in `image-dates.json`).

### validate.py checks
Per-image: `file`, `alt`, `added` fields present; file exists on disk and is non-empty; `file` and `thumb` paths start with `images/`; `animated: true` only on `.gif`/`.webp`; `w`/`h` are positive non-boolean integers; declared `thumb` path exists on disk. Global: OG preview has `FF D8` JPEG magic bytes; sitemap is valid XML with `<url>` entries.

### Copilot CLI skill — `publish_gallery`
`.github/extensions/update-gallery/extension.mjs` registers a `publish_gallery` tool available in any Copilot CLI session for this repo. When the artist says "publish" or "update the website", call this tool — it runs the full pipeline (git pull --rebase --autostash → optimize → generate → validate → commit → push) without requiring any git knowledge. Merge conflicts are surfaced with a plain-English recovery message.

### Adding new images
1. Drop images into `images/<category>/` (create the subfolder if needed). Supported formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.avif`, `.svg`.
2. Say "publish the gallery" (Copilot CLI will use the skill) **or** run `python optimize-images.py && python generate-manifest.py` locally **or** just push — CI runs automatically.
3. Never manually edit `image-manifest.json`, `image-hashes.json`, or `image-dates.json`; they are always machine-generated.
