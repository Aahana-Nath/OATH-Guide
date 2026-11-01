"""Unit tests for the safety guard and the accuracy fixes. No network or API key needed:  python tests/unit_test.py"""
import os, sys, urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
os.environ.pop("OAUTH_AGENT_ALLOW_PRIVATE", None)
import guide_agent as g
import netguard

passed = 0


def check(name, cond):
    global passed
    assert cond, f"FAILED: {name}"
    passed += 1


# --- SSRF guard: only public http(s) hosts
for host in ("127.0.0.1", "localhost", "169.254.169.254", "10.1.2.3", "192.168.0.9", "[::1]", ""):
    check(f"host_is_public({host!r}) is False", netguard.host_is_public(host) is False)
for url in ("file:///etc/passwd", "ftp://example.com/x", "http://127.0.0.1/", "https://169.254.169.254/latest/meta-data/"):
    try:
        netguard.check_url(url)
        check(f"{url} blocked", False)
    except urllib.error.URLError:
        check(f"{url} blocked", True)
check("fetch() refuses a private host", g.fetch("http://127.0.0.1:8765/") is None)
try:
    g.run_agent("http://10.0.0.1", "m", 1, 5, 0)
    check("run_agent refuses private targets", False)
except ValueError as e:
    check("run_agent refuses private targets", "not a public internet address" in str(e))

# --- an "approval wait" must state a duration
for ok in ("up to 10 business days", "5-10 business days", "a few minutes", "within one week", "up to six weeks", "2-3 business days"):
    check(f"duration: {ok}", bool(g.DURATION_RE.search(ok)))
for bad in ("default", "regularly", "at their discretion", "not specified", "before it goes live"):
    check(f"not a duration: {bad}", not g.DURATION_RE.search(bad))

# --- requirements and steps must come from OAuth / app-registration pages, not unrelated product docs
copilot_page = "To use Copilot in your IDE you need a Copilot plan. Install the extension from the Visual Studio Marketplace, then sign in."
oauth_page = "Create an app, then copy the Client ID and Client secret. Set the redirect URI. Exchange the authorization code for a token (OAuth 2.0)."
check("IDE extension page is off-topic", len(g.TOPIC_RE.findall(copilot_page)) < 2)
check("OAuth registration page is on-topic", len(g.TOPIC_RE.findall(oauth_page)) >= 2)

# --- conditional requirements are not "required to register"
check("'To offer paid plans...' is conditional", bool(g.COND_RE.match("To offer paid plans for your app, the app must be owned by an organization")))
check("'You must verify your email' is not conditional", not g.COND_RE.match("You must verify your email address"))

# --- display names and quote matching
check("brand casing", g.parse_target("github.com")["name"] == "GitHub" and g.parse_target("calendly.com")["name"] == "Calendly")
page = g.norm("Authorization codes expire after 10 minutes and can be used only once.")
check("exact quote accepted", g.quote_ok("Authorization codes expire after 10 minutes", page))
check("invented quote rejected", not g.quote_ok("Apps are limited to 99 users per workspace at all times.", page))

# --- test-then-save gate: claims whose quotes cannot be re-found are removed; the result is recorded as a tested claim
import copy, json, types
import savecheck
savecheck.time.sleep = lambda s: None
base = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guides", "github-agent.json")))
schema = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guides", "guide.schema.json")
keys = set()
savecheck._collect({k: v for k, v in base.items() if k not in ("provider", "evidence")}, keys)
check("sample guide has documentation claims to test", len(keys) > 10)
gone = set(sorted(keys)[:4])
texts = {}
for u, q in keys:
    if (u, q) not in gone:
        texts[u] = texts.get(u, "") + " " + q
env = types.SimpleNamespace(cache={}, norm_url=g.norm_url, norm=g.norm, quote_ok=g.quote_ok, log=lambda *a: None,
                            fetch=lambda url, accept=None: {"text": texts[url]} if url in texts else None)
out, res = savecheck.recheck_and_prune(copy.deepcopy(base), env, schema, "2026-01-01")
left = set()
savecheck._collect({k: v for k, v in out.items() if k not in ("provider", "evidence")}, left)
check("every removed quote is gone from the saved guide", not (left & gone))
check("every re-found quote is kept", (keys - gone) <= left)
check("gate reports what failed", res["checked"] == len(keys) and len(res["failed"]) == len(gone))
check("gate result is recorded as a tested claim", out["extras"][0]["title"] == "Tested live by the agent"
      and out["extras"][0]["claims"][0]["label"] == "tested" and "re-checked" in out["extras"][0]["claims"][0]["text"])
