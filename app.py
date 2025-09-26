from flask import Flask, request, render_template_string
import requests, time, re, html
from bs4 import BeautifulSoup

# ---------- Site configuration ----------
BASE = "https://rarauctions.bidwrangler.com"
INDEX_URL = f"{BASE}/ui/complete"
HEADERS = {"User-Agent": "RRAggregator/1.0 (+https://rarauctions.com)"}

# ---------- Flask app ----------
app = Flask(__name__)

# ---------- HTML template ----------
PAGE = """
<!doctype html><meta charset="utf-8">
<title>R&R Multi-Catalog Search</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px}
h1{margin:0 0 12px}
form{display:flex;gap:8px;margin:12px 0 20px}
input[type=text]{flex:1;padding:10px;border:1px solid #ccc;border-radius:10px}
button{padding:10px 16px;border:0;border-radius:10px;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,.08)}
.grid{display:grid;grid-template-columns:120px 1fr;gap:10px;align-items:center;border-bottom:1px solid #eee;padding:10px 0}
img{max-width:120px;height:auto;border-radius:8px}
.meta{color:#666;font-size:12px}
small.muted{color:#666}
.note{background:#fff8c5;border:1px solid #f1e58a;padding:8px 12px;border-radius:8px;margin:8px 0}
</style>

<h1>R&R Multi-Catalog Search</h1>
<form method="get">
  <input type="text" name="q" value="{{q or ''}}" placeholder="Search term (e.g., whistle, lantern, book)" autofocus>
  <button>Search</button>
</form>

{% if discovered %}
  <p><small class="muted">Discovered {{discovered|length}} auction(s): {{ discovered|join(', ') }}</small></p>
{% else %}
  <div class="note">No auctions discovered from the index yet. Try running a search anyway; if this persists, reload in ~10s (first boot warms up the headless browser).</div>
{% endif %}

{% if q is not none %}
  <p><strong>{{results|length}}</strong> result(s) for “{{q}}”.</p>
  {% for r in results %}
    <div class="grid">
      <div>{% if r.thumb %}<img src="{{r.thumb}}" loading="lazy" alt="thumb">{% endif %}</div>
      <div>
        <div><a href="{{r.lot_url}}" target="_blank" rel="noopener">{{r.title or '(Untitled lot)'}}</a></div>
        <div class="meta">Auction {{r.auction_id}}{% if r.lot_number %} · {{r.lot_number}}{% endif %} · <a href="{{r.query_url}}" target="_blank" rel="noopener">open in auction</a></div>
      </div>
    </div>
  {% endfor %}
{% endif %}
"""

# ---------- Helpers ----------
def _extract_ids(html_text: str) -> list[int]:
    """Find auction IDs in any HTML/text via regex."""
    return sorted({int(m.group(1)) for m in re.finditer(r"/ui/auctions/(\d+)", html_text)})

def _render_js(url: str, timeout: int = 60) -> str:
    """
    Render a JS-driven page using requests_html + pyppeteer.
    Requires requirements.txt pins and the start.sh pre-download on Render.
    """
    try:
        from requests_html import HTMLSession
    except Exception:
        return ""
    sess = HTMLSession()
    r = sess.get(url, timeout=timeout)
    # Important flags for containerized hosts; larger timeout for cold starts
    r.html.render(
        timeout=timeout * 1000,
        sleep=1.0,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"]
    )
    return r.html.html or ""

def discover_auctions() -> list[int]:
    """
    Discover all auction IDs from the index.
    Tries static HTML first; if empty, falls back to JS-render.
    """
    try:
        r = requests.get(INDEX_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        ids = _extract_ids(r.text)
        if ids:
            return ids
    except Exception:
        pass

    # Fallback to headless render if static fetch didn't find IDs
    rendered = _render_js(INDEX_URL, timeout=60)
    return _extract_ids(rendered) if rendered else []

def parse_results(html_text: str, auction_id: int, query_url: str) -> list[dict]:
    """Extract lot links/titles/thumbs/lot numbers from an auction search HTML."""
    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    for a in soup.select('a[href*="/ui/lots/"]'):
        href = a.get("href") or ""
        if "/ui/lots/" not in href:
            continue
        lot_url = href if href.startswith("http") else f"{BASE}{href}"
        title = a.get_text(strip=True)
        if not title:
            p = a.find_parent()
            title = (p.get_text(" ", strip=True)[:200] if p else "")

        thumb = ""
        img = a.find("img") or (a.find_parent().find("img") if a.find_parent() else None)
        if img and img.get("src"):
            src = img["src"]
            thumb = src if src.startswith("http") else f"{BASE}{src}"

        lot_no = ""
        ctx = a.find_parent()
        if ctx:
            txt = ctx.get_text(" ", strip=True)
            m = re.search(r"(Lot\s*#?\s*\d+|\b#\s*\d+)", txt, re.I)
            lot_no = m.group(0) if m else ""

        items.append({
            "auction_id": auction_id,
            "query_url": query_url,
            "lot_url": lot_url,
            "lot_number": lot_no,
            "title": title or "(Untitled)",
            "thumb": thumb
        })
    return items

def fetch_results(aid: int, query: str) -> list[dict]:
    """
    Fetch one auction's results for the query.
    Try static HTML first; if empty, render with headless.
    """
    qurl = f"{BASE}/ui/auctions/{aid}?query={requests.utils.quote(query)}"
    try:
        r = requests.get(qurl, headers=HEADERS, timeout=40)
        r.raise_for_status()
        items = parse_results(r.text, aid, qurl)
        if items:
            return items
    except Exception:
        pass

    rendered = _render_js(qurl, timeout=60)
    return parse_results(rendered, aid, qurl) if rendered else []

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    q = request.args.get("q")
    discovered = discover_auctions()

    # Optional: limit to most recent N auctions during testing
    # discovered = discovered[-40:]

    results = []
    if q and q.strip():
        for aid in discovered:
            try:
                results.extend(fetch_results(aid, q.strip()))
            except Exception:
                # Swallow per-auction errors to keep the page responsive
                pass
            time.sleep(0.4)  # be a good citizen
    return render_template_string(PAGE, q=q, results=results, discovered=discovered)

@app.get("/health")
def health():
    return {"ok": True}
