"""Firecrawl integration tests against a fake Firecrawl API and a fake docs site (no network, no keys):  python tests/firecrawl_test.py"""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
os.environ["OAUTH_AGENT_ALLOW_PRIVATE"] = "1"       # the fake servers are on localhost
os.environ.pop("FIRECRAWL_DISABLE", None)
import firecrawl
import guide_agent as g

MD = ("# Create an app\n\nOpen the **developer portal** and click [Create app](https://x.test/new). "
      "Then copy the `client_id` and the client secret. " + "Redirect URIs must match exactly. " * 30)
scrapes, searches = [], []


class Docs(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/robots.txt":
            body, ctype = b"User-agent: *\nDisallow: /private\n", "text/plain"
        else:
            body, ctype = b"<html><body><div id=root></div><noscript>Enable JavaScript</noscript></body></html>", "text/html"
        self.send_response(200); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)


class Fire(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.headers["Authorization"] == "Bearer fc-test", "key must be sent as a bearer token"
        if os.environ.get("FAKE_FC_STATUS"):
            return self.reply(int(os.environ["FAKE_FC_STATUS"]), {"success": False})
        if self.path == "/v2/search":
            searches.append(body["query"])
            return self.reply(200, {"success": True, "data": {"web": [{"url": "https://docs.example.com/oauth", "title": "t"},
                                                                       {"url": "ftp://bad"}]}})
        scrapes.append(body["url"])
        assert body["formats"] == ["markdown", "links"]
        self.reply(200, {"success": True, "data": {"markdown": MD, "links": ["https://x.test/a", "mailto:a@b.c"],
                                                   "metadata": {"title": "Create an app", "statusCode": 200}}})

    def reply(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(raw)


def serve(handler):
    s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


docs, docs_url = serve(Docs)
fire, fire_url = serve(Fire)
passed = 0


def check(name, cond):
    global passed
    assert cond, f"FAILED: {name}"
    passed += 1


os.environ.pop("FIRECRAWL_API_KEY", None)
check("disabled without a key", not firecrawl.enabled())
check("search is skipped without a key", firecrawl.search("x") is None)
check("a thin page stays thin without a key", g.fetch(docs_url + "/a")["thin"] is True)

os.environ["FIRECRAWL_API_KEY"] = "fc-test"
os.environ["FIRECRAWL_API_URL"] = fire_url + "/v2"
firecrawl.reset()
check("enabled with a key", firecrawl.enabled())
check("search returns only http(s) urls", firecrawl.search("slack oauth") == ["https://docs.example.com/oauth"])
check("web_search uses Firecrawl first", g.web_search("slack oauth") == ["https://docs.example.com/oauth"])

pg = g.fetch(docs_url + "/guide")
check("a JavaScript shell is rendered through Firecrawl", pg["via"] == "firecrawl" and not pg["thin"] and scrapes == [docs_url + "/guide"])
check("markdown syntax is stripped so quotes match the visible text",
      "Open the developer portal and click Create app." in pg["text"] and "`" not in pg["text"] and "**" not in pg["text"] and "](" not in pg["text"])
check("links come back, mailto is dropped", pg["links"] == [("https://x.test/a", "")] and pg["title"] == "Create an app")
n = len(scrapes)
g.fetch(docs_url + "/guide")
check("repeat reads are cached", len(scrapes) == n)

g.fetch(docs_url + "/robots.txt"); g.fetch(docs_url + "/sitemap.xml")
check("robots.txt and sitemaps are never sent to Firecrawl", len(scrapes) == n)
check("robots.txt is honoured: a disallowed page is not rendered", g.fetch(docs_url + "/private/x") is None and len(scrapes) == n)
g.fetch(docs_url + "/norender", render=False)
check("render=False never costs a credit", len(scrapes) == n)
g.fetch(docs_url + "/m", accept="text/markdown")
check("the markdown rendition is not routed through Firecrawl", len(scrapes) == n)

os.environ["FIRECRAWL_MAX_SCRAPES"] = str(firecrawl.STATS["scrapes"])
check("a new page beyond the budget is not rendered", g.fetch(docs_url + "/over")["thin"] is True)
g._cache.pop(g.norm_url(docs_url + "/guide"), None)
check("a page already rendered can be re-read by the save-time re-test", g.fetch(docs_url + "/guide").get("via") == "firecrawl")
del os.environ["FIRECRAWL_MAX_SCRAPES"]

os.environ["FAKE_FC_STATUS"] = "402"
firecrawl.reset()
check("out of credits: scrape falls back to the built-in page", g.fetch(docs_url + "/credits")["thin"] is True)
check("out of credits: Firecrawl is switched off for the rest of the run", not firecrawl.enabled() and firecrawl.STATS["stopped"] == "out of credits")
check("out of credits: search falls back to the other engines", firecrawl.search("x") is None)
del os.environ["FAKE_FC_STATUS"]

firecrawl.reset()
os.environ["FIRECRAWL_DISABLE"] = "1"
check("--no-firecrawl switches it off", not firecrawl.enabled())

print(f"{passed} firecrawl checks passed")
