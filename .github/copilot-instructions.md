# Copilot Instructions

## What this project is

Static artist portfolio for Lavinia Gabriela Enache — no framework, no bundler, no package manager. The site is a single HTML/CSS/JS page served from GitHub Pages at `laviniaenache.com`.

## Commands

```bash
# Process new images (resize → watermark → generate thumbnails)
python optimize-images.py

# Rebuild the manifest and sitemap (run after optimize-images.py)
python generate-manifest.py

# Both steps together (local workflow script)
./update-gallery.sh            # macOS/Linux
update-gallery.bat             # Windows

# Validate generated output (same checks CI runs)
python validate.py
```

`validate.py` exits with code 1 on errors — it is also the CI gate. No other test runner exists.

## Architecture

The gallery is data-driven: `script.js` fetches `image-manifest.json` at runtime and renders everything dynamically. `index.html` is just the shell.

```
images/
  <category-slug>/          ← each subfolder = one gallery category
    01-painting.jpg         ← numeric prefix controls sort order
    thumbs/
      01-painting.webp      ← 400 px WebP thumbnail (auto-generated)
image-manifest.json         ← generated; consumed by script.js via fetch()
image-hashes.json           ← SHA-256 + dimensions of processed images (idempotency state)
image-dates.json            ← first-seen date per image (drives "New" badge)
```

**CI pipeline** (`.github/workflows/update-manifest.yml`) triggers on pushes to `main` that touch `images/**`:
1. `optimize-images.py` — resize to max 2400 px, burn watermark, create `thumbs/*.webp`
2. `generate-manifest.py` — scan `images/`, write manifest + sitemap + OG preview
3. `validate.py` — sanity-check all outputs
4. Commit changed assets back to `main`, then deploy to GitHub Pages

## Key conventions

### Image processing
- `optimize-images.py` is **idempotent**: it skips any image whose SHA-256 is already in `image-hashes.json`. To force reprocessing, delete the entry from that file.
- Thumbnails live at `images/<category>/thumbs/<stem>.webp`. `script.js` uses the thumbnail for the grid and the full image for the lightbox.
- `image-hashes.json` stores `{hash, w, h}` per image. The `w`/`h` values are read by `generate-manifest.py` and embedded in the manifest so the browser can pre-reserve aspect-ratio space (preventing CLS).

### Gallery categories
- Each subfolder of `images/` becomes a category. The slug is the folder name; the display label is derived by splitting on `-`/`_` and capitalising each word.
- Files named with a leading numeric prefix (`01-`, `02_`, `003 `, etc.) are sorted by that number; the prefix is stripped from the displayed alt text.
- Images placed directly in `images/` (no subfolder) appear under "General".

### Theming
- Dark/light theme is stored in `localStorage` under key `lgfe-theme` and applied via `document.documentElement.dataset.theme` before CSS loads (inline script in `<head>` prevents flash).
- All theme colours are CSS custom properties on `:root` and `[data-theme="light"]`; accent colour is `--accent: #c9a96e` (dark) / `#b5843a` (light).

### Front-end
- The gallery renders in batches of 24 (`BATCH_SIZE`) using `IntersectionObserver` on a sentinel element for infinite scroll.
- Layout is pure CSS masonry: `columns: 3 280px; column-gap: var(--gap)`.
- Image right-click and drag are suppressed (artist copyright protection).
- "New" badge appears on images added within the last 30 days (date tracked in `image-dates.json`).

### Adding new images
1. Drop images into `images/<category>/` (create the subfolder if needed).
2. Run `python optimize-images.py && python generate-manifest.py` locally **or** just push — CI does it automatically.
3. Never manually edit `image-manifest.json`, `image-hashes.json`, or `image-dates.json`; they are always machine-generated.
