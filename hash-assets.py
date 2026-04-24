#!/usr/bin/env python3
"""
hash-assets.py
Adds a cache-busting query string (?v=<short-sha>) to style.css and script.js
references in index.html. Run in CI after manifest generation.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = ROOT / "index.html"

def get_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()

def main():
    if not INDEX.exists():
        print("index.html not found")
        return

    sha = get_git_sha()
    html = INDEX.read_text(encoding="utf-8")

    # Replace style.css and script.js references with cache-busted versions
    html = html.replace('href="style.css"', f'href="style.css?v={sha}"')
    html = html.replace('src="script.js"', f'src="script.js?v={sha}"')

    INDEX.write_text(html, encoding="utf-8")
    print(f"✓  Cache-busted assets with ?v={sha}")

if __name__ == "__main__":
    main()
