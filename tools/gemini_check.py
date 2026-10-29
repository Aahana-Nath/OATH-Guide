#!/usr/bin/env python3
"""Phase 0 check: does your Gemini API key support Google Search grounding and URL context?

Setup (never paste your key anywhere else):
  macOS/Linux:  export GEMINI_API_KEY="your-key"
  Windows:      set GEMINI_API_KEY=your-key
Run:
  python3 gemini_check.py
Optional: GEMINI_MODEL=<model id> to choose a model; otherwise the script picks a Flash model.
Uses only the Python standard library. The key is sent in a header and never printed.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
DOCS_URL = "https://docs.slack.dev/slack-marketplace/slack-marketplace-review-guide"
QUESTION = "How long does Slack's Marketplace functional review take for a new app? Cite your sources."

KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not KEY:
    sys.exit("GEMINI_API_KEY is not set. See the setup lines at the top of this file.")


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-goog-api-key": KEY, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": {"message": "(unreadable error body)"}}
    except Exception as e:  # network problems
        return 0, {"error": {"message": f"{type(e).__name__}: {e}"}}


def pick_model():
    status, data = call("GET", "/models?pageSize=200")
    if status != 200:
        msg = data.get("error", {}).get("message", "unknown error")
        sys.exit(f"Could not list models (HTTP {status}): {msg[:300]}\nIf this says the key is invalid, create it again.")
    skip = ("live", "image", "tts", "audio", "transcribe", "embedding", "veo", "lyria", "omni")
    names = [
        m["name"].split("/", 1)[1]
        for m in data.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
        and "flash" in m["name"].lower()
        and not any(s in m["name"].lower() for s in skip)
    ]
    if not names:
        sys.exit("No Flash model with generateContent found. Set GEMINI_MODEL to a model ID from the AI Studio 'All models' page.")
    return sorted(names)[-1]


def run(model, label, tools, prompt):
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if tools:
        body["tools"] = tools
    status, data = call("POST", f"/models/{model}:generateContent", body)
    print(f"\n--- {label} ---")
    print(f"HTTP {status}")
    if status != 200:
        print("ERROR:", data.get("error", {}).get("message", "unknown")[:400])
        return (False, False)
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    gm = cand.get("groundingMetadata") or {}
    um = cand.get("urlContextMetadata") or {}
    uris = [c.get("web", {}).get("uri") for c in gm.get("groundingChunks", []) if c.get("web")]
    fetched = [u.get("retrievedUrl") for u in um.get("urlMetadata", [])]
    print("Answer starts:", text.strip()[:160].replace("\n", " "))
    print("Search queries:", gm.get("webSearchQueries", []))
    print("Grounding sources:", len(uris), uris[:3])
    print("URL context fetched:", fetched[:3])
    return (True, bool(uris or fetched))


model = os.environ.get("GEMINI_MODEL") or pick_model()
print("Model:", model)

base_ok, _ = run(model, "A. Plain call (is the key valid?)", None, "Reply with the single word: ready")
_, ok_search = run(model, "B. Google Search grounding", [{"google_search": {}}], QUESTION)
_, ok_url = run(model, "C. URL context", [{"url_context": {}}], f"Using {DOCS_URL}, how long does the functional review take for new apps? Quote the sentence.")

print("\n=== Verdict ===")
print("Key works:             ", "yes" if base_ok else "no")
print("Search grounding works:", "YES, sources returned" if ok_search else "NO (error, or answered from memory)")
print("URL context works:     ", "YES, page fetched" if ok_url else "NO (error, or answered from memory)")
if not ok_search and not ok_url:
    print("Neither tool returned evidence on this tier. Enable billing on the project or switch to the Claude API.")
