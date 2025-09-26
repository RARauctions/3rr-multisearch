#!/usr/bin/env bash
set -e

# Ensure pyppeteer downloads Chromium into a writeable cache
export PYPPETEER_HOME="${PYPPETEER_HOME:-/opt/render/project/.pyppeteer}"
mkdir -p "$PYPPETEER_HOME"

python - <<'PY'
import asyncio, os
from pyppeteer import chromium_downloader as cd

# Pre-download Chromium so it doesn't try at first request
async def main():
    # use linux-x64 revision cached by pyppeteer
    rev = cd.chromium_revision
    path = cd.chromium_executable()
    if not os.path.exists(path):
        print("Downloading Chromium (one-time)...")
        await cd.download_chromium()
    else:
        print("Chromium already present:", path)

asyncio.get_event_loop().run_until_complete(main())
PY

# Start the app
exec gunicorn app:app --timeout 120 --workers 2 --threads 4 --bind 0.0.0.0:$PORT
