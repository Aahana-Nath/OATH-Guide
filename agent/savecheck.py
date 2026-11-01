"""Test-then-save gate: before a guide is saved, re-fetch every page it cites and re-check every quoted claim.

A documentation claim stays in the guide only if its quote is found again on a fresh copy of its cited page. Claims that
fail are removed (and anything that rested only on them), the result is re-validated against the schema, and the outcome is
recorded in the guide as a tested claim ("N of M quoted passages re-found when this guide was saved").
"""
import collections
import copy
import json
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

TESTED_TITLE = "Tested live by the agent"


def _is_claim(n):
    return isinstance(n, dict) and n.get("label") and n.get("checked_at") and n.get("text")


def _key(c):
    return (c.get("source_url"), c.get("evidence_quote"))


def _collect(node, out):
    if isinstance(node, list):
        for n in node:
            _collect(n, out)
    elif isinstance(node, dict):
        if _is_claim(node):
            if node["label"] == "official_docs" and node.get("source_url") and node.get("evidence_quote"):
                out.add(_key(node))
            return
        for v in node.values():
            _collect(v, out)


def _has_failed(node, failed):
    found = set()
    _collect(node, found)
    return bool(found & failed)


def _prune(node, failed):
    """Drop list items whose own claim failed; drop claims that failed inside claim lists."""
    if isinstance(node, list):
        out = []
        for x in node:
            if isinstance(x, dict):
                if _is_claim(x) and x["label"] == "official_docs" and _key(x) in failed:
                    continue
                if _is_claim(x.get("claim")) and x["claim"]["label"] == "official_docs" and _key(x["claim"]) in failed:
                    continue
            out.append(_prune(x, failed))
        return out
    if isinstance(node, dict):
        if _is_claim(node):
            return node
        return {k: _prune(v, failed) for k, v in node.items()}
    return node


_host_locks = collections.defaultdict(threading.Lock)
RENDITIONS = ("text/html", "text/markdown")


def _check_url(env, url, quotes):
    """Fresh fetch of every rendition of a page (HTML and markdown, up to 3 attempts) and return {quote: found?}.
    A quote counts if it is on any rendition the site serves for that URL. Requests to one host are serialised with a short
    pause: some docs sites (shopify.dev) answer rapid or parallel requests with a different or partial page."""
    found = {q: False for q in quotes}
    host = urllib.parse.urlparse(url).netloc
    for attempt in range(3):
        texts = []
        with _host_locks[host]:
            for accept in RENDITIONS:
                env.cache.pop((env.norm_url(url), accept), None)
                page = env.fetch(url, accept=accept)
                if page:
                    texts.append(env.norm(page["text"]))
                time.sleep(0.5)
        for q in quotes:
            found[q] = found[q] or any(env.quote_ok(q, t) for t in texts)
        if all(found.values()):
            break
        time.sleep(2)
    return found


