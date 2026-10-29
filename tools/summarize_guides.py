#!/usr/bin/env python3
"""Summarise guides into a Markdown comparison table (used for docs/DEMO.md).

Usage: python tools/summarize_guides.py guides/*-agent.json
"""
import collections
import json
import sys


def claims(node, out):
    if isinstance(node, list):
        for n in node:
            claims(n, out)
    elif isinstance(node, dict):
        if node.get("label") and node.get("checked_at") and node.get("text"):
            out.append(node)
            return
        for v in node.values():
            claims(v, out)


def row(path):
    g = json.load(open(path, encoding="utf-8"))
    body = {k: v for k, v in g.items() if k not in ("provider", "evidence")}
    cs = []
    claims(body, cs)
    seen, uniq = set(), []
    for c in cs:                                   # count each distinct claim once
        k = (c["text"], c["label"], c.get("source_url"))
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    n = collections.Counter(c["label"] for c in uniq)
    probe = sum(1 for c in uniq if c["label"] == "tested" and c.get("source_type") == "agent_probe")
    manual = sum(1 for c in uniq if c["label"] == "tested" and c.get("source_type") == "manual_test")
    ap = g["time"]["to_approval"]["display"]
    return {
        "name": g["provider"]["name"], "mode": g["generated_by"]["mode"],
        "start": g["difficulty"]["start"]["level"], "public": g["difficulty"]["public"]["level"],
        "approval": ap if ap != "Not found" else "not found in docs",
        "tiers": len(g["access_ladder"]), "steps": len(g["steps"]),
        "req": len(g["requirements"]["register"]) + len(g["requirements"]["go_public"]),
        "limits": len(g["limits"]), "blockers": len(g["blockers"]),
        "docs": n["official_docs"], "probe": probe, "manual": manual, "inferred": n["inferred"], "unknown": n["unknown"],
        "human": len(g["agent_vs_human"]["human"]), "agent": len(g["agent_vs_human"]["agent"]),
    }


def main(paths):
    print("| App | Start | Public | Approval wait | Tiers | Steps | Reqs | Limits | Blockers | Docs claims | Tested (agent / person) | Inferred | Unknown |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in paths:
        r = row(p)
        print(f"| {r['name']} | {r['start']} | {r['public']} | {r['approval'][:60]} | {r['tiers']} | {r['steps']} | {r['req']} | {r['limits']} | {r['blockers']} | "
              f"{r['docs']} | {r['probe']} / {r['manual']} | {r['inferred']} | {r['unknown']} |")


if __name__ == "__main__":
    main(sys.argv[1:])
