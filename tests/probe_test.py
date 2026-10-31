"""Offline test for the live probes. Needs the fake server:  python tests/serve.py  (terminal 1)  then  python tests/probe_test.py"""
import copy, json, os, sys, time, types

os.environ["OAUTH_AGENT_ALLOW_PRIVATE"] = "1"   # the fake OAuth server is on 127.0.0.1

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
import guide_agent as g
import probes

BASE = "http://127.0.0.1:8765"
env = types.SimpleNamespace(log=g.log, UA=g.UA, root_domain=g.root_domain, norm_url=g.norm_url,
                            allowed_by_robots=g.allowed_by_robots, allow_http=True)
t = g.parse_target(BASE)
pages = [{"url": BASE + "/docs", "text": "Send users to http://127.0.0.1:8765/oauth/authorize to begin, then exchange the code at http://127.0.0.1:8765/oauth/token.", "title": "Docs", "thin": False,
          "links": [(BASE + "/dashboard", "Create an app"), (BASE + "/docs/oauth", "OAuth guide")]}]
res = probes.run_probes(env, t, pages, time.time() + 30)

kinds = [o["kind"] for o in res["observations"]]
texts = " | ".join(o["text"] for o in res["observations"])
assert "metadata" in kinds and "publishes OAuth server metadata" in texts, texts
assert "PKCE" in texts and "S256" in texts, texts
assert "registration endpoint" in texts, texts
assert any(o["kind"] == "authorize" and "rejected an unregistered test client with HTTP 400" in o["text"] and "Unknown client_id" in o["text"] for o in res["observations"]), texts
assert any(o["kind"] == "portal" and "sign-in page" in o["text"] for o in res["observations"]), texts
assert any(o["kind"] == "token" and "HTTP 401" in o["text"] and "Client authentication failed" in o["text"] and "WWW-Authenticate" in o["quote"] for o in res["observations"]), texts
assert res["login_wall"] and res["login_wall"]["lands_on"].endswith("/login"), res["login_wall"]
assert res["requests"] <= probes.MAX_REQUESTS

# folding into a guide keeps it schema-valid and grounds the agent / human split
guide = copy.deepcopy(json.load(open(os.path.join(HERE, "..", "guides", "github.json"))))
guide["evidence"]["not_verified"].append({"item": "Anything that needs a hands-on attempt", "note": "x"})
before_h = len(guide["agent_vs_human"]["human"])
probes.apply_probes(guide, res, g.TODAY)
assert guide["extras"][0]["title"] == "Tested live by the agent"
assert all(c["label"] == "tested" and c["source_type"] == "agent_probe" and c["note"] for c in guide["extras"][0]["claims"])
assert len(guide["agent_vs_human"]["human"]) == before_h + 1 and "sign-in page" in guide["agent_vs_human"]["human"][0]["claim"]["text"]
assert guide["requirements"]["register"][0]["status"] == "required"
assert not any(n["item"] == "Anything that needs a hands-on attempt" for n in guide["evidence"]["not_verified"])
assert len(guide["extras"]) <= 5
assert g.validate(guide, os.path.join(HERE, "..", "guides", "guide.schema.json")), "schema invalid"

# an https-only run must refuse the plain-http fake server and not crash
strict = probes.Prober(types.SimpleNamespace(**{**vars(env), "allow_http": False}), t, pages, time.time() + 30).run()
assert strict["requests"] == 0 and not strict["observations"]
# a docs page that only redirects to add a trailing slash and has "Sign in" in its navigation is NOT a login wall
doc_pages = [{"url": BASE + "/docs", "text": "Nothing here.", "title": "Docs", "thin": False, "links": [(BASE + "/guide-doc", "Create an app")]}]
doc_res = probes.Prober(env, t, doc_pages, time.time() + 30).run()
assert not [o for o in doc_res["observations"] if o["kind"] == "portal"], doc_res["observations"]
assert doc_res["login_wall"] is None

print("probe tests passed:", len(res["observations"]), "observations,", res["requests"], "requests")
