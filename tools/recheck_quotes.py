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
import types
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import guide_agent as g  # noqa: E402  (reuses the same fetcher and quote matcher the agent uses)
import savecheck  # noqa: E402


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


def check_group(args):
    """Fetch one cited URL (a few attempts, markdown variant accepted) and test every quote cited from it."""
    url, items = args
    env = types.SimpleNamespace(cache=g._cache, norm_url=g.norm_url, norm=g.norm, quote_ok=g.quote_ok, fetch=g.fetch)
    found = savecheck._check_url(env, url, sorted({c["evidence_quote"] for _, c in items}))
    return [(w, c, "ok" if found[c["evidence_quote"]] else "quote-not-found") for w, c in items]


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
        by_url = {}
        for it in uniq:                                       # fetch each cited page once, then test all its quotes
            by_url.setdefault(it[1]["source_url"], []).append(it)
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = [r for grp in ex.map(check_group, by_url.items()) for r in grp]
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
