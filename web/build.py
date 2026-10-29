#!/usr/bin/env python3
"""Inline the guide JSON files into template.html and write a single self-contained page.

Usage: python3 build.py template.html out.html github.json slack.json
The first JSON file's name (minus .json) becomes its route key, e.g. #github.
"""
import json
import os
import sys


def main(template_path, out_path, *json_paths):
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    data = {}
    for p in json_paths:
        key = os.path.splitext(os.path.basename(p))[0]
        with open(p, encoding="utf-8") as f:
            data[key] = json.load(f)
    blob = json.dumps(data, ensure_ascii=False, indent=1)
    # keep the JSON from closing the script tag or opening an HTML comment
    blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--")
    marker = "/*__DATA__*/"
    if marker not in template:
        sys.exit("marker not found in template")
    html = template.replace(marker, "const DATA = " + blob + ";")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out_path} ({len(html)//1024} KB, {len(data)} guides)")


if __name__ == "__main__":
    main(*sys.argv[1:])