check("pruned guide still validates", g.validate(out, schema))
check("removed claims are listed under not verified", any("removed at save time" in n["item"] for n in out["evidence"]["not_verified"]))
env_ok = types.SimpleNamespace(cache={}, norm_url=g.norm_url, norm=g.norm, quote_ok=g.quote_ok, log=lambda *a: None,
                               fetch=lambda url, accept=None: {"text": " ".join(q for (u, q) in keys if u == url)})
out2, res2 = savecheck.recheck_and_prune(copy.deepcopy(base), env_ok, schema, "2026-01-01")
check("a fully verified guide loses nothing", not res2["failed"] and len(out2["steps"]) == len(base["steps"]))

# --- OAuth is the main subject: the agent may not finish without a page that explains the flow
apps = {"url": "https://x.test/a", "title": "", "links": [], "text": "Publish your app to the Marketplace. Review takes days. Upload with the CLI and set the manifest.", "thin": False}
flow = {"url": "https://x.test/b", "title": "", "links": [], "text": "OAuth setup. Register the app to get a client_id and client secret for OAuth. Set the redirect_uri for OAuth. Send users to /authorize, then exchange the authorization code at the token endpoint for an access_token. " + "OAuth is required. " * 8, "thin": False}
check("a marketplace-only page does not explain OAuth", not g.explains_oauth(apps))
check("a page with the OAuth flow does", g.explains_oauth(flow))
check("a thin page never counts", not g.explains_oauth({**flow, "thin": True}))
ex = g.Explorer({"name": "X", "origin": "https://x.test", "root": "x.test", "host": "x.test"}, [apps], [apps], [], [])
check("oauth_flow is listed as missing first", ex.missing()[0] == "oauth_flow")
ex.pages.append(flow)
check("oauth_flow clears once such a page is read", "oauth_flow" not in ex.missing())

# --- the OAuth setup section: keys, grounded values, schema, and the save-time test
for item, key in (("authorize_url", "authorize_url"), ("Authorization endpoint", "authorize_url"), ("token endpoint", "token_url"), ("Redirect URI rules", "redirect_uri"),
                  ("PKCE", "pkce"), ("Access token lifetime", "token_lifetime"), ("client secret", "client_credentials"), ("something odd", "other"), (None, "other")):
    check(f"oauth_key({item!r}) is {key}", g.oauth_key(item) == key)
q = "Send users to https://x.test/oauth/authorize. The code expires in 10 minutes."
check("a URL that is in the quote is kept", g.value_in_quote("https://x.test/oauth/authorize", q))
check("a URL that is not in the quote is refused", not g.value_in_quote("https://x.test/oauth/token", q))
check("a number that is not in the quote is refused", not g.value_in_quote("5 minutes", q))
check("a number that is in the quote is kept", g.value_in_quote("10 minutes", q))
check("a paraphrased word value is refused", not g.value_in_quote("short lived", q))

claims = [c for c in (n["claim"] for n in base["limits"] + base["blockers"]) if c["label"] == "official_docs"][:2]
rows_guide = copy.deepcopy(base)
rows_guide["oauth_setup"] = [{"key": "authorize_url", "item": "Authorization URL", "value": "https://x.test/a", "claim": claims[0]},
                             {"key": "pkce", "item": "PKCE", "value": "required", "claim": claims[1]}]
check("a guide with an OAuth setup section validates", g.validate(rows_guide, schema))
bad = copy.deepcopy(rows_guide)
bad["oauth_setup"][0]["key"] = "made_up"
check("an unknown OAuth key is rejected by the schema", not g.validate(bad, schema))
keys2 = set()
savecheck._collect({k: v for k, v in rows_guide.items() if k not in ("provider", "evidence")}, keys2)
gone2 = {(claims[1]["source_url"], claims[1]["evidence_quote"])}
texts2 = {}
for u, qt in keys2:
    if (u, qt) not in gone2:
        texts2[u] = texts2.get(u, "") + " " + qt
env2 = types.SimpleNamespace(cache={}, norm_url=g.norm_url, norm=g.norm, quote_ok=g.quote_ok, log=lambda *a: None,
                             fetch=lambda url, accept=None: {"text": texts2[url]} if url in texts2 else None)
out3, _ = savecheck.recheck_and_prune(copy.deepcopy(rows_guide), env2, schema, "2026-01-01")
check("the save-time test removes an OAuth row whose quote is gone", [r["key"] for r in out3.get("oauth_setup", [])] == ["authorize_url"])

print(f"{passed} unit checks passed")
