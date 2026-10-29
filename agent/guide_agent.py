#!/usr/bin/env python3
"""Research agent: give it an app name or website, get an OAuth setup guide in guide.schema.json format.

How it works (no search engine needed):
  1. discover  - guess docs URLs from the domain, read the homepage links, sitemap/llms.txt,
                 and ask Gemini for URL suggestions (suggestions are only candidates, never evidence)
  2. crawl     - fetch pages ourselves, following the links most likely to cover OAuth, review,
                 requirements and limits, within a page and time budget
  3. extract   - Gemini reads the fetched text and returns findings, each with a verbatim quote
  4. verify    - CODE checks every quote against the fetched text; unverifiable claims are dropped
  5. explore   - an agent loop: Gemini sees the checklist of what is still missing, picks a tool (fetch_page,
                 list_links, search_pages, record_finding, finish), sees the result, and repeats until the
                 checklist is covered or the step / time budget runs out. record_finding goes through the same
                 quote check as step 4.
  6. assemble  - verified findings become Official-docs claims; gaps become Unknown

The agent only labels something "Tested" when its own live probe observed it (source type agent_probe). Registering, installing
or submitting an app needs a person's account and is never attempted; those steps are handed to the developer.

Usage:
  export GEMINI_API_KEY="your-key"
  python3 guide_agent.py linear.app --out linear.json
Options: --model ID  --max-pages N  --max-seconds N  --max-steps N  --no-probes  --trace trace.json  --schema guide.schema.json
Live probes (agent/probes.py) run after the reading: read-only GETs that check the provider's OAuth metadata, how the
authorize endpoint answers an unregistered client, and whether the developer portal sits behind a sign-in wall. What
they observe becomes "Tested" claims (source type agent_probe). Registering or submitting an app is never attempted.
Standard library only (jsonschema is used for validation if installed).
"""
import argparse
import heapq
import json
import os
import re
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gcp_secrets import get_gemini_api_key
from netguard import host_is_public, open_url
from probes import apply_probes, run_probes

UA = "OAuthGuideAgent/0.1 (research prototype; reads public developer docs)"
BASE = "https://generativelanguage.googleapis.com/v1beta"
TODAY = date.today().isoformat()
MAX_BYTES = 2_000_000
PAGE_CHARS = 24_000          # characters of each page sent to the model
BATCH = 3                    # pages per extraction call
NOISE = re.compile(r"/reference/(methods|scopes|events|block|objects)|/changelog|/release-notes|/blog|/features|/pricing|"
                   r"/customers|/resources|/solutions|/intl/|/sdk|/community|/careers|/legal|/security/|/trust|/admins|/tools/", re.I)
DOCHOST = re.compile(r"^(docs|developers?|dev|api|platform|apidocs)\.", re.I)
LIM_GOOD_RE = re.compile(r"oauth|token|authori[sz]|code|expire|rate limit|per minute|per hour|per second|redirect|secret|rotat", re.I)
LIM_BAD_RE = re.compile(r"review|feedback|submission|workspaces?\b|deliver|character|description|image|video|words?\b|shortcut|slash command|unfurl|kilobyte|display_name|manifest|\bname length|megabyte|mb\b", re.I)
STEP_ALLOW = re.compile(r"quickstart|getting-started|creating|create|install|register|manifest|app-settings|distribution|publish|submit|setup|set-up|build", re.I)
REG_PAGE = re.compile(r"quickstart|getting-started|creating|create|manifest|app-settings|register|install", re.I)
STEP_DENY = re.compile(r"verifying|enterprise|events|webhook|signing|rate-limit|tokens|scopes|reference|agent|mcp|admins", re.I)
# a section counts as covered only when it has at least this many verified claims
MIN_COUNTS = {"step": 6, "requirement_register": 3, "requirement_public": 4, "review_stage": 2,
              "limit": 4, "access_tier": 2, "blocker": 3}
# topics a complete guide needs; the crawl keeps going until each has pages
TOPICS = {
    "review":   ["app review", "marketplace", "review guide", "submit", "submission", "approval", "listing", "publish", "directory", "review process"],
    "public":   ["distribution", "distribute", "public", "marketplace", "guidelines", "requirements", "listing", "app directory", "go live", "production"],
    "register": ["create app", "create an app", "register", "quickstart", "getting started", "manifest", "app management", "build your first", "oauth app"],
    "types":    ["token types", "bot token", "user token", "app types", "types of", "manifest", "starter app", "getting started", "quickstart", "installing"],
    "ladder":   ["distribution", "distribute", "manage distribution", "public distribution", "share your app", "app lifecycle", "lifecycle", "listing"],
    "limits":   ["rate limit", "rate-limit", "ratelimit", "limits", "quota", "throttl"],
}




RUN_ERRORS = []      # model calls that failed during this run (shown in the guide, never hidden)


