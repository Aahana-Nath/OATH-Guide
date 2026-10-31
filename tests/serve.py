import http.server, json, os
M={"/":"index.html","/docs":"docs.html","/docs/oauth":"oauth.html","/docs/app-review":"review.html"}
META={"issuer":"http://127.0.0.1:8765","authorization_endpoint":"http://127.0.0.1:8765/oauth/authorize",
      "code_challenge_methods_supported":["S256"],"registration_endpoint":"http://127.0.0.1:8765/register"}
class H(http.server.BaseHTTPRequestHandler):
    def send(s, code, body, ctype="text/html", headers=()):
        s.send_response(code); s.send_header("Content-Type", ctype)
        for k, v in headers: s.send_header(k, v)
        s.end_headers(); s.wfile.write(body if isinstance(body, bytes) else body.encode())
    def do_POST(s):
        n = int(s.headers.get("Content-Length") or 0)
        s.rfile.read(n)
        if s.path.split("?")[0] == "/oauth/token":
            return s.send(401, json.dumps({"error": "invalid_client", "error_description": "Client authentication failed"}), "application/json",
                          headers=[("WWW-Authenticate", 'Basic realm="oauth"')])
        s.send_response(404); s.end_headers()
    def do_GET(s):
        path = s.path.split("?")[0].rstrip("/") or "/"
        # fake OAuth provider used by tests/fake_test.py to exercise the live probes
        if path == "/.well-known/oauth-authorization-server": return s.send(200, json.dumps(META), "application/json")
        if path == "/oauth/authorize": return s.send(400, json.dumps({"error": "invalid_client", "error_description": "Unknown client_id"}), "application/json")
        if path == "/dashboard": return s.send(302, "", headers=[("Location", "/login")])
        if path == "/login": return s.send(200, "<html><body><h1>Sign in</h1><p>Enter your email to continue. " + "Welcome back to the Acme developer platform. " * 8 + "</p></body></html>")
        # a documentation page that only redirects to add a trailing slash and has "Sign in" in its navigation (not a login wall)
        if s.path == "/guide-doc": return s.send(301, "", headers=[("Location", "/guide-doc/")])
        if s.path == "/guide-doc/": return s.send(200, "<html><body><nav>Docs Sign in Support</nav><h1>Getting started</h1><p>" + "This page explains the platform in detail for developers. " * 12 + "</p></body></html>")
        f=M.get(path)
        if not f: s.send_response(404); s.end_headers(); return
        b=open(os.path.join(os.path.dirname(__file__),"site",f),"rb").read(); s.send_response(200); s.send_header("Content-Type","text/html"); s.end_headers(); s.wfile.write(b)
    def log_message(*a): pass
http.server.HTTPServer(("127.0.0.1",8765),H).serve_forever()
