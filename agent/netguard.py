"""Outbound-request guard (SSRF protection) for a service that fetches user-supplied sites.

- only http(s) URLs are fetched (no file://, ftp://, ...)
- the host must resolve only to public internet addresses (no localhost, private ranges, link-local/cloud-metadata)
- every redirect hop is checked too, so a public page cannot bounce the agent to an internal address

Limitation: the address is checked at lookup time and the connection resolves again, so a hostile DNS server could still
answer differently the second time (DNS rebinding). Run the service without access to internal networks if that matters.
Set OAUTH_AGENT_ALLOW_PRIVATE=1 only for local tests against 127.0.0.1.
"""
import ipaddress
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

_cache = {}


def host_is_public(host):
    if os.environ.get("OAUTH_AGENT_ALLOW_PRIVATE") == "1":
        return True
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    if host not in _cache:
        try:
            ips = {i[4][0].split("%")[0] for i in socket.getaddrinfo(host, None)}
            _cache[host] = bool(ips) and all(ipaddress.ip_address(ip).is_global for ip in ips)
        except Exception:
            _cache[host] = False
    return _cache[host]


def check_url(url):
    """Raise URLError unless the URL is http(s) to a public host."""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise urllib.error.URLError(f"blocked scheme: {p.scheme or 'none'}")
    if not host_is_public(p.hostname):
        raise urllib.error.URLError("blocked: not a public internet address")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(req, timeout):
    """urlopen replacement that applies the guard to the request and to every redirect."""
    check_url(req.full_url)
    return urllib.request.build_opener(SafeRedirect).open(req, timeout=timeout)
