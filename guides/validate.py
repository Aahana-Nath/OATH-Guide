#!/usr/bin/env python3
"""Validate guide JSON files against guide.schema.json and print a label summary.

Usage: python3 validate.py guide.schema.json github.json slack.json
"""
import json
import sys
from collections import Counter

from jsonschema import Draft202012Validator


def walk_claims(node, out):
    if isinstance(node, dict):
        if "label" in node and "checked_at" in node and "text" in node:
            out.append(node)
        for v in node.values():
            walk_claims(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_claims(v, out)


def main(schema_path, *guide_paths):
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    failed = False
    for path in guide_paths:
        with open(path, encoding="utf-8") as f:
            guide = json.load(f)
        errors = sorted(validator.iter_errors(guide), key=lambda e: list(e.absolute_path))
        if errors:
            failed = True
            print(f"FAIL {path}: {len(errors)} error(s)")
            for e in errors[:15]:
                loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
                print(f"  - {loc}: {e.message[:160]}")
            continue
        claims = []
        walk_claims(guide, claims)
        counts = Counter(c["label"] for c in claims)
        print(f"OK   {path}: {len(claims)} claims  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(*sys.argv[1:])
