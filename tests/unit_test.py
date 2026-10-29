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

print(f"{passed} unit checks passed")
