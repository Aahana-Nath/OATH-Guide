"""Optional Firecrawl support (https://firecrawl.dev): web search and JavaScript-rendered page reads.

Enabled only when FIRECRAWL_API_KEY is set (and FIRECRAWL_DISABLE is not). Standard library only.
FIRECRAWL_API_URL overrides the endpoint (self-hosted Firecrawl, or the fake server in tests).
Everything here fails soft: on any error the caller falls back to the built-in fetcher / search.
"""
import json
import os
import re
import threading
import urllib.error
import urllib.request

DEFAULT_API = "https://api.firecrawl.dev/v2"
_lock = threading.Lock()
STATS = {"searches": 0, "scrapes": 0, "failed": 0, "urls": [], "stopped": ""}


def reset():
    with _lock:
        STATS.update({"searches": 0, "scrapes": 0, "failed": 0, "urls": [], "stopped": ""})


def enabled():
    return bool(os.environ.get("FIRECRAWL_API_KEY", "").strip()) and not os.environ.get("FIRECRAWL_DISABLE") and not STATS["stopped"]


def budget_left():
    return STATS["scrapes"] < int(os.environ.get("FIRECRAWL_MAX_SCRAPES", "25"))


def _call(path, body, timeout):
    base = os.environ.get("FIRECRAWL_API_URL", DEFAULT_API).rstrip("/")
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "Bearer " + os.environ["FIRECRAWL_API_KEY"].strip(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)[:120]}


def _stop_if_account_problem(status):
    # a bad key or no credits will not fix itself mid-run: stop calling and let the built-in fetcher take over
    if status in (401, 402, 403):
        STATS["stopped"] = {401: "invalid API key", 402: "out of credits", 403: "access denied"}[status]


def search(query, n=8):
    """URLs for a web search, or None if Firecrawl is unavailable (so the caller can use another engine)."""
    if not enabled():
        return None
    status, data = _call("/search", {"query": query, "limit": n}, 40)
    STATS["searches"] += 1
    _stop_if_account_problem(status)
    if status != 200 or not data.get("success", True):
        STATS["failed"] += 1
        return None
    d = data.get("data") or {}
    rows = d.get("web", []) if isinstance(d, dict) else d      # v2 nests under "web"; v1 returned a list
    return [r["url"] for r in rows if isinstance(r, dict) and str(r.get("url", "")).startswith("http")][:n]


def to_text(md):
    """Markdown -> plain text, so quotes match what a person sees on the page (no link syntax, emphasis or backticks)."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)
    t = re.sub(r"(\*\*|__|`)", "", t)
    return t


def scrape(url, timeout=60):
    """Render one page. Returns {"text", "title", "links"} or None. The text is plain text derived from Firecrawl's markdown."""
    if not enabled():
        return None
    status, data = _call("/scrape", {"url": url, "formats": ["markdown", "links"], "onlyMainContent": True,
                                     "timeout": timeout * 1000}, timeout + 15)
    STATS["scrapes"] += 1
    _stop_if_account_problem(status)
    d = data.get("data") if isinstance(data, dict) else None
    meta = (d or {}).get("metadata") or {}
    code = meta.get("statusCode")
    if status != 200 or not d or not d.get("markdown") or (isinstance(code, int) and code >= 400):
        STATS["failed"] += 1
        return None
    if url not in STATS["urls"]:
        STATS["urls"].append(url)
    return {"text": to_text(d["markdown"]).strip(), "title": (meta.get("title") or "").strip(),
            "links": [l for l in (d.get("links") or []) if isinstance(l, str)]}