def log(stage, msg):
    """Progress line. In the website this becomes a streamed event."""
    print(f"[{stage}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- HTML -> text

class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}
    CHROME = {"nav", "footer", "aside", "header"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "pre",
             "section", "article", "table", "ul", "ol", "blockquote", "dt", "dd", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.title = [], [], ""
        self._skip = self._chrome = 0
        self._in_title = False
        self._a = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.CHROME:
            self._chrome += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            href = dict(attrs).get("href")
            self._a = [href, []] if href else None
        if tag in self.BLOCK and not self._skip and not self._chrome:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.CHROME:
            self._chrome = max(0, self._chrome - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._a:
            self.links.append((self._a[0], " ".join(self._a[1]).strip()))
            self._a = None
        if tag in self.BLOCK and not self._skip and not self._chrome:
            self.text.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._a is not None and data.strip():
            self._a[1].append(data.strip())
        if not self._chrome:
            self.text.append(data)


def clean_text(parts):
    t = "".join(parts)
    t = t.replace("\u00ad", "")
    t = re.sub(r"(?<=[A-Za-z])[\u200b\u2060\ufeff](?=[A-Za-z])", " ", t)   # invisible separators between words
    t = re.sub(r"[\u200b\u2060\ufeff]", "", t)
    t = re.sub(r"[ \t\r\f\v ]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


# ---------------------------------------------------------------- fetching

_robots = {}
_cache = {}


def allowed_by_robots(url):
    p = urllib.parse.urlparse(url)
    key = f"{p.scheme}://{p.netloc}"
    if key not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(key + "/robots.txt", headers={"User-Agent": UA})
            with open_url(req, 8) as r:
                rp.parse(r.read(200_000).decode("utf-8", "replace").splitlines())
        except Exception:
            rp = None            # no robots.txt (or unreachable): allowed
        _robots[key] = rp
    rp = _robots[key]
    return True if rp is None else rp.can_fetch(UA, url)


def norm_url(u):
    u, _ = urllib.parse.urldefrag(u)
    return u.rstrip("/") if urllib.parse.urlparse(u).path not in ("", "/") else u.rstrip("/")


def fetch(url, timeout=12):
    """Return a page dict, or None if blocked, missing, binary or unreachable."""
    url = norm_url(url)
    if url in _cache:
        return _cache[url]
    page = None
    try:
        if allowed_by_robots(url):
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,text/plain,text/markdown,*/*;q=0.5"})
            with open_url(req, timeout) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                if r.status == 200 and any(x in ctype for x in ("html", "text/", "xml", "markdown")):
                    raw = r.read(MAX_BYTES)
                    m = re.search(r"charset=([\w-]+)", ctype)
                    body = raw.decode(m.group(1) if m else "utf-8", "replace")
                    final = norm_url(r.geturl())
                    if "html" in ctype:
                        pp = PageParser()
                        pp.feed(body)
                        text, title = clean_text(pp.text), pp.title.strip()
                        links = []
                        for href, label in pp.links:
                            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                                continue
                            links.append((norm_url(urllib.parse.urljoin(final + "/", href)), label))
                    else:
                        text, title, links = body.strip(), "", []
                    thin = len(text) < 600 or ("enable javascript" in text.lower() and len(text) < 2000)
                    page = {"url": final, "title": title, "text": text, "links": links, "thin": thin, "ctype": ctype}
    except Exception:
        page = None
    _cache[url] = page
    return page


# ---------------------------------------------------------------- scoring

KEYWORDS = {
    "oauth": 4, "authorization": 3, "authentication": 3, "authorize": 2, "app review": 4, "review": 2,
    "marketplace": 3, "publish": 2, "listing": 2, "verification": 3, "verify": 2, "scopes": 3, "scope": 2,
    "rate limit": 3, "rate-limit": 3, "ratelimit": 3, "register": 3, "create app": 3, "create an app": 3,
    "requirements": 3, "guidelines": 2, "distribution": 3, "distribute": 2, "approval": 3, "submit": 2,
    "permissions": 2, "app directory": 3, "client id": 2, "redirect": 2,
    "quickstart": 3, "getting started": 3, "app settings": 2, "manifest": 2, "install": 2,
    "quota": 3, "extended": 2, "extension": 2, "allowlist": 2, "development mode": 2,
}
# pages that are about OAuth / registering or publishing an app (used to keep unrelated product docs out of the guide)
TOPIC_RE = re.compile(
    r"oauth|client[ _-]?(id|secret)|redirect[ _]uri|callback url|register(ing)? (an?|your|the|a new) (app|application|integration|connection)|"
    r"create (an?|your|a new) (app|application|integration|connection)|app (manifest|review|directory|listing|marketplace|store)|"
    r"(app|apps|integration|integrations|slack) marketplace|marketplace (listing|review|submission|requirements|app|apps)|"
    r"submit(ting)? (your|an?) (app|application|integration)|authorization code|developer (portal|dashboard)", re.I)
# a requirement phrased as "to <do X>..." / "if you..." applies only in that case
COND_RE = re.compile(r"^\W*(to (offer|sell|publish|list|charge|enable|distribute|monetize)|if (you|your|the app)|when (you|your))\b", re.I)
# a review stage only counts as a wait if its text states a duration
DURATION_RE = re.compile(
    r"\b\d+(?:\s*(?:-|–|to)\s*\d+)?\s*(?:business\s+|working\s+|calendar\s+)?(?:minutes?|hours?|days?|weeks?|months?)\b"
    r"|\b(?:a|an|one|two|three|four|five|six|seven|eight|ten|few|several)\s+(?:business\s+|working\s+)?(?:minutes?|hours?|days?|weeks?|months?)\b"
    r"|\b(?:immediately|instantly|same[- ]day|real[- ]time)\b", re.I)
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".zip", ".mp4", ".css", ".js", ".ico", ".woff", ".woff2")
DOC_HINT = re.compile(r"developer|docs|documentation|\bapi\b|integration|platform|apps?\b", re.I)


def score(text):
    t = (text or "").lower()
    return sum(w for k, w in KEYWORDS.items() if k in t)


def link_score(url, label):
    path = urllib.parse.urlparse(url).path
    sc = score(label) * 2 + score(path.replace("-", " ").replace("_", " ").replace("/", " "))
    return sc - (8 if NOISE.search(path) else 0)


def topic_score(topic, url, label, text=""):
    blob = (urllib.parse.urlparse(url).path.replace("-", " ").replace("_", " ") + " " + (label or "") + " " + text[:1500]).lower()
    sc = sum(3 for k in TOPICS[topic] if k in blob)
    return sc - (8 if NOISE.search(urllib.parse.urlparse(url).path) else 0)


def root_domain(host):
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) > 2 else host


# ---------------------------------------------------------------- Gemini

def _post(model, body, key):
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent", data=json.dumps(body).encode(),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get('GEMINI_TIMEOUT', '240'))) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": {"message": str(e)}}


def pick_model(key):
    req = urllib.request.Request(f"{BASE}/models?pageSize=200", headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    skip = ("live", "image", "tts", "audio", "transcribe", "embedding", "veo", "lyria", "omni")
    names = [m["name"].split("/", 1)[1] for m in data.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"].lower()
             and not any(s in m["name"].lower() for s in skip)]
    if not names:
        raise RuntimeError("No Flash model found; pass --model with an ID from AI Studio.")
    return sorted(names)[-1]


def gemini_json(prompt, schema, model, retries=6):
    """One model call that must return JSON matching `schema`. No tools: the model only reads what we pass.
    Transient failures (timeouts, 429/500/503) are retried with growing, jittered waits; after 3 failures one
    fallback model (GEMINI_FALLBACK, default gemini-flash-lite-latest) is tried so one flaky model can't sink a run."""
    import random
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    fallback = os.environ.get("GEMINI_FALLBACK", "gemini-flash-lite-latest")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "temperature": 0}}
    cur = model
    for attempt in range(retries):
        status, data = _post(cur, body, key)
        if status == 200:
            cand = (data.get("candidates") or [{}])[0]
            text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            try:
                return json.loads(text)
            except ValueError:
                status, data = 500, {"error": {"message": "model returned invalid JSON"}}
        if status in (0, 429, 500, 503):
            wait = min(60, 6 * 2 ** attempt) + random.uniform(0, 3)
            why = (data.get("error", {}) or {}).get("message", "")[:80]
            if attempt == 2 and fallback and fallback != cur:
                cur = fallback
                log("model", f"switching to fallback model {cur}")
            log("model", f"HTTP {status}{' (' + why + ')' if why else ''}, retry {attempt + 1}/{retries - 1} in {wait:.0f}s")
            time.sleep(wait)
            continue
        raise RuntimeError(f"Gemini error {status}: {data.get('error', {}).get('message', '')[:300]}")
    raise RuntimeError("Gemini stayed unavailable or over quota after retries.")


URL_SCHEMA = {"type": "OBJECT", "properties": {"urls": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["urls"]}

CATEGORIES = ["requirement_register", "requirement_public", "limit", "blocker", "review_stage",
              "access_tier", "setup_type", "creation_path", "recommendation", "step", "extra"]
FINDINGS_SCHEMA = {"type": "OBJECT", "properties": {"findings": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "category": {"type": "STRING", "enum": CATEGORIES},
    "item": {"type": "STRING"}, "value": {"type": "STRING"},
    "status": {"type": "STRING", "enum": ["required", "optional", "not_asked", "unknown"]},
    "fix": {"type": "STRING"}, "text": {"type": "STRING"}, "quote": {"type": "STRING"}, "page_id": {"type": "INTEGER"},
}, "required": ["category", "text", "quote", "page_id"]}}}, "required": ["findings"]}

LEVELS = ["easy", "medium", "hard", "unknown"]
JUDGE_SCHEMA = {"type": "OBJECT", "properties": {
    "summary": {"type": "STRING"},
    "start_level": {"type": "STRING", "enum": LEVELS}, "start_reason": {"type": "STRING"},
    "public_level": {"type": "STRING", "enum": LEVELS}, "public_reason": {"type": "STRING"},
    "agent_tasks": {"type": "ARRAY", "items": {"type": "STRING"}},
    "human_tasks": {"type": "ARRAY", "items": {"type": "STRING"}},
}, "required": ["summary", "start_level", "start_reason", "public_level", "public_reason", "agent_tasks", "human_tasks"]}


# ---------------------------------------------------------------- 1. discover

BRAND_CASE = {"github": "GitHub", "gitlab": "GitLab", "linkedin": "LinkedIn", "youtube": "YouTube", "paypal": "PayPal", "hubspot": "HubSpot",
              "docusign": "DocuSign", "openai": "OpenAI", "bitbucket": "Bitbucket", "zendesk": "Zendesk", "mailchimp": "Mailchimp"}


def parse_target(raw):
    s = raw.strip()
    if not re.match(r"^https?://", s):
        s = "https://" + s
    u = urllib.parse.urlparse(s)
    host = (u.hostname or "").lower()
    label = root_domain(host).split(".")[0]
    return {"origin": f"{u.scheme}://{u.netloc}", "host": host, "root": root_domain(host),
            "name": host if re.match(r"^[\d.]+$|^localhost$", host) else BRAND_CASE.get(label, label.replace("-", " ").title())}


def resolve_bare_name(raw):
    """'Linear' with no dot: try common top-level domains."""
    if "." in raw or "/" in raw:
        return raw
    for tld in ("com", "io", "app", "dev", "co"):
        cand = f"{raw.strip().lower().replace(' ', '')}.{tld}"
        if fetch(f"https://{cand}", timeout=6):
            log("discover", f"'{raw}' looks like {cand}")
            return cand
    return raw


LOCALE = re.compile(r"^/(de|fr|es|sv|vi|tr|ja|ko|pt|it|nl|ru|zh|pl|id|th|ar|he|cs|da|fi|nb|no|hu|ro|uk|el|ms|tl|hi|bg|hr|sk|sl|lt|lv|et)(-[a-z]{2,4})?(/|$)", re.I)


def foreign_locale(u):
    return bool(LOCALE.match(urllib.parse.urlparse(u).path))


def web_search(query, n=8):
    """Search the web. Uses TAVILY_API_KEY or BRAVE_API_KEY if set, else DuckDuckGo's HTML page (no key). Returns URLs."""
    try:
        if os.environ.get("TAVILY_API_KEY"):
            req = urllib.request.Request("https://api.tavily.com/search", method="POST",
                                         data=json.dumps({"api_key": os.environ["TAVILY_API_KEY"], "query": query, "max_results": n}).encode(),
                                         headers={"Content-Type": "application/json"})
            return [r["url"] for r in json.load(urllib.request.urlopen(req, timeout=15)).get("results", [])]
        if os.environ.get("BRAVE_API_KEY"):
            req = urllib.request.Request("https://api.search.brave.com/res/v1/web/search?count=%d&q=%s" % (n, urllib.parse.quote(query)),
                                         headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"], "Accept": "application/json"})
            return [r["url"] for r in json.load(urllib.request.urlopen(req, timeout=15)).get("web", {}).get("results", [])]
        req = urllib.request.Request("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query), headers={"User-Agent": UA})
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
        out = []
        for m in re.finditer(r'href="([^"]*uddg=[^"]+)"', html):
            u = urllib.parse.parse_qs(urllib.parse.urlparse(html_unescape(m.group(1))).query).get("uddg", [""])[0]
            if u.startswith("http") and u not in out:
                out.append(u)
        return out[:n]
    except Exception as e:
        log("search", f"web search unavailable: {str(e)[:100]}")
        return []


def html_unescape(x):
    import html
    return html.unescape(x)


EXTRA_LINKS = []     # doc URLs found in sitemaps; the crawler treats them as links from the seed pages


def sitemap_urls(t, hosts):
    """robots.txt Sitemap lines + /sitemap.xml on each docs host, following sitemap indexes (max 8 files)."""
    todo, done, urls = [], set(), []
    for h in hosts:
        base = f"https://{h}"
        rb = fetch(base + "/robots.txt")
        for m in re.finditer(r"(?im)^sitemap:\s*(\S+)", rb["text"] if rb else ""):
            todo.append(m.group(1))
        todo.append(base + "/sitemap.xml")
    while todo and len(done) < 8:
        sm = norm_url(todo.pop(0))
        if sm in done:
            continue
        done.add(sm)
        pg = fetch(sm, timeout=15)
        if not pg:
            continue
        for u in re.findall(r"https?://[^\s<>\"']+", pg["text"]):
            if u.lower().endswith(".xml") or "sitemap" in u.lower():
                if root_domain(urllib.parse.urlparse(u).netloc.split(":")[0]) == t["root"]:
                    todo.append(u)
            else:
                urls.append(u)
    return urls


def discover(t, model, deadline):
    cands = {}      # url -> why

    def add(url, why):
        url = norm_url(url)
        if url and url not in cands:
            cands[url] = why

    local = t["host"] in ("localhost", "127.0.0.1") or re.match(r"^\d+\.\d+\.\d+\.\d+$", t["host"] or "")
    if not local:
        for sub in ("developers", "developer", "docs", "api", "dev"):
            add(f"https://{sub}.{t['root']}", "pattern")
    for path in ("/docs", "/developers", "/developer", "/api", "/api-docs", "/developer-docs"):
        add(t["origin"] + path, "pattern")

    home = fetch(t["origin"])
    if home:
        log("discover", f"read homepage ({len(home['links'])} links)")
        for url, label in home["links"]:
            if DOC_HINT.search(label or "") or DOC_HINT.search(urllib.parse.urlparse(url).netloc):
                if not url.lower().endswith(SKIP_EXT) and not foreign_locale(url):
                    add(url, "homepage link")
    else:
        log("discover", "homepage not readable")

    index_urls = [t["origin"] + "/llms.txt", t["origin"] + "/sitemap.xml"]
    if not local:
        index_urls += [f"https://docs.{t['root']}/llms.txt", f"https://developers.{t['root']}/llms.txt"]
    for iu in index_urls:
        pg = fetch(iu)
        if pg:
            urls = re.findall(r"https?://[^\s)<>\"']+", pg["text"])
            hits = [u for u in urls if score(urllib.parse.urlparse(u).path.replace("-", " ")) >= 3][:15]
            log("discover", f"{iu.rsplit('/', 1)[-1]}: {len(hits)} relevant URLs")
            for u in hits:
                add(u, "index file")

    EXTRA_LINKS.clear()
    if not local:
        try:
            hosts = {t["host"], f"developers.{t['root']}", f"docs.{t['root']}"} | {urllib.parse.urlparse(u).netloc for u in cands if DOCHOST.search(urllib.parse.urlparse(u).netloc)}
            allu = sitemap_urls(t, sorted(h for h in hosts if h))
            ranked = sorted({norm_url(u) for u in allu}, key=lambda u: -score(urllib.parse.urlparse(u).path.replace("-", " ").replace("/", " ")))
            for u in ranked[:60]:
                if not foreign_locale(u) and score(urllib.parse.urlparse(u).path.replace("-", " ").replace("/", " ")) >= 3:
                    EXTRA_LINKS.append(u)
            log("discover", f"sitemaps: {len(allu)} URLs, {len(EXTRA_LINKS)} look relevant")
        except Exception as e:
            log("discover", f"sitemap scan failed: {str(e)[:100]}")

    if not local and time.time() < deadline:
        found_any = 0
        for q in (f"{t['name']} developer docs create OAuth app", f"{t['name']} app marketplace submit app review approval requirements",
                  f"{t['name']} API rate limits scopes app permissions"):
            for u in web_search(q):
                host = urllib.parse.urlparse(u).netloc.lower()
                if (root_domain(host.split(":")[0]) == t["root"] or t["name"].lower().replace(" ", "") in host) and not foreign_locale(u) and not u.lower().endswith(SKIP_EXT):
                    add(u, "web search")
                    found_any += 1
        log("discover", f"web search added {found_any} provider URLs")

    if time.time() < deadline:
        try:
            res = gemini_json(
                f"The website is {t['origin']}. List up to 5 URLs you are fairly confident exist on the provider's own "
                f"developer documentation covering OAuth app registration, app review or publishing, and rate limits. "
                f"Only real, specific URLs. Return JSON.", URL_SCHEMA, model)
            for u in res.get("urls", [])[:5]:
                if isinstance(u, str) and u.startswith("http"):
                    add(u, "model suggestion (unverified)")
            log("discover", f"model suggested {len(res.get('urls', []))} URLs (candidates only)")
        except Exception as e:
            log("discover", f"model suggestions unavailable: {str(e)[:120]}")

    log("discover", f"{len(cands)} candidate URLs, probing")
    urls = list(cands)
    with ThreadPoolExecutor(max_workers=6) as ex:
        pages = list(ex.map(fetch, urls))
    found = []
    for u, pg in zip(urls, pages):
        if pg and not pg["thin"] or (pg and cands[u] != "pattern"):
            pu = urllib.parse.urlparse(pg["url"])
            s = score(pg["title"] + " " + pg["url"] + " " + pg["text"][:3000]) + (3 if cands[u] == "homepage link" else 0)
            s += 6 if (DOCHOST.search(pu.netloc) or re.match(r"^/(docs|developers?|api)\b", pu.path)) else 0
            s -= 10 if NOISE.search(pu.path) else 0
            found.append((s, pg, cands[u]))
    found.sort(key=lambda x: -x[0])
    seeds, seen = [], set()
    for s, pg, why in found:
        if pg["url"] in seen or s < 1:
            continue
        seen.add(pg["url"])
        seeds.append(pg)
        log("discover", f"seed [{s}] {pg['url']} ({why})")
        if len(seeds) >= 4:
            break
    return seeds


# ---------------------------------------------------------------- 2. crawl

def crawl(seeds, max_pages, deadline):
    """Best-first crawl, then top up any topic (review, going public, registering, limits) that has no pages yet."""
    pages, seen, heap, n, pool = [], set(), [], 0, {}
    for pg in seeds:
        seen.add(pg["url"])
        pages.append(pg)
    hosts = {urllib.parse.urlparse(p["url"]).netloc for p in seeds}
    roots = {root_domain(h.split(":")[0]) for h in hosts}

    def in_scope(u):
        host = urllib.parse.urlparse(u).netloc
        return u.startswith("http") and not foreign_locale(u) and not u.lower().endswith(SKIP_EXT) and (host in hosts or root_domain(host.split(":")[0]) in roots)

    def push(pg):
        nonlocal n
        for url, label in pg["links"]:
            u = norm_url(url)
            if not in_scope(u):
                continue
            if len(label or "") > len(pool.get(u, "")):
                pool[u] = label or ""
            if u in seen:
                continue
            s = link_score(u, label)
            if s >= 2:
                n += 1
                heapq.heappush(heap, (-s, n, u, label))
                seen.add(u)

    def take(url, why):
        pg = fetch(url)
        if not pg:
            log("crawl", f"skip {url} (unreadable or blocked)")
            return None
        seen.add(pg["url"])
        if pg["thin"]:
            log("crawl", f"thin page (likely needs JavaScript): {url}")
        else:
            log("crawl", f"read [{why}] {url} ({len(pg['text'])} chars)")
            push(pg)
        pages.append(pg)
        return pg

    for pg in seeds:
        push(pg)
    push({"links": [(u, "") for u in EXTRA_LINKS]})
    base = max(4, max_pages // 2)
    while heap and len(pages) < base and time.time() < deadline:
        s, _, url, label = heapq.heappop(heap)
        take(url, str(-s))

    # topic top-up: every topic should have at least 2 pages that match it
    for topic in TOPICS:
        have = sum(1 for p in pages if not p["thin"] and topic_score(topic, p["url"], p["title"]) >= 6)
        want = 3 - have if have < 3 else 2
        cands = sorted(((topic_score(topic, u, lab), u) for u, lab in pool.items() if u not in {p["url"] for p in pages}), reverse=True)
        added = 0
        for sc, u in cands:
            if sc < (3 if have < 3 else 6) or added >= want or len(pages) >= max_pages + 8 or time.time() > deadline:
                break
            if take(u, f"{topic}:{sc}"):
                added += 1
        if added == 0 and have == 0:
            log("crawl", f"no pages found for topic '{topic}'")

    # spend what is left of the budget on the best remaining links
    while heap and len(pages) < max_pages and time.time() < deadline:
        s, _, url, label = heapq.heappop(heap)
        if url not in {p["url"] for p in pages}:
            take(url, str(-s))
    return pages


# ---------------------------------------------------------------- 3. extract

EXTRACT_RULES = """You are reading provider developer documentation to find facts about registering an OAuth app,
getting it approved, and what limits or gates apply. Rules:
- Use ONLY the page text below. Do not use outside knowledge. If a page does not say it, leave it out.
- Every finding needs "quote": 20-300 characters copied EXACTLY, character for character, from that page. No paraphrase, no ellipsis.
- "page_id" is the number of the page the quote comes from.
- "text" is a short plain sentence stating the fact. It may say no more than the quote says; rewrite in plain, short words when that helps.
- One finding per item: never combine several items or options into one finding.
Categories:
- requirement_register: something needed just to create/register the app (item, status required|optional|not_asked)
- requirement_public: something needed before an ordinary app can be used by other people or listed. Skip rules that only apply to enterprise admins or one special program (item, status)
- limit: only limits that affect OAuth, token lifetimes, code expiry, rate limits on auth endpoints, user/install caps, or review. Skip field lengths, file sizes, image/video specs and counts of UI items. item = SHORT label under 50 characters, value = the figure (always fill it)
- blocker: a trap or failure: anything that says do not / must not / will be rejected, returned or blocked, error codes (e.g. bad_redirect_uri), limits that block submission, or changes that cannot be undone (item = the problem in one sentence, fix = what to do)
- review_stage: a review or approval stage (item = a short stage name like 'Preliminary review', value = how long, copied as written)
- access_tier: a stage of access from private/dev use to public/listed (item = a descriptive NAME such as "Unlisted distributed app", never "Tier 1"; value = the gate to reach it)
- setup_type: a choice the developer must make between kinds of credentials or apps (e.g. bot token vs user token, internal single-workspace app vs distributed app, OAuth app vs GitHub App). NOT API method names, pricing plans, or features (item = name, value = one-line difference, fix = which the docs prefer, if they say)
- creation_path: one distinct way to create or start the app that the docs describe (e.g. blank app, from a manifest, starter template, AI agent template, CLI project). Only ways to CREATE a new app, not ways to deploy, update or manage one. One finding per way (item = the way's name, value = what you get or what the wizard does, fix = when to use it)
- recommendation: ONLY if the docs explicitly say which option to use or prefer among several (words like recommend, prefer, usually best). item = the recommended option's name exactly as it is named elsewhere, text = what the docs say, fix = when a different option is better. Never invent a preference
- step: one instruction the developer performs to create, configure, install or publish the app, in the order the page gives them. INCLUDE the first steps (open the apps page, click Create an app, choose the creation option, name the app, pick a workspace), choosing scopes, setting redirect URLs and installing. Skip headings, contents lists, enterprise/identity-provider flows and optional features (events, webhooks, slash commands) unless the page presents them as part of creating the app. Include the very first step (creating or naming the app) and the install/authorize steps; one finding per step, in order.
- extra: any other fact a developer needs that fits nowhere above (item = title, value = why it matters)
Return JSON."""


def extract(pages, model, only=None, indices=None):
    """Read pages in small batches. page_id is the page's position in `pages` (1-based), so verify() can find it."""
    idx = indices if indices is not None else list(range(len(pages)))
    findings = []
    rules = EXTRACT_RULES
    if only:
        rules += "\nFOCUS: extract ONLY these categories, and be thorough: " + ", ".join(only) + ". Ignore everything else."
    for k in range(0, len(idx), BATCH):
        blocks = []
        for i in idx[k:k + BATCH]:
            pg = pages[i]
            blocks.append(f"=== PAGE {i + 1} ===\nURL: {pg['url']}\nTITLE: {pg['title']}\nTEXT:\n{pg['text'][:PAGE_CHARS]}")
        try:
            res = gemini_json(rules + "\n\n" + "\n\n".join(blocks), FINDINGS_SCHEMA, model)
            findings += res.get("findings", [])
        except Exception as e:
            log("extract", f"batch failed ({str(e)[:100]}); retrying its pages one by one")
            for i in idx[k:k + BATCH]:
                pg = pages[i]
                one = f"=== PAGE {i + 1} ===\nURL: {pg['url']}\nTITLE: {pg['title']}\nTEXT:\n{pg['text'][:PAGE_CHARS // 2]}"
                try:
                    findings += gemini_json(rules + "\n\n" + one, FINDINGS_SCHEMA, model, retries=3).get("findings", [])
                except Exception as e2:
                    log("extract", f"page {i + 1} failed: {str(e2)[:100]}")
                    RUN_ERRORS.append(str(e2)[:140])
        if k + BATCH < len(idx):
            time.sleep(3)         # stay under free-tier requests per minute
    log("extract", f"{len(findings)} findings from {len(idx)} pages")
    return findings


GAPS = {   # category -> topic whose pages should contain it
    "review_stage": "review", "access_tier": "ladder", "requirement_public": "public",
    "requirement_register": "register", "step": "register", "limit": "limits", "blocker": "review",
}


def fill_gaps(pages, good, model):
    """Second, focused pass for categories that came back empty."""
    counts = {}
    for g in good:
        counts[g["category"]] = counts.get(g["category"], 0) + 1
    extra = []
    ranked = sorted(range(len(pages)), key=lambda i: -(topic_score("types", pages[i]["url"], pages[i]["title"], pages[i]["text"]) +
                    sum(2 for k in TOPICS["types"] if k in pages[i]["text"].lower())))[:3]
    log("extract", f"focused pass for 'setup_type'/'creation_path' on pages {[i + 1 for i in ranked]}")
    extra += extract(pages, model, only=["setup_type", "creation_path", "recommendation"], indices=ranked)
    time.sleep(3)
    if not any(g["category"] == "creation_path" for g in good + extra):
        alt = [i for i, pg in enumerate(pages) if re.search(r"quickstart|manifest|create|agent|getting-started|starter", pg["url"], re.I) and not pg["thin"]][:3]
        if alt:
            log("extract", f"no creation paths yet; retrying on pages {[i + 1 for i in alt]}")
            extra += extract(pages, model, only=["creation_path"], indices=alt)
            time.sleep(3)
    for cat, topic in GAPS.items():
        if counts.get(cat, 0) >= MIN_COUNTS.get(cat, 1):
            continue
        ranked = sorted(range(len(pages)), key=lambda i: -(topic_score(topic, pages[i]["url"], pages[i]["title"], pages[i]["text"]) +
                        sum(2 for k in TOPICS[topic] if k in pages[i]["text"].lower())))[:3]
        log("extract", f"second pass for '{cat}' on pages {[i + 1 for i in ranked]}")
        extra += extract(pages, model, only=[cat], indices=ranked)
        time.sleep(3)
    return extra


# ---------------------------------------------------------------- 4. verify

def norm(s):
    s = (s or "").lower()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), (" ", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def quote_ok(quote, page_norm):
    if len(norm(quote)) < 20:
        return False
    frags = [norm(x) for x in re.split(r"\.\.\.|…", quote) if len(norm(x)) >= 15]
    return bool(frags) and all(f in page_norm for f in frags)


NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60}


def numbers_supported(f):
    """Every number the claim states must appear in its own quote (digits or spelled out)."""
    q = norm(f.get("quote", "")).replace(",", "")
    qnums = set(re.findall(r"\d+(?:\.\d+)?", q)) | {str(v) for w, v in NUMWORDS.items() if re.search(rf"\b{w}\b", q)}
    claim = (f.get("text", "") + " " + f.get("value", "")).lower().replace(",", "")
    return all(n in qnums for n in re.findall(r"\d+(?:\.\d+)?", claim))


_STOPW = set("the and for with that this are can will must may your you our not only any all into than then also from have has been".split())


def _content(s):
    out = set()
    for w in re.findall(r"[a-z][a-z0-9\-\.]+", (s or "").lower().replace("\u2019", "'")):
        w = w.strip(".-")
        if len(w) >= 4 and w not in _STOPW:
            out.add(w.rstrip("s"))
    return out


def overlap_ok(f):
    """Backstop: a claim that shares almost no words with its own quote says something the quote does not."""
    t = _content(f.get("text", ""))
    return len(t) < 5 or len(t & _content(f.get("quote", ""))) / len(t) >= 0.2


def supported(f, page_norm_text):
    return quote_ok(f.get("quote", ""), page_norm_text) and numbers_supported(f) and overlap_ok(f)


def verify(findings, pages):
    page_norm = [norm(p["text"]) for p in pages]
    good, dropped = [], []
    for f in findings:
        i = f.get("page_id", 0) - 1
        if 0 <= i < len(pages) and supported(f, page_norm[i]):
            f["_page"] = pages[i]
            good.append(f)
        else:
            dropped.append(f)
    log("verify", f"{len(good)} of {len(findings)} quotes found verbatim in the fetched pages; {len(dropped)} dropped")
    return good, dropped


# ---------------------------------------------------------------- 4b. explore (the agent loop)
# The model looks at what has been verified so far, picks ONE tool per turn, sees the result and repeats
# until it calls finish, the checklist is covered, or the step / time budget runs out.
# Tools: fetch_page, list_links, search_pages, record_finding, finish. record_finding goes through the same
# quote check as the first pass, so the model cannot add a claim the page does not contain.

CHECKLIST = [
    ("step", "registration steps, in order"),
    ("requirement_register", "what is needed to register the app"),
    ("requirement_public", "what is needed before other people can use the app or it can be listed"),
    ("review_stage", "review or approval stages and how long they take"),
    ("limit", "limits: user caps, token lifetimes, rate limits"),
    ("access_tier", "stages of access, from private to public"),
    ("blocker", "common traps or failures"),
]
AGENT_ACTIONS = ["web_search", "fetch_page", "list_links", "search_pages", "record_finding", "finish"]
ACTION_SCHEMA = {"type": "OBJECT", "properties": {
    "thought": {"type": "STRING"},
    "action": {"type": "STRING", "enum": AGENT_ACTIONS},
    "url": {"type": "STRING"}, "page_id": {"type": "INTEGER"}, "topic": {"type": "STRING"}, "query": {"type": "STRING"},
    "findings": {"type": "ARRAY", "items": FINDINGS_SCHEMA["properties"]["findings"]["items"]},
}, "required": ["thought", "action"]}

AGENT_RULES = """You are a research agent. Goal: fill the checklist below about this provider's OAuth app registration,
review and limits, using ONLY its own developer documentation. Each turn you choose exactly one action and see the result.
Actions:
- web_search(query): search the web for the provider's documentation (e.g. "<provider> create OAuth app", "<provider> marketplace app review requirements"). Results on the provider's own domains can then be fetched.
- fetch_page(url): read a page. Only the provider's own domains work (including domains a search returned that carry the provider's name). Each page you fetch is also read automatically and its verifiable facts are saved for you.
- list_links(page_id): list links found on a page you already read.
- search_pages(topic): find a topic in the pages already read, and suggest unread links about it.
- record_finding(findings): save findings from a page you have seen. Each needs an exact quote (20-300 characters, copied
  character for character from that page, no ellipsis) and its page_id. Code rejects any quote it cannot find on the page.
- finish: stop, when the checklist is covered or the missing items are not documented anywhere you can reach.
Rules:
- Prefer actions that fill a missing checklist item. Fetching a page you already read shows its full text again at no cost:
  use that to re-read a page before recording findings the first pass missed. Do not repeat the same action twice.
- Record findings as soon as you have read a page that contains them. Do not record what is already recorded.
- Never use outside knowledge. If the docs do not say it, do not record it.
Finding categories:
""" + EXTRACT_RULES.split("Categories:\n", 1)[1].rsplit("Return JSON.", 1)[0]


class Explorer:
    """State and tools for the agent loop. Mutates `pages`, `readable`, `good` and `dropped` in place."""

    def __init__(self, t, pages, readable, good, dropped, model=None, auto_read=False):
        self.t, self.pages, self.readable, self.good, self.dropped = t, pages, readable, good, dropped
        self.model, self.auto = model, auto_read
        self.name_key = re.sub(r"[^a-z0-9]", "", t["name"].lower())
        self.new_findings = []
        self.seen = {p["url"] for p in pages}
        self.roots = {t["root"]} | {root_domain(urllib.parse.urlparse(p["url"]).netloc.split(":")[0]) for p in pages}
        self.quotes = {norm(g["quote"]) for g in good}
        self.pool = {}      # unread-or-read candidate url -> link label, gathered from every page seen
        for p in pages:
            self._add_links(p)

    # -- helpers
    def _in_scope(self, url):
        host = urllib.parse.urlparse(url).netloc.split(":")[0]
        return url.startswith("http") and root_domain(host) in self.roots and not url.lower().endswith(SKIP_EXT)

    def _add_links(self, pg):
        for url, label in pg["links"]:
            u = norm_url(url)
            if self._in_scope(u) and (u not in self.pool or len(label) > len(self.pool[u])):
                self.pool[u] = label

    def _page(self, page_id):
        return self.readable[page_id - 1] if isinstance(page_id, int) and 1 <= page_id <= len(self.readable) else None

    def _links_text(self, items, limit):
        ranked = sorted(items, key=lambda x: -link_score(x[0], x[1]))[:limit]
        return "\n".join(f"- {u} - {l[:70]}{' (read)' if u in self.seen else ''}" for u, l in ranked) or "(none)"

    def unread(self, limit=12):
        return self._links_text([(u, l) for u, l in self.pool.items() if u not in self.seen and link_score(u, l) > 0], limit)

    def coverage(self):
        def counts(g, cat):
            if g["category"] != cat:
                return False
            if cat != "step":
                return True
            u = g["_page"]["url"].lower()
            return bool(REG_PAGE.search(u)) and not STEP_DENY.search(u) and urllib.parse.urlparse(u).path.strip("/") != ""
        return {cat: sum(1 for g in self.good if counts(g, cat)) for cat, _ in CHECKLIST}

    def missing(self):
        cov = self.coverage()
        return [cat for cat, _ in CHECKLIST if cov[cat] < MIN_COUNTS.get(cat, 1)]

    # -- tools
    def web_search(self, query):
        if not (query or "").strip():
            return "web_search needs a query."
        urls = web_search(query, 8)
        if not urls:
            return "No results (search unavailable or empty). Try fetch_page on a known docs URL."
        out = []
        for u in urls:
            u = norm_url(u)
            host = urllib.parse.urlparse(u).netloc.split(":")[0]
            if foreign_locale(u):
                continue
            if root_domain(host) in self.roots or (self.name_key and self.name_key in host.replace("-", "").replace(".", "")):
                self.roots.add(root_domain(host))
                self.pool.setdefault(u, "web search result")
                out.append(f"- {u}{' (read)' if u in self.seen else ''}")
            else:
                out.append(f"- {u} (not the provider's domain; cannot be fetched)")
        return "Search results:\n" + "\n".join(out)

    def auto_read(self, pg):
        """After the agent chooses a page, read it in full and save what code can verify."""
        try:
            found = extract([pg], self.model)
        except Exception as e:
            return f"auto-read failed: {str(e)[:80]}"
        g, d = verify(found, [pg])
        have = {norm(x["quote"]) for x in self.good}
        new = [x for x in g if norm(x["quote"]) not in have]
        self.good += new
        self.dropped += d
        self.new_findings += found
        return f"auto-read saved {len(new)} verified finding(s)."

    def fetch_page(self, url):
        u = norm_url(url or "")
        if not u.startswith("http"):
            return "fetch_page needs a full http(s) URL."
        if not self._in_scope(u):
            return f"{u} is outside the provider's domains ({', '.join(sorted(self.roots))}) or is a file type that is skipped. Not fetched."
        pg = fetch(u)
        if not pg:
            return f"{u} could not be read (blocked by robots.txt, missing, or not text)."
        self.seen.update((u, pg["url"]))
        if not any(p["url"] == pg["url"] for p in self.pages):
            self.pages.append(pg)
        if pg["thin"]:
            return f"{pg['url']} returned almost no text (probably rendered with JavaScript). Try another page."
        if not any(p["url"] == pg["url"] for p in self.readable):
            self.readable.append(pg)
            self._add_links(pg)
        pid = next(i for i, p in enumerate(self.readable, 1) if p["url"] == pg["url"])
        note = ""
        if self.auto and pg["url"] not in getattr(self, "_read", set()):
            self._read = getattr(self, "_read", set()) | {pg["url"]}
            note = self.auto_read(pg) + "\n"
        links = self._links_text([(norm_url(a), b) for a, b in pg["links"] if self._in_scope(norm_url(a))], 8)
        return f"{note}PAGE {pid}\nURL: {pg['url']}\nTITLE: {pg['title']}\nTEXT:\n{pg['text'][:PAGE_CHARS]}\n\nBest links on this page:\n{links}"

    def list_links(self, page_id):
        pg = self._page(page_id)
        if not pg:
            return f"No page {page_id}. Pages read are numbered 1 to {len(self.readable)}."
        return f"Links on page {page_id}:\n" + self._links_text(
            [(norm_url(a), b) for a, b in pg["links"] if self._in_scope(norm_url(a))], 25)

    def search_pages(self, topic):
        words = {w for w in re.findall(r"[a-z0-9]+", (topic or "").lower()) if len(w) >= 3}
        if not words:
            return "search_pages needs a topic with at least one word of 3+ letters."
        hits = []
        for i, pg in enumerate(self.readable, 1):
            for sent in re.split(r"(?<=[.!?])\s+|\n+", pg["text"]):
                n = sum(1 for w in words if w in sent.lower())
                if n and n >= min(2, len(words)):
                    hits.append((n, i, sent.strip()[:240]))
        hits.sort(key=lambda h: -h[0])
        out = ["Matches in pages already read:"] + [f"- page {i}: {s}" for _, i, s in hits[:6]] if hits else \
              ["No matches in pages already read."]
        links = [(u, l) for u, l in self.pool.items() if u not in self.seen and any(w in (u + " " + l).lower() for w in words)]
        return "\n".join(out) + "\nUnread links that may cover it:\n" + self._links_text(links, 10)

    def record_finding(self, findings):
        ok, bad = 0, []
        for f in findings or []:
            pg = self._page(f.get("page_id"))
            if not f.get("text") or f.get("category") not in CATEGORIES:
                bad.append("missing text or invalid category")
            elif not pg or not supported(f, norm(pg["text"])):
                self.dropped.append(f)
                self.new_findings.append(f)
                bad.append(f"quote not found verbatim on page {f.get('page_id')}, or a number in the claim is not in the quote: {f['text'][:70]}")
            elif norm(f["quote"]) in self.quotes:
                bad.append(f"already recorded: {f['text'][:70]}")
            else:
                f["_page"] = pg
                self.quotes.add(norm(f["quote"]))
                self.good.append(f)
                self.new_findings.append(f)
                ok += 1
        msg = f"{ok} finding(s) verified and saved."
        if bad:
            msg += " Not saved: " + "; ".join(bad) + ". To retry, copy the quote exactly from the page text."
        return msg

    def prompt(self, n, max_steps, history, last):
        cov = self.coverage()
        check = "\n".join(f"[{'x' if cov[c] >= MIN_COUNTS.get(c, 1) else ' '}] {c}: {d} ({cov[c]} verified, want {MIN_COUNTS.get(c, 1)}+)" for c, d in CHECKLIST)
        pages = "\n".join(f"{i}. {p['url']} - {p['title'][:60]}" for i, p in enumerate(self.readable, 1)) or "(none yet)"
        thin = [p["url"] for p in self.pages if p["thin"]]
        return (f"{AGENT_RULES}\nProvider: {self.t['name']} ({self.t['origin']}). Allowed domains: {', '.join(sorted(self.roots))}\n\n"
                f"CHECKLIST\n{check}\n\nPAGES READ (page_id. url)\n{pages}\n"
                + (f"Pages with no readable text: {', '.join(thin[:5])}\n" if thin else "")
                + f"\nUNREAD CANDIDATE LINKS\n{self.unread()}\n\nPREVIOUS ACTIONS\n"
                + ("\n".join(history[-10:]) or "(none)")
                + f"\n\nLATEST RESULT\n{last}\n\nStep {n} of {max_steps}. Choose one action. Return JSON.")


def explore(t, pages, readable, good, dropped, model, deadline, max_steps, agent_first=False):
    """Run the agent loop. Returns (steps, new_findings) for the trace."""
    ex = Explorer(t, pages, readable, good, dropped, model, auto_read=agent_first)
    if agent_first:
        for pg in list(readable):
            ex._read = getattr(ex, "_read", set()) | {pg["url"]}
            log("agent", f"reading seed page {pg['url']}: {ex.auto_read(pg)}")
    steps, history = [], []
    nudged = False
    last = ("Nothing yet. A first automatic pass already read the pages above and saved what it could verify. "
            "Fill what is still missing.") if not agent_first else (
            "You start with only a few seed pages. Decide yourself where to look: search the web, fetch the provider's docs pages, "
            "follow links. Every page you fetch is read for you. Fill the checklist.")
    for n in range(1, max_steps + 1):
        if time.time() >= deadline:
            log("agent", "time budget used up")
            break
        if not ex.missing():
            log("agent", "checklist covered")
            break
        try:
            act = gemini_json(ex.prompt(n, max_steps, history, last), ACTION_SCHEMA, model)
        except Exception as e:
            log("agent", f"model unavailable, stopping: {str(e)[:120]}")
            break
        action = act.get("action") if isinstance(act, dict) else None
        thought = (act.get("thought") or "")[:200] if isinstance(act, dict) else ""
        if action == "finish" and ex.missing() and not nudged and n < max_steps:
            nudged = True
            last = ("Not finished: the checklist still has missing items: " + ", ".join(ex.missing()) +
                    ". Search or fetch pages for them. Call finish again only if they are not documented anywhere you can reach.")
            log("agent", f"finish refused once, still missing: {', '.join(ex.missing())}")
            history.append(f"{n}. finish -> refused, checklist incomplete")
            steps.append({"step": n, "action": "finish", "arg": "refused", "thought": thought, "result": last[:300]})
            continue
        if action not in AGENT_ACTIONS or action == "finish":
            log("agent", f"finish: {thought}" if action == "finish" else "no valid action returned, stopping")
            steps.append({"step": n, "action": "finish", "thought": thought, "result": ""})
            break
        if action == "web_search":
            arg, last = act.get("query") or "", ex.web_search(act.get("query"))
        elif action == "fetch_page":
            arg, last = act.get("url") or "", ex.fetch_page(act.get("url"))
        elif action == "list_links":
            arg, last = act.get("page_id"), ex.list_links(act.get("page_id"))
        elif action == "search_pages":
            arg, last = act.get("topic") or "", ex.search_pages(act.get("topic"))
        else:
            arg, last = f"{len(act.get('findings') or [])} finding(s)", ex.record_finding(act.get("findings"))
        log("agent", f"step {n}/{max_steps} {action}({arg}) - {thought[:90]}")
        time.sleep(2)
        history.append(f"{n}. {action}({arg}) -> {last.splitlines()[0][:110]}")
        steps.append({"step": n, "action": action, "arg": str(arg), "thought": thought, "result": last[:300]})
    log("agent", f"{len(ex.new_findings)} finding(s) recorded in the loop, still missing: {', '.join(ex.missing()) or 'nothing'}")
    return steps, ex.new_findings


# ---------------------------------------------------------------- 5. assemble

def short(g, n=70):
    t = (g.get("item") or g["text"]).strip()
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0] + "…"


def c_docs(f):
    return {"text": f["text"].strip(), "label": "official_docs", "source_type": "docs", "source_url": f["_page"]["url"],
            "evidence_quote": f["quote"].strip(), "checked_at": TODAY}


def c_unknown(text, note):
    return {"text": text, "label": "unknown", "source_type": "none", "note": note, "checked_at": TODAY}


def c_inferred(text, note):
    return {"text": text, "label": "inferred", "source_type": "none", "note": note, "checked_at": TODAY}


JUDGE_RULES = """Using ONLY the verified claims below (each was checked against the provider's docs), write a short assessment.
- summary: at most 300 characters, plain sentences.
- start_level / public_level: easy, medium, hard or unknown. start = registering and using the app yourself. public = letting other people use it or getting listed.
  Use "unknown" when the claims don't cover it. Never guess.
- *_reason: one sentence naming the claims you relied on.
- agent_tasks: up to 4 things an AI agent can do for the developer about creating the app, configuring scopes/redirect URLs/manifest, preparing listing text and assets, or meeting the review requirements. Nothing that needs the provider portal login. Never tasks about runtime features such as messaging, webhooks, events or request signing.
- human_tasks: up to 4 things only the developer can do to get the app registered, installed, submitted and approved (sign in, submit, verify identity, attest, record a demo, wait for review). Only tasks the claims above support.
Return JSON."""


def judge(good, name, model):
    if not good:
        return None
    keep = [g for g in good if g["category"] not in ("extra", "setup_type")
            and not (g["category"] == "limit" and (LIM_BAD_RE.search(g["text"]) or not LIM_GOOD_RE.search(g["text"])))]
    lines = "\n".join(f"- [{g['category']}] {g['text']}" for g in keep[:60])
    try:
        return gemini_json(f"Provider: {name}\n\n{JUDGE_RULES}\n\nVerified claims:\n{lines}", JUDGE_SCHEMA, model)
    except Exception as e:
        log("judge", f"unavailable: {str(e)[:120]}")
        return None


LADDER_SCHEMA = {"type": "OBJECT", "properties": {"tiers": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "name": {"type": "STRING"}, "allows": {"type": "STRING"}, "gate": {"type": "STRING"},
    "claim_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}}}, "required": ["name", "allows", "gate", "claim_ids"]}}},
    "required": ["tiers"]}


def build_ladder(cands, model):
    """Order verified access claims into stages. The model only arranges and names; every stage cites verified claims verbatim."""
    if not cands:
        return None
    lines = "\n".join(f"{i}. [{g['category']}] {g['text']}" for i, g in enumerate(cands, 1))
    res = gemini_json(
        "Arrange these verified claims into the stages of access an app goes through, from most private (only the developer's own "
        "workspace/account) to most public (listed in the provider's marketplace/directory). Rules: start with the default stage right after the app is created (usually working only for its own developer or workspace) if any claim supports it; at most 5 stages; merge claims "
        "that describe the same stage; name = a descriptive name, never 'Tier N'; allows = one sentence on what the developer can do "
        "at that stage; gate = what must happen to reach it (the first stage's gate is 'Default'); claim_ids = the numbers of the "
        "claims that support the stage. Use ONLY the claims below.\n\n" + lines, LADDER_SCHEMA, model)
    out = []
    for t in (res.get("tiers") or [])[:5]:
        ids = [i for i in t.get("claim_ids", []) if isinstance(i, int) and 1 <= i <= len(cands)]
        if ids and t.get("name") and not re.match(r"^tier\s*\d+$", t["name"].strip(), re.I):
            out.append({"tier": len(out) + 1, "name": t["name"].strip()[:60], "allows": t.get("allows", "").strip()[:240] or "See claims",
                        "gate": t.get("gate", "").strip()[:200] or "See claims", "prerequisites": [],
                        "claims": [c_docs(cands[i - 1]) for i in dict.fromkeys(ids)]})
    return out or None


STAGES_SCHEMA = {"type": "OBJECT", "properties": {"stages": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "name": {"type": "STRING"}, "duration": {"type": "STRING"}, "claim_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}}},
    "required": ["name", "duration", "claim_ids"]}}}, "required": ["stages"]}


def build_stages(cands, model):
    """Name the distinct review stages and their durations. Durations must be copied from the cited claims."""
    if not cands:
        return None
    lines = "\n".join(f"{i}. {g['text']} || {g['quote']}" for i, g in enumerate(cands[:12], 1))
    res = gemini_json("List the distinct review or approval stages described below. name = a short stage name (e.g. 'Preliminary review', "
                      "'Functional review'); duration = the time exactly as the claims state it, including who it applies to if stated "
                      "(e.g. 'up to 10 weeks for new submissions, 6 weeks for resubmissions'); claim_ids = the numbers of the claims "
                      "that state it. Use ONLY the claims below. Max 4 stages.\n\n" + lines, STAGES_SCHEMA, model)
    out = []
    for st in res.get("stages") or []:
        ids = [i for i in st.get("claim_ids", []) if isinstance(i, int) and 1 <= i <= len(cands[:12])]
        if not ids or not st.get("name") or not st.get("duration"):
            continue
        src = " ".join(cands[i - 1]["text"] + " " + cands[i - 1]["quote"] for i in ids).replace(",", "")
        nums = set(re.findall(r"\d+(?:\.\d+)?", src)) | {str(v) for w, v in NUMWORDS.items() if re.search(rf"\b{w}\b", src.lower())}
        if all(n in nums for n in re.findall(r"\d+(?:\.\d+)?", st["duration"].replace(",", ""))):
            out.append({"name": st["name"].strip()[:50], "duration": st["duration"].strip()[:160], "claim_src": cands[ids[0] - 1]})
    return out or None


def assemble(t, pages, good, dropped, judgement, model, seeds):
    # Requirements and steps must come from a page that is actually about OAuth / app registration. The quote check proves a
    # quote exists, not that it is relevant: without this, "Node.js 18" from a CLI tutorial became an OAuth requirement.
    def on_topic(g):
        return len(TOPIC_RE.findall(g["_page"]["text"])) >= 2
    GATED = ("requirement_register", "requirement_public", "step")
    by = lambda cat: [g for g in good if g["category"] == cat and (cat not in GATED or on_topic(g))]
    n_docs = len(pages)
    read_note = f"{n_docs} pages read: " + ", ".join(p["url"] for p in pages[:6]) + (" …" if n_docs > 6 else "")

    # difficulty
    def rated(level, reason, label_missing):
        if judgement and level in ("easy", "medium", "hard"):
            return {"level": level, "reason": c_inferred(reason, "Model judgement from the verified claims in this guide; not tested.")}
        return {"level": "unknown", "reason": c_unknown(label_missing, read_note)}
    if judgement and not (by("requirement_public") or by("review_stage") or by("access_tier")):
        judgement = dict(judgement, public_level="unknown")
    difficulty = {
        "start": rated(judgement and judgement["start_level"], judgement and judgement["start_reason"],
                       "The pages read did not cover registering an app, so no rating was possible."),
        "public": rated(judgement and judgement["public_level"], judgement and judgement["public_reason"],
                        "The pages read did not cover review, listing or distribution, so no rating was possible."),
    }

    # time
    stages = [g for g in by("review_stage") if DURATION_RE.search(f"{g.get('value') or ''} {g['text']} {g['quote']}")]
    if stages:
        def stage_name(g):
            m = re.match(r"^(.{3,60}?)\s+(?:generally\s+|currently\s+)?(?:takes?|is|are|can)\b", g["text"])
            it = (g.get("item") or "").strip()
            return m.group(1) if m and it.lower() in ("", "review", "review stage") else (it or "Review")
        built = None
        try:
            built = build_stages(stages, model)
        except Exception as e:
            log("stages", f"could not structure review stages: {str(e)[:100]}")
        if built:
            time_ap = {"display": "; ".join(f"{b['name']}: {b['duration']}" for b in built)[:300],
                       "stages": [{"name": b["name"], "duration_text": b["duration"]} for b in built],
                       "claim": c_docs(built[0]["claim_src"])}
        else:
            time_ap = {"display": "; ".join(g["text"].rstrip(".")[:110] for g in stages[:3]),
                       "stages": [{"name": stage_name(g), "duration_text": g.get("value") or "see source"} for g in stages],
                       "claim": c_docs(stages[0])}
    else:
        time_ap = {"display": "Not found", "stages": [], "claim": c_unknown("No review or approval timeline was found.", read_note)}
    time_ = {"to_start": {"display": "Unknown", "claim": c_unknown(
        "Setup time was not stated in the pages read.", "Only a hands-on attempt shows how long registration takes.")},
        "to_approval": time_ap}

    # access ladder
    ladder = None
    try:
        ladder = build_ladder((by("access_tier") + by("review_stage"))[:20], model)
    except Exception as e:
        log("ladder", f"could not arrange stages: {str(e)[:100]}")
    tiers = by("access_tier")
    if ladder:
        pass
    elif tiers:
        ladder = [{"tier": i, "name": g.get("item") or f"Tier {i}", "allows": g["text"], "gate": g.get("value") or "See source",
                   "prerequisites": [], "claims": [c_docs(g)]} for i, g in enumerate(tiers, 1)]
    else:
        ladder = [{"tier": 1, "name": "Registered app", "allows": "Not determined", "gate": "Not determined", "prerequisites": [],
                   "claims": [c_unknown("No access stages were described in the pages read.", read_note)]}]

    def reqs(cat):
        out, kept = [], []
        for g in by(cat):
            tk = {w for w in re.findall(r"[a-z0-9]+", (g["text"] + " " + (g.get("item") or "")).lower()) if (len(w) > 3 or w.isdigit()) and w not in {"apps", "must", "your", "that", "with", "have", "least", "other"}}
            if tk and any(len(tk & k) / min(len(tk), len(k)) >= 0.6 for k in kept):
                continue                  # same rule restated (e.g. the 10-workspace minimum four times)
            kept.append(tk)
            status = g.get("status") if g.get("status") in ("required", "optional", "not_asked") else ("optional" if re.search(r"\boptional\b|\bif you\b|\bmay\b", g["text"], re.I) else "required")
            # "To offer paid plans, the app must be owned by an organization" is not needed to register at all
            cond = cat == "requirement_register" and status == "required" and bool(COND_RE.match(g["quote"] or g["text"]))
            out.append({"item": short(g, 90) + (" (only in some cases)" if cond else ""), "status": "optional" if cond else status, "claim": c_docs(g)})
        return out[:14]

    LIM_GOOD, LIM_BAD = LIM_GOOD_RE, LIM_BAD_RE

    def lim_score(g):
        blob = (g.get("item") or "") + " " + g["text"] + " " + g["_page"]["url"]
        return 2 * len(LIM_GOOD.findall(blob)) - 3 * len(LIM_BAD.findall(blob))

    def lim_value(g):
        if g.get("value") and g["value"].lower() != "see source":
            return g["value"]
        num = r"(?:\d[\d,\.]*|" + "|".join(NUMWORDS) + r")"
        m = re.search(num + r"\s*(?:[a-z]+(?:\s+(?:per|a|each)\s+[a-z]+)?)", g["text"] + " " + g["quote"], re.I)
        return m.group(0).strip() if m else short(g, 40)
    other_q = {norm(g["quote"]) for g in good if g["category"] != "limit"}
    ranked_limits = sorted((g for g in by("limit") if lim_score(g) > 0 and norm(g["quote"]) not in other_q), key=lambda g: -lim_score(g))
    seen_lim, uniq_lim = set(), []
    for g in ranked_limits:                       # the same limit is often stated on several pages
        k = (short(g).lower(), lim_value(g).lower())
        if k not in seen_lim:
            seen_lim.add(k)
            uniq_lim.append(g)
    ranked_limits = uniq_lim[:8]
    limits = [{"item": short(g), "value": lim_value(g), "claim": c_docs(g)} for g in ranked_limits]
    blockers = [{"issue": short(g, 90), "fix": g.get("fix") or "See the cited page.", "claim": c_docs(g)} for g in by("blocker")]

    def actor_for(text):
        if re.search(r"\b(log ?in|sign ?in|authenticat\w*|connect to your|enter\w*|typ(e|ing)|paste|pasting|fill\w*|click\w*|button|open\w*|go to|scroll\w*|navigat\w*|toggl\w*|select\w*|choos\w*|activat\w*|submit\w*|enabl\w*|turn on|allow\w*|creat\w* (an?|your) [a-z ]*app|press\w*)\b", text, re.I):
            return "human"
        if re.search(r"\b(cli|slack create|slack run|npm|pip|curl|exchange|call|parse|verify|send|post|listen|implement|handle|respond|store|redirect|write|install)\b", text, re.I):
            return "agent"
        return "both"
    raw = by("step")
    per_page = {}
    for g in raw:
        u_l = g["_page"]["url"].lower()
        if urllib.parse.urlparse(u_l).path.strip("/") == "" or STEP_DENY.search(u_l) or not STEP_ALLOW.search(u_l):
            continue                      # front pages, signature checks, enterprise/event flows are not the setup flow
        per_page.setdefault(g["_page"]["url"], []).append(g)
    counts = sorted(per_page.items(), key=lambda kv: -len(kv[1]))
    top = len(counts[0][1]) if counts else 0
    best = [(u, v) for i, (u, v) in enumerate(counts[:2]) if i == 0 or len(v) >= max(3, top // 2)]
    best.sort(key=lambda kv: (0 if REG_PAGE.search(kv[0].lower()) else 1, -topic_score("register", kv[0], kv[1][0]["_page"]["title"])))
    steps = []
    for u, items in best:
        pg = items[0]["_page"]
        body = norm(pg["text"])
        flow = (pg["title"].split("|")[0].strip() or u)[:50] if len(best) > 1 else None
        for g in sorted((x for x in items if not re.match(r"\s*\$?\s*cd\s", x["quote"])), key=lambda g: body.find(norm(g["quote"]))):
            st = {"order": len(steps) + 1, "text": g["text"], "actor": actor_for(g["text"]), "claim": c_docs(g)}
            if flow:
                st["text"] = f"[{flow}] {st['text']}"
            steps.append(st)

    if len(steps) > 6:
        core = [x for x in steps if not re.search(r"\bevents?\b|webhook|slash command", x["text"], re.I)]
        if len(core) >= 5:
            steps = [dict(x, order=i + 1) for i, x in enumerate(core)]

    if not steps:
        first = seeds[0]["url"] if seeds else t["origin"]
        steps = [{"order": 1, "actor": "human", "text": f"Start from the provider's developer docs: {first}",
                  "claim": c_inferred("No registration steps could be extracted from the registration pages read.", read_note)}]

    def from_steps(kinds):
        return [{"text": st["text"].split("] ", 1)[-1], "claim": st["claim"]} for st in steps
                if st["actor"] in kinds and st["claim"]["label"] == "official_docs"][:4]

    def suggested(key):
        return [{"text": x, "claim": c_inferred(x, "Model suggestion; not verified against this provider's portal.")}
                for x in (judgement or {}).get(key, []) if len(x) > 30 and not re.match(r"(help|assist|guide)\b", x, re.I)][:2]

    def dedupe(items):
        seen_t, out = set(), []
        for it in items:
            k = it["text"].lower()[:50]
            if k not in seen_t:
                seen_t.add(k)
                out.append(it)
        return out
    agent_tasks = dedupe(from_steps(("agent",)) + suggested("agent_tasks"))[:5]
    human_tasks = dedupe(from_steps(("human", "both")) + suggested("human_tasks"))[:5]

    def slug(n):
        return re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_")[:40]

    def best_match(name, names):
        n, toks = norm(name), _content(name)
        for nm in names:
            m = norm(nm)
            if n and m and (n in m or m in n):
                return nm
        scored = sorted(names, key=lambda nm: -len(toks & _content(nm)))
        return scored[0] if scored and toks & _content(scored[0]) else None

    log("assemble", f"{len(by('setup_type'))} setup_type, {len(by('creation_path'))} creation_path, {len(by('recommendation'))} recommendation findings")
    recs = by("recommendation")
    rec = None
    types, seen_t = [], set()
    for g in by("setup_type"):
        nm = (g.get("item") or "").strip()[:60]
        tid = slug(nm)
        if nm and tid and tid not in seen_t:
            seen_t.add(tid)
            types.append({"id": tid, "name": nm, "one_line": (g.get("value") or g["text"]).strip()[:200], "recommended": False})
    BAD_TYPE = re.compile(r"api method|pricing|\bplans?\b|trial|\bpaid\b|\bfree\b|\.v\d|endpoint", re.I)
    types = [x for x in types if not BAD_TYPE.search(x["name"])]
    BAD_PATH = re.compile(r"deploy|ci/cd|install app|manag|dev/staging|existing|reinstall|pricing|copy from", re.I)

    def _toks(n):
        return {w for w in re.findall(r"[a-z]+", n.lower()) if w not in {"create", "app", "apps", "from", "via", "the", "a", "new", "ui", "with", "using", "programmatically"}}
    good_paths, kept = [], []
    for g in by("creation_path"):
        nm = (g.get("item") or "").strip()
        tk = _toks(nm)
        if not nm or BAD_PATH.search(nm + " " + (g.get("value") or "")) or not tk:
            continue
        if any(len(tk & k) / min(len(tk), len(k)) >= 0.66 for k in kept):
            continue
        kept.append(tk)
        good_paths.append(g)
    good_paths = good_paths[:6]
    path_names = [(g.get("item") or "").strip()[:60] for g in good_paths]
    for r in recs:
        if r.get("item") and (best_match(r["item"], [t["name"] for t in types]) or best_match(r["item"], path_names)):
            rec = r
            break
    if rec is None and recs:
        rec = recs[0]
    rec_type = rec_path = None
    if rec and rec.get("item"):
        mt = best_match(rec["item"], [t["name"] for t in types])
        rec_type = next((t for t in types if t["name"] == mt), None)
        if not rec_type:
            rec_path = best_match(rec["item"], path_names)
    setup_types_obj = None
    if rec_type and len(types) >= 2:
        rec_type["recommended"] = True
        setup_types_obj = {"types": types[:6] if rec_type in types[:6] else types[:5] + [rec_type], "rows": [],
                           "recommendation": {"type_id": rec_type["id"], "claim": c_docs(rec), "exceptions": []}}

    extras = []
    st = by("setup_type")
    if len(st) >= 2 and not setup_types_obj:
        extras.append({"title": "Choices to make before you start (token / app / registration types)",
                       "why_it_matters": "The provider offers more than one way to set up. Compare before you choose.",
                       "claims": [c_docs(g) for g in st]})
    for g in by("extra")[: 5 - len(extras)]:
        extras.append({"title": g.get("item") or "Also worth knowing", "why_it_matters": g.get("value") or "", "claims": [c_docs(g)]})

    not_verified = []
    expected = [("review_stage", "Review or approval timeline"), ("requirement_public", "Requirements to go public"),
                ("limit", "Limits and rate limits"), ("step", "Registration steps"), ("access_tier", "Stages of access")]
    for cat, label in expected:
        if not by(cat):
            not_verified.append({"item": label, "note": "Not found in the pages read. " + read_note})
    if (len(types) >= 2 or len(path_names) >= 2) and not rec:
        not_verified.append({"item": "Which setup option is recommended", "note": "The docs read list several options but state no preference, so none is marked as recommended."})
    not_verified.append({"item": "Anything that needs a hands-on attempt", "note": "An agent cannot register an app, so nothing in this guide is Tested."})
    if RUN_ERRORS:
        not_verified.append({"item": f"{len(RUN_ERRORS)} model call(s) failed during this run",
                             "note": "Some sections may be incomplete. Errors: " + "; ".join(sorted(set(RUN_ERRORS))[:3])})
    for d in dropped[:8]:
        not_verified.append({"item": "Dropped model claim: " + (d.get("text") or "")[:120],
                             "note": "The quote the model gave was not found verbatim in the fetched page, so the claim was discarded."})
    thin = [p["url"] for p in pages if p["thin"]]
    if thin:
        not_verified.append({"item": "Pages that returned almost no text", "note": "Probably rendered with JavaScript: " + ", ".join(thin[:4])})

    paths, seen_p = [], set()
    for g in good_paths:
        name = (g.get("item") or "").strip()[:60]
        pid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if not name or not pid or pid in seen_p:
            continue
        seen_p.add(pid)
        paths.append({"id": pid, "name": name, "gives": (g.get("value") or g["text"]).strip()[:240],
                      "use_when": (g.get("fix") or "See the cited page.").strip()[:240], "claim": c_docs(g)})
        if rec_path and name == rec_path:
            paths[-1]["recommended"] = True

    MUSTNOT = re.compile(r"^(apps?|your app|the app)?\s*(must not|cannot|can't|should not|do not|are not eligible|is not eligible)", re.I)
    go_public = reqs("requirement_public")
    restr = [r for r in go_public if MUSTNOT.search(r["claim"]["text"])]
    if len(restr) >= 3:
        go_public = [r for r in go_public if r not in restr] or go_public[:1]
        extras.insert(0, {"title": "What the Marketplace rejects (app types and behaviours that must not be submitted)",
                          "why_it_matters": "Check your app against these before submitting; any one can get it returned.",
                          "claims": [r["claim"] for r in restr[:12]]})
        extras[:] = extras[:5]

    guide = {
        "schema_version": "1.0",
        "provider": {"name": t["name"], "website": t["origin"], "docs_urls": [s["url"] for s in seeds] or [t["origin"]]},
        "generated_at": TODAY,
        "generated_by": {"mode": "agent", "model": model},
        "summary": ((judgement or {}).get("summary") or f"Automatic research of {t['name']}'s developer docs. {len(good)} claims were verified against the pages read.")[:400],
        "difficulty": difficulty, "time": time_, "access_ladder": ladder,
        "requirements": {"register": reqs("requirement_register"), "go_public": go_public},
        "limits": limits, "blockers": blockers, "steps": steps,
        "agent_vs_human": {"agent": agent_tasks, "human": human_tasks},
        "extras": extras,
        "evidence": {"not_verified": not_verified, "conflicts": [],
                     "sources": list({p["url"]: {"title": p["title"] or p["url"], "url": p["url"], "type": "docs"} for p in pages if not p["thin"]}.values())},
    }
    if len(paths) >= 2:
        guide["creation_paths"] = paths
    if setup_types_obj:
        guide["setup_types"] = setup_types_obj
    if rec and not rec_type and not rec_path:
        guide["extras"].append({"title": "What the docs recommend", "why_it_matters": rec.get("item") or "Stated preference", "claims": [c_docs(rec)]})
    return guide


# ---------------------------------------------------------------- orchestration

_real_gemini_json = gemini_json


def agent_first_empty(pages):
    return not pages


def run_agent(raw_input, model, max_pages=20, max_seconds=300, max_steps=10, agent_first=True, probes=True):
    deadline = time.time() + max_seconds
    RUN_ERRORS.clear()
    raw_input = resolve_bare_name(raw_input)
    t = parse_target(raw_input)
    log("start", f"{t['name']} ({t['origin']})")
    if not host_is_public(t["host"]):
        raise ValueError(f"Refused: {t['host']!r} is not a public internet address (localhost, private and internal hosts are blocked).")
    seeds = discover(t, model, deadline)
    if not seeds:
        log("discover", "no documentation pages found")
    if agent_first:
        pages = list(seeds[:6])           # the agent decides everything else
        log("agent", f"agent-first mode: starting from {len(pages)} seed pages; the agent searches and reads the rest")
    else:
        pages = crawl(seeds, max_pages, deadline) if seeds else []
        log("crawl", f"{len(pages)} pages kept")
    readable = [p for p in pages if not p["thin"]]
    findings = [] if agent_first else (extract(readable, model) if readable else [])
    good, dropped = verify(findings, readable) if findings else ([], [])
    if readable and not agent_first:                      # focused second pass for categories that came back empty
        more = fill_gaps(readable, good, model)
        g2, d2 = verify(more, readable)
        seen_q = {norm(g["quote"]) for g in good}
        good += [g for g in g2 if norm(g["quote"]) not in seen_q]
        dropped += d2
        findings += more
    steps = []
    if max_steps > 0 and (readable or agent_first):    # agent loop fills whatever is still missing
        steps, extra = explore(t, pages, readable, good, dropped, model,
                               deadline if agent_first else time.time() + max(60, max_seconds // 2), max_steps, agent_first)
        findings = findings + extra
    if agent_first and readable:      # one focused pass for categories the agent's reading left thin
        more = fill_gaps(readable, good, model)
        g2, d2 = verify(more, readable)
        seen_q = {norm(g["quote"]) for g in good}
        good += [g for g in g2 if norm(g["quote"]) not in seen_q]
        dropped += d2
        findings += more
    probe_res = None
    if probes and not agent_first_empty(pages):
        env = types.SimpleNamespace(log=log, UA=UA, root_domain=root_domain, norm_url=norm_url, allowed_by_robots=allowed_by_robots)
        probe_res = run_probes(env, t, pages, min(deadline, time.time() + 60))
    facts = [{"category": "live_test", "text": "(tested live) " + o["text"]} for o in (probe_res or {}).get("observations", [])]
    judgement = judge(facts + good, t["name"], model)
    guide = assemble(t, readable if readable else pages, good, dropped, judgement, model, seeds)
    if probe_res:
        apply_probes(guide, probe_res, TODAY)
    trace = {"input": raw_input, "pages": [{"url": p["url"], "chars": len(p["text"]), "thin": p["thin"]} for p in pages],
             "steps": steps, "probes": probe_res,
             "findings": [{"category": f["category"], "text": f["text"], "quote": f["quote"], "verified": f in good} for f in findings]}
    return guide, trace


def validate(guide, schema_path):
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        log("validate", "jsonschema not installed; skipping schema check (pip install jsonschema)")
        return True
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    errs = sorted(Draft202012Validator(schema).iter_errors(guide), key=lambda e: list(e.absolute_path))
    for e in errs[:10]:
        log("validate", "/".join(str(p) for p in e.absolute_path) + ": " + e.message[:140])
    log("validate", "OK" if not errs else f"{len(errs)} schema error(s)")
    return not errs


def load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k and not k.startswith("#") and v and k not in os.environ:
                os.environ[k] = v.strip().strip(chr(34)+chr(39))


def main():
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="app name or website, e.g. linear.app")
    ap.add_argument("--out", help="write the guide JSON here (default: stdout)")
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL"))
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--max-seconds", type=int, default=600)
    ap.add_argument("--classic", action="store_true", help="old mode: crawl first, agent only fills gaps")
    ap.add_argument("--max-steps", type=int, default=25, help="agent-loop steps after the first pass (0 = first pass only)")
    ap.add_argument("--no-probes", action="store_true", help="skip the read-only live checks against the provider")
    ap.add_argument("--trace", help="write pages read and every finding (verified or not) here")
    ap.add_argument("--schema", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guides", "guide.schema.json"))
    a = ap.parse_args()
    sm_key = get_gemini_api_key()      # Secret Manager first, then GEMINI_API_KEY from the environment / .env
    if sm_key:
        os.environ["GEMINI_API_KEY"] = sm_key
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        sys.exit("No Gemini API key: set GCP_PROJECT_ID (Secret Manager) or GEMINI_API_KEY.")
    model = a.model or pick_model(os.environ["GEMINI_API_KEY"].strip())
    log("start", f"model {model}")
    try:
        guide, trace = run_agent(a.target, model, a.max_pages, a.max_seconds, a.max_steps, agent_first=not a.classic, probes=not a.no_probes)
    except ValueError as e:
        sys.exit(str(e))
    ok = os.path.exists(a.schema) and validate(guide, a.schema)
    out = json.dumps(guide, indent=2, ensure_ascii=False)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(out)
        log("done", f"wrote {a.out}")
    else:
        print(out)
    if a.trace:
        os.makedirs(os.path.dirname(os.path.abspath(a.trace)), exist_ok=True)
        with open(a.trace, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2, ensure_ascii=False)
    sys.exit(0 if ok or not os.path.exists(a.schema) else 2)


if __name__ == "__main__":
    main()