def recheck_and_prune(guide, env, schema_path, today):
    """Returns (guide, summary). `env` supplies fetch, cache, norm_url, norm, quote_ok, log."""
    keys = set()
    _collect({k: v for k, v in guide.items() if k not in ("provider", "evidence")}, keys)
    by_url = {}
    for url, quote in keys:
        by_url.setdefault(url, []).append(quote)
    env.log("savecheck", f"re-testing {len(keys)} quoted passages on {len(by_url)} cited pages before saving")
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = dict(zip(by_url, ex.map(lambda u: _check_url(env, u, by_url[u]), by_url)))
    failed = {(u, q) for u, d in results.items() for q, ok in d.items() if not ok}
    ok_count = len(keys) - len(failed)

    out = copy.deepcopy(guide)
    removed = []
    if failed:
        for section in ("setup_types", "creation_paths"):      # optional sections: drop whole if any part is untested
            if section in out and _has_failed(out[section], failed):
                removed.append(f"the whole '{section}' section")
                del out[section]
        ta = out["time"]["to_approval"]
        if _is_claim(ta.get("claim")) and ta["claim"]["label"] == "official_docs" and _key(ta["claim"]) in failed:
            out["time"]["to_approval"] = {"display": "Not found", "stages": [], "claim": {
                "text": "No review or approval timeline could be confirmed.", "label": "unknown", "source_type": "none",
                "note": "The only source quoted for it could not be re-found when this guide was saved.", "checked_at": today}}
            removed.append("the approval timeline")
        elif isinstance(ta.get("total_estimate"), dict) and _is_claim(ta["total_estimate"]) and _key(ta["total_estimate"]) in failed:
            del ta["total_estimate"]
        before = {k: len(out.get(k) or []) for k in ("steps", "limits", "blockers", "extras", "access_ladder", "oauth_setup")}
        rest = {k: v for k, v in out.items() if k not in ("provider", "evidence", "setup_types", "creation_paths")}
        pruned = _prune(rest, failed)
        out.update(pruned)
        out["extras"] = [x for x in (out.get("extras") or []) if x.get("claims")]
        ladder = [t for t in (out.get("access_ladder") or []) if t.get("claims")]
        out["access_ladder"] = [dict(t, tier=i) for i, t in enumerate(ladder, 1)] or [{
            "tier": 1, "name": "Registered app", "allows": "Not determined", "gate": "Not determined", "prerequisites": [],
            "claims": [{"text": "No access stages could be confirmed.", "label": "unknown", "source_type": "none",
                        "note": "The quotes behind them could not be re-found when this guide was saved.", "checked_at": today}]}]
        if not out.get("steps"):
            out["steps"] = [{"order": 1, "actor": "human", "text": "Start from the provider's developer docs.", "claim": {
                "text": "No setup steps could be confirmed.", "label": "inferred", "source_type": "none",
                "note": "The quotes behind the steps could not be re-found when this guide was saved.", "checked_at": today}}]
        for k, n in before.items():
            if len(out.get(k) or []) < n:
                removed.append(f"{n - len(out[k])} item(s) from {k}")
        out["steps"] = [dict(s, order=i) for i, s in enumerate(out["steps"], 1)]

    # The gate's own result is a tested claim, placed first under "Tested live by the agent".
    first_url = sorted(by_url)[0] if by_url else guide["provider"]["website"]
    text = (f"When this guide was saved, the agent re-fetched the {len(by_url)} pages it cites and re-checked {len(keys)} quoted passages: "
            f"{ok_count} were found again" + (f", {len(failed)} were not and were removed from the guide." if failed else ", none were missing."))
    claim = {"text": text, "label": "tested", "source_type": "agent_probe", "source_url": first_url,
             "note": f"Automated test on {today}: each quote must appear in a fresh copy of the cited page. A quote that does not is removed, "
                     "together with anything that rested only on it.", "checked_at": today}
    extras = out.setdefault("extras", [])
    tested = next((x for x in extras if x.get("title") == TESTED_TITLE), None)
    if tested:
        tested["claims"].insert(0, claim)
    else:
        extras.insert(0, {"title": TESTED_TITLE, "why_it_matters": "The agent tested this guide's evidence and the provider's live behaviour before saving it. These are observations, not documentation.", "claims": [claim]})
    del extras[5:]
    if failed:
        out["evidence"]["not_verified"].append({
            "item": f"{len(failed)} claim(s) removed at save time",
            "note": "Their quotes could not be re-found on the cited pages: " + "; ".join(f"{u.split('//')[-1][:60]}" for u, _ in sorted(failed)[:4])})

    # Never save a guide the schema would reject: fall back to the unpruned guide if pruning broke it.
    try:
        from jsonschema import Draft202012Validator
        with open(schema_path, encoding="utf-8") as f:
            errs = list(Draft202012Validator(json.load(f)).iter_errors(out))
        if errs:
            env.log("savecheck", f"pruned guide failed the schema ({errs[0].message[:90]}); keeping the unpruned guide")
            return guide, {"checked": len(keys), "pages": len(by_url), "ok": ok_count, "failed": [list(k) for k in sorted(failed)], "removed": [], "kept_unpruned": True}
    except ImportError:
        pass
    env.log("savecheck", f"{ok_count} of {len(keys)} passages re-found" + (f"; removed: {', '.join(removed)}" if removed else ""))
    return out, {"checked": len(keys), "pages": len(by_url), "ok": ok_count, "failed": [list(k) for k in sorted(failed)], "removed": removed, "kept_unpruned": False}
