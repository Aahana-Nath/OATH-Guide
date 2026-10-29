"""Live probes: read-only checks the agent runs against the provider to test what the docs say.

Safe by design: GET requests only, no login, no registration, no credentials, at most MAX_REQUESTS requests,
and robots.txt is honoured. Anything that needs an account (creating the app, installing, submitting for review)
is NOT attempted; it is reported as a hand-off instead.

Probes:
  metadata   - does the provider publish OAuth server metadata (/.well-known/...)? PKCE, grant types, registration endpoint
  authorize  - how does the authorize endpoint answer an unregistered test client? (proves an app must be registered first)
  portal     - does the developer portal / "create an app" page sit behind a sign-in wall?
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from netguard import SafeRedirect, check_url
MAX_REQUESTS = 10
TIMEOUT = 10
TEST_CLIENT_ID = "oauth-guide-agent-probe"
TEST_REDIRECT = "https://localhost/oauth-guide-agent-probe"
META_PATHS = ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration")
AUTHORIZE_RE = re.compile(r"https?://[^\s\"'<>)\]\\]+/(?:oauth2?/(?:v\d+/)?)?authori[sz]e(?:[^\s\"'<>)\]\\]*)?", re.I)
PORTAL_RE = re.compile(
    r"(create|new|register|build)\W+(an?\W+)?(app|application|integration)|developer\W*(portal|console|dashboard)"
    r"|my\W+apps|your\W+apps|manage\W+apps|/apps/?$|/dashboard|/console|/developers?/apps|/settings/(developers|applications)", re.I)
LOGIN_PATH_RE = re.compile(r"log[-_ ]?in|sign[-_ ]?in|signin|/sso|/session|/auth(?:/|$)|/oauth/authorize|accounts\.|/identity", re.I)
LOGIN_TEXT_RE = re.compile(r"\b(sign in|log in|login|continue with (google|github|email)|enter your (email|password))\b", re.I)
NEED_LOGIN_RE = re.compile(r"[^.!?]*\b(?:need|must|have|required?) to (?:sign|log) ?in\b[^.!?]*[.!?]?|[^.!?]*\b(?:please|first) (?:sign|log) ?in\b[^.!?]*[.!?]?"
                           r"|[^.!?]*\b(?:sign|log) ?in (?:is )?required\b[^.!?]*[.!?]?", re.I)
DOC_PATH_RE = re.compile(r"/(docs?|documentation|guides?|reference|tutorials?|blog|changelog|learn|help|support|articles?)(/|$)", re.I)
ERROR_RE = re.compile(r"invalid|unknown|not found|unauthori[sz]ed|unregistered|no such|incorrect|missing|denied|forbidden", re.I)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _text(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


class Prober:
    def __init__(self, env, target, pages, deadline):
        self.env, self.t, self.pages, self.deadline = env, target, pages, deadline
        self.allow_http = getattr(env, "allow_http", False)   # only the offline test server is plain http
        self.requests = 0
        self.obs = []       # observations: things the agent saw
        self.skipped = []   # things it could not or would not test, with the reason
        self.roots = {target["root"]} | {env.root_domain(urllib.parse.urlparse(p["url"]).netloc.split(":")[0]) for p in pages}

    # ---- plumbing
    def _in_scope(self, url):
        host = urllib.parse.urlparse(url).netloc.split(":")[0]
        scheme_ok = url.startswith("https://") or (self.allow_http and url.startswith("http://"))
        return scheme_ok and self.env.root_domain(host) in self.roots

    def _get(self, url, follow=True):
        """One GET. Returns (status, final_url, headers, body_text) or None. Honours robots.txt and the request cap."""
        if self.requests >= MAX_REQUESTS or time.time() >= self.deadline:
            return None
        if not self._in_scope(url):
            self.skipped.append({"what": url, "why": "outside the provider's own domains"})
            return None
        if not self.env.allowed_by_robots(url):
            self.skipped.append({"what": url.split("?")[0], "why": "robots.txt disallows it, so the agent did not request it"})
            return None
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": self.env.UA, "Accept": "application/json,text/html;q=0.8,*/*;q=0.5"})
        opener = urllib.request.build_opener(SafeRedirect) if follow else urllib.request.build_opener(_NoRedirect)
        try:
            check_url(url)
            with opener.open(req, timeout=TIMEOUT) as r:
                body = r.read(300_000).decode("utf-8", "replace")
                return r.status, r.geturl(), r.headers, body
        except urllib.error.HTTPError as e:
            try:
                body = e.read(300_000).decode("utf-8", "replace")
            except Exception:
                body = ""
            return e.code, url, e.headers, body
        except Exception as e:
            self.skipped.append({"what": url, "why": f"request failed ({type(e).__name__})"})
            return None

    def _add(self, kind, text, url, quote="", how="", note=""):
        self.obs.append({"kind": kind, "text": text, "url": url, "quote": quote[:300], "how": how, "note": note})
        self.env.log("probe", f"{kind}: {text[:110]}")

    # ---- 1. OAuth server metadata
    def metadata(self):
        hosts = []
        for u in [self.t["origin"]] + [p["url"] for p in self.pages]:
            pu = urllib.parse.urlparse(u)
            origin = f"{pu.scheme}://{pu.netloc}"
            if origin not in hosts and (pu.scheme == "https" or (self.allow_http and pu.scheme == "http")):
                hosts.append(origin)
        for origin in hosts[:3]:
            for path in META_PATHS:
                url = origin + path
                res = self._get(url)
                if not res or res[0] != 200:
                    continue
                try:
                    meta = json.loads(res[3])
                except ValueError:
                    continue
                if not isinstance(meta, dict) or not ("authorization_endpoint" in meta or "issuer" in meta):
                    continue
                self.meta = meta
                self.meta_oidc = "openid-configuration" in path
                self.meta_mcp = "mcp" in json.dumps(meta).lower()
                first = len(self.obs)
                how = f"GET {url} returned HTTP 200 with JSON"
                kind_note = ""
                if self.meta_mcp:
                    kind_note = "This metadata mentions MCP, so it likely describes the provider's MCP server sign-in, not the standard app OAuth flow in the docs."
                elif self.meta_oidc:
                    kind_note = "This is the OpenID Connect (sign-in) metadata, which may not describe the main app OAuth flow."
                self._add("metadata", f"The provider publishes {'OpenID Connect' if self.meta_oidc else 'OAuth server'} metadata at {url}.", url,
                          quote=f"issuer: {meta.get('issuer', '')}".strip(), how=how, note=kind_note)
                pk = meta.get("code_challenge_methods_supported")
                if pk:
                    self._add("metadata", f"The metadata lists PKCE code challenge methods: {', '.join(map(str, pk))}.", url,
                              quote=f"code_challenge_methods_supported: {pk}", how=how)
                if meta.get("registration_endpoint"):
                    self._add("metadata", f"The metadata advertises a client registration endpoint ({meta['registration_endpoint']}), so apps may be creatable through an API.", url,
                              quote=f"registration_endpoint: {meta['registration_endpoint']}", how=how,
                              note="The agent did not register an app: that would create a real client on your behalf.")
                if meta.get("grant_types_supported"):
                    self._add("metadata", f"Supported grant types: {', '.join(map(str, meta['grant_types_supported']))}.", url,
                              quote=f"grant_types_supported: {meta['grant_types_supported']}", how=how)
                if meta.get("token_endpoint_auth_methods_supported"):
                    self._add("metadata", f"Client authentication methods at the token endpoint: {', '.join(map(str, meta['token_endpoint_auth_methods_supported']))}.", url,
                              quote=f"token_endpoint_auth_methods_supported: {meta['token_endpoint_auth_methods_supported']}", how=how)
                if isinstance(meta.get("scopes_supported"), list):
                    self._add("metadata", f"The metadata lists {len(meta['scopes_supported'])} supported scopes.", url, quote="scopes_supported: " + ", ".join(map(str, meta["scopes_supported"][:8])), how=how)
                for o in self.obs[first:]:        # carry the caveat on every observation from this document
                    if kind_note and kind_note not in o["note"]:
                        o["note"] = (o["note"] + " " + kind_note).strip()
                return
        self.meta = None
        self.skipped.append({"what": "OAuth server metadata", "why": f"none published at {', '.join(h.split('//')[1] for h in hosts[:3])} (checked {', '.join(META_PATHS)})"})

    # ---- 2. authorize endpoint
    def _authorize_url(self):
        meta = getattr(self, "meta", None)
        meta_url = meta.get("authorization_endpoint") if meta else None
        docs_url = None
        for p in self.pages:
            for m in AUTHORIZE_RE.finditer(p["text"]):
                u = m.group(0).rstrip(".,;").split("?")[0]
                if self._in_scope(u):
                    docs_url = u
                    break
            if docs_url:
                break
        # OIDC / MCP sign-in metadata often points at a different flow than the app OAuth the docs describe
        if getattr(self, "meta_oidc", False) or getattr(self, "meta_mcp", False):
            return docs_url or (None if getattr(self, "meta_mcp", False) else meta_url)
        return meta_url or docs_url

    def authorize(self):
        base = self._authorize_url()
        if not base:
            self.skipped.append({"what": "Authorize endpoint", "why": "no authorization URL found in the metadata or the docs read"})
            return
        q = urllib.parse.urlencode({"response_type": "code", "client_id": TEST_CLIENT_ID, "redirect_uri": TEST_REDIRECT, "state": "probe"})
        url = f"{base}?{q}"
        res = self._get(url, follow=False)
        if not res:
            return
        status, _, headers, body = res
        how = f"GET {base} with a made-up client_id ({TEST_CLIENT_ID}), no login, redirects not followed"
        loc = headers.get("Location") if headers else None
        if status in (301, 302, 303, 307, 308) and loc:
            lu = urllib.parse.urlparse(urllib.parse.urljoin(base, loc))
            dest = f"{lu.netloc}{lu.path}"
            if LOGIN_PATH_RE.search(dest):
                self._add("authorize", f"The authorize endpoint sent an unauthenticated request to a sign-in page ({dest}).", base,
                          quote=f"HTTP {status} Location: {dest}", how=how,
                          note="Sign-in comes before any client check here, so the agent could not see how an unregistered client is treated.")
            else:
                self._add("authorize", f"The authorize endpoint answered an unregistered test client with a redirect (HTTP {status}) to {dest}.", base,
                          quote=f"HTTP {status} Location: {dest}", how=how)
            return
        snippet = ""
        try:
            j = json.loads(body)
            snippet = str(j.get("error_description") or j.get("error") or j.get("message") or "")[:200] if isinstance(j, dict) else ""
        except ValueError:
            snippet = _text(body)[:200]
        if status == 200 and LOGIN_TEXT_RE.search(snippet) and not ERROR_RE.search(snippet):
            self._add("authorize", "The authorize endpoint returned a sign-in page (HTTP 200) for an unregistered test client.", base,
                      quote=snippet, how=how, note="Sign-in comes first, so unregistered-client handling was not visible without an account.")
        elif status >= 400 or ERROR_RE.search(snippet):
            self._add("authorize", f"The authorize endpoint rejected an unregistered test client with HTTP {status}" + (f": \"{snippet}\"." if snippet else "."), base,
                      quote=snippet or f"HTTP {status}", how=how,
                      note="So an app (client ID) must be registered before any sign-in flow can work.")
        else:
            self.skipped.append({"what": f"How {base} treats an unregistered client",
                                 "why": f"it returned HTTP {status} with no readable error (likely a JavaScript page), so nothing could be concluded"})

    # ---- 3. developer portal
    def _portal_candidates(self):
        seen, out = set(), []
        for p in self.pages:
            for url, label in p["links"]:
                u = self.env.norm_url(url)
                if u in seen or not self._in_scope(u) or u.lower().endswith((".png", ".jpg", ".svg", ".pdf", ".zip")):
                    continue
                path = urllib.parse.urlparse(u).path
                host = urllib.parse.urlparse(u).netloc
                if DOC_PATH_RE.search(path) or host.lower().startswith(("docs.", "support.", "help.")):
                    continue   # a documentation page can't show whether creating an app needs a sign-in
                if PORTAL_RE.search(label or "") or PORTAL_RE.search(path):
                    seen.add(u)
                    out.append((len(PORTAL_RE.findall(label or "")) * 2 + len(PORTAL_RE.findall(path)), u))
        return [u for _, u in sorted(out, reverse=True)]

    def portal(self):
        cands = self._portal_candidates()
        if not cands:
            self.skipped.append({"what": "Developer portal", "why": "no 'create an app' or dashboard link found in the pages read"})
            return
        for url in cands[:3]:
            res = self._get(url)
            if not res:
                continue
            status, final, _, body = res
            fu = urllib.parse.urlparse(final)
            dest = f"{fu.netloc}{fu.path}"
            text = _text(body)
            how = f"GET {url} without an account (redirects followed)"
            if status in (401, 403):
                self._add("portal", f"Opening {url} without an account returned HTTP {status}: it requires you to be signed in.", url, quote=f"HTTP {status}", how=how)
                self.login_wall = (url, dest)
                return
            if status != 200:
                self.skipped.append({"what": url, "why": f"returned HTTP {status}"})
                continue
            if len(text) < 200:
                self.skipped.append({"what": url, "why": "the page needs JavaScript, so the agent cannot read what is behind it without a browser"})
                continue
            need = NEED_LOGIN_RE.search(text)
            if LOGIN_PATH_RE.search(fu.path) or LOGIN_PATH_RE.search(fu.netloc) or (final != url and LOGIN_TEXT_RE.search(text[:600])):
                self._add("portal", f"Opening {url} without an account ended on a sign-in page ({dest}).", url, quote=text[:160], how=how,
                          note="Creating the app needs your own account, so the agent stopped here and left it to you.")
                self.login_wall = (url, dest)
                return
            if need:
                said = need.group(0).strip()[:200]
                self._add("portal", f"{url} opened without an account but says sign-in is needed to create an app.", url, quote=said, how=how,
                          note="Creating the app needs your own account, so the agent stopped here and left it to you.")
                self.login_wall = (url, dest)
                return
            self.skipped.append({"what": url, "why": "it opened without a visible sign-in wall (HTTP 200); the agent cannot tell whether creating an app there needs an account"})
            continue

    def run(self):
        self.meta, self.login_wall = None, None
        for step in (self.metadata, self.authorize, self.portal):
            try:
                step()
            except Exception as e:
                self.skipped.append({"what": step.__name__, "why": f"probe error ({type(e).__name__}: {str(e)[:80]})"})
        return {"observations": self.obs, "skipped": self.skipped, "requests": self.requests,
                "login_wall": {"url": self.login_wall[0], "lands_on": self.login_wall[1]} if self.login_wall else None}


def run_probes(env, target, pages, deadline):
    """env supplies: log, UA, root_domain, norm_url, allowed_by_robots."""
    env.log("probe", "starting read-only live checks (no login, no registration)")
    res = Prober(env, target, pages, deadline).run()
    env.log("probe", f"{len(res['observations'])} observation(s) from {res['requests']} request(s); {len(res['skipped'])} skipped")
    return res


def claim_of(obs, today):
    c = {"text": obs["text"], "label": "tested", "source_type": "agent_probe", "source_url": obs["url"],
         "note": f"Automated read-only probe by the agent on {today}: {obs['how']}." + (f" {obs['note']}" if obs["note"] else ""),
         "checked_at": today}
    if obs["quote"]:
        c["evidence_quote"] = obs["quote"]
    return c


def apply_probes(guide, res, today):
    """Fold probe results into an assembled guide: tested claims, grounded hand-offs, and an honest 'not verified' note."""
    obs = res["observations"]
    claims = [claim_of(o, today) for o in obs]
    if claims:
        guide["extras"].insert(0, {
            "title": "Tested live by the agent",
            "why_it_matters": "The agent made read-only requests to the provider (no login, no registration) and recorded what came back. These are observations, not documentation.",
            "claims": claims})
        del guide["extras"][5:]
        done = next((c for o, c in zip(obs, claims) if o["kind"] in ("metadata", "authorize")), claims[0])
        guide["agent_vs_human"]["agent"].insert(0, {
            "text": "Look up the provider's live OAuth endpoints and check how they answer an unregistered client (done during this run).", "claim": done})
    wall = res.get("login_wall")
    if wall:
        wc = next(c for o, c in zip(obs, claims) if o["kind"] == "portal")
        host = urllib.parse.urlparse(wall["url"]).netloc
        guide["agent_vs_human"]["human"].insert(0, {"text": f"Sign in to {host} and register the app. The agent was stopped by a sign-in page at {wall['lands_on']}.", "claim": wc})
        guide["requirements"]["register"].insert(0, {"item": f"A signed-in account on {host}", "status": "required", "claim": wc})
    nv = guide["evidence"]["not_verified"]
    for n in nv:
        if n["item"] == "Anything that needs a hands-on attempt":
            n["item"] = "Registering, installing and submitting an app"
            n["note"] = ("Not attempted. These steps need your account and create real state, so the agent stopped at the sign-in wall. "
                         + ("Only the live checks under 'Tested live by the agent' were run." if claims else "The live checks found nothing to record."))
    for s in res["skipped"][:6]:
        nv.append({"item": f"Live check not completed: {s['what'][:100]}", "note": s["why"]})
    return guide
