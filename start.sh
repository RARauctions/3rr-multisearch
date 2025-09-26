#!/usr/bin/env bash
set -e

# Cache Chromium in a writeable path
export PYPPETEER_HOME="${PYPPETEER_HOME:-/opt/render/project/.pyppeteer}"
mkdir -p "$PYPPETEER_HOME"

# Pre-download Chromium so first request is fast/reliable
python - <<'PY'
import asyncio, os
from pyppeteer.chromium_downloader import download_chromium, chromium_executable

async def main():
    path = chromium_executable()
    if not os.path.exists(path):
        print("Downloading Chromium (one-time)...")
        await download_chromium()
    else:
        print("Chromium already present:", path)

asyncio.run(main())
PY

# Start Gunicorn
exec gunicorn app:app --timeout 120 --workers 2 --threads 4 --bind 0.0.0.0:$PORT
