# Lavinia Gabriela Enache — Portfolio

Personal art and illustration portfolio at **[laviniaenache.com](https://laviniaenache.com)**, served via GitHub Pages.

Built as a single HTML/CSS/JS page with no framework or bundler. Images are processed and watermarked automatically by a Python pipeline on every push.

---

## Adding new artwork

1. Drop images into `images/<category>/` — create the subfolder if it's a new category.
2. Say **"publish the gallery"** in Copilot CLI (the skill handles everything), or just push to `main` and CI does it automatically.

Supported formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` (including animated), `.avif`, `.svg`.

Name files with a numeric prefix to control sort order: `01-sunset.jpg`, `02-portrait.png`, …

---

## How it works

```
Push images → CI runs optimize-images.py
                      generate-manifest.py
                      validate.py
           → commits processed images + manifest back to main
           → GitHub Pages deploys automatically
```

| File | Purpose |
|---|---|
| `image-manifest.json` | Generated data layer — fetched by `script.js` at runtime |
| `image-hashes.json` | SHA-256 + dimensions per image — tracks what's already processed |
| `image-dates.json` | First-seen date per image — drives the "New" badge |
| `images/<cat>/thumbs/` | 400 px WebP thumbnails, auto-generated from frame 0 |

The optimizer is **idempotent**: it skips any image whose hash is already recorded. To force reprocessing, delete the entry from `image-hashes.json`.

---

## Local development

**Requirements:** Python 3, Pillow (`pip install Pillow` — installed automatically if missing).

```bash
# Process images, rebuild manifest, validate
python optimize-images.py && python generate-manifest.py && python validate.py

# Or use the convenience scripts
./update-gallery.sh     # macOS / Linux
update-gallery.bat      # Windows
```

`validate.py` is the only test suite — it exits with code 1 on errors.

To preview the site locally, serve the repo root with any static file server:

```bash
python -m http.server 8080
# then open http://localhost:8080
```

---

## Image processing pipeline

Each image goes through (exactly once, tracked by SHA-256):

1. **EXIF rotation** normalised
2. **Resize** to max 2400 px on the longest side
3. **Watermark** burned bottom-right — *© Lavinia Gabriela Enache*
4. **Thumbnail** generated at 400 px (WebP, no watermark)

**Animated GIFs and animated WebPs** are handled separately: every frame is resized, the watermark is applied to frame 0 only, and all frame timing / loop / disposal metadata is preserved. A static thumbnail is generated from frame 0.

---

## Copilot CLI skill

The repo includes a one-command publish skill for [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli/). When a session is open in this directory, just say:

> *"publish the gallery"* or *"update the website"*

The `publish_gallery` tool will sync with GitHub, run the full pipeline, commit, and push — without requiring any git knowledge.
