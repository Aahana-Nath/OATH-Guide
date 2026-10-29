#!/usr/bin/env python3
"""Independent re-check of a guide's documentation claims.

For every claim labelled official_docs, fetch its source_url again (fresh, not from the agent's cache) and confirm the
evidence_quote still appears in the page. This catches fabricated quotes, wrong source URLs and pages that have changed.
It does not judge whether a claim is *useful* or *complete*; see docs/VERIFICATION.md for the manual spot-check.

Usage:  python tools/recheck_quotes.py guides/github-agent.json [more.json ...]
        python tools/recheck_quotes.py guides/*-agent.json --json report.json
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import guide_agent as g  # noqa: E402  (reuses the same fetcher and quote matcher the agent uses)


def doc_claims(node, where, out):
    if isinstance(node, list):
        for n in node:
            doc_claims(n, where, out)
    elif isinstance(node, dict):
        if node.get("label") and node.get("checked_at") and node.get("text"):
            if node["label"] == "official_docs":
                out.append((where, node))
            return
        for k, v in node.items():
            doc_claims(v, where or k, out)


def check(item):
    where, c = item
    status = _check_once(where, c)
    if status in ("quote-not-found", "unreachable"):
        # one retry after a pause: busy docs sites sometimes answer parallel requests with a different or partial page
        time.sleep(2)
        status = _check_once(where, c)
    return where, c, status


def _check_once(where, c):
    g._cache.pop(g.norm_url(c["source_url"]), None)          # force a fresh fetch
    page = g.fetch(c["source_url"])
    if not page:
        return "unreachable"
    if g.quote_ok(c["evidence_quote"], g.norm(page["text"])):
        return "ok"
    # some docs sites serve different text as markdown (.md) than as HTML; report that separately
    if not c["source_url"].endswith(".md"):
        md = g.fetch(c["source_url"].rstrip("/") + ".md")
        if md and g.quote_ok(c["evidence_quote"], g.norm(md["text"])):
            return "only-in-md-variant"
    return "quote-not-found"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("guides", nargs="+")
    ap.add_argument("--json", help="write the full report here")
    a = ap.parse_args()
    report, bad_total = {}, 0
    for path in a.guides:
        guide = json.load(open(path, encoding="utf-8"))
        items = []
        doc_claims({k: v for k, v in guide.items() if k not in ("provider", "evidence")}, "", items)
        seen, uniq = set(), []
        for it in items:                                      # the same claim can appear in several sections
            key = (it[1].get("source_url"), it[1].get("evidence_quote"))
            if key not in seen:
                seen.add(key)
                uniq.append(it)
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(check, uniq))
        bad = [r for r in results if r[2] not in ("ok", "only-in-md-variant")]
        md_only = [r for r in results if r[2] == "only-in-md-variant"]
        bad_total += len(bad)
        report[path] = {"provider": guide["provider"]["name"], "checked": len(results), "ok": sum(1 for r in results if r[2] == "ok"),
                        "only_in_md_variant": len(md_only),
                        "failures": [{"status": s, "section": w, "text": c["text"], "url": c["source_url"], "quote": c["evidence_quote"]} for w, c, s in bad]}
        extra = f", {len(md_only)} only in the page's markdown variant" if md_only else ""
        print(f"{path}: {report[path]['ok']}/{len(results)} documentation quotes re-found at their source{extra}")
        for w, c, s in bad:
            print(f"   ✗ [{s}] {w}: {c['text'][:90]}  ({c['source_url']})")
    if a.json:
        json.dump(report, open(a.json, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    sys.exit(1 if bad_total else 0)


if __name__ == "__main__":
    main()
