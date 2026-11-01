"""Streamlit UI for the OAuth guide agent.

Run:  streamlit run app.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
AGENT = ROOT / "agent" / "guide_agent.py"
sys.path.insert(0, str(ROOT / "agent"))
OUT = ROOT / "out"
GUIDE_DIRS = [ROOT / "guides", OUT]

LABELS = {
    "tested": ("🟢", "tested"),
    "official_docs": ("🔵", "official docs"),
    "inferred": ("🟡", "inferred"),
    "unknown": ("⚪", "unknown"),
}
LEVELS = {"easy": "🟢 Easy", "medium": "🟡 Medium", "hard": "🔴 Hard", "unknown": "⚪ Unknown"}
STATUS = {"required": "🔴 required", "optional": "🟢 optional", "not_asked": "⚪ not asked", "unknown": "❔ unknown"}


def load_env_key():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.strip().partition("=")
            if k in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FALLBACK_MODELS") \
                    and v and not os.environ.get(k):
                os.environ[k] = v.strip().strip("\"'")


def list_guides():
    found = {}
    for d in GUIDE_DIRS:
        if d.exists():
            for f in sorted(d.glob("*.json")):
                if f.name.endswith((".trace.json", ".schema.json")):
                    continue
                found[f"{d.name}/{f.name}"] = f
    return found


# ---------------------------------------------------------------- rendering

def claim_badge(c):
    icon, name = LABELS.get(c.get("label"), ("⚪", c.get("label", "?")))
    return f"{icon} {name}"


def render_claim(c):
    """Compact evidence expander for one claim."""
    with st.expander(f"{claim_badge(c)} · evidence", expanded=False):
        st.markdown(c.get("text", ""))
        if c.get("evidence_quote"):
            st.markdown(f"> {c['evidence_quote']}")
        if c.get("source_url"):
            st.markdown(f"[Source]({c['source_url']})")
        if c.get("note"):
            st.caption(c["note"])
        st.caption(f"Checked {c.get('checked_at', '?')} · source type: {c.get('source_type', 'none')}")


def render_guide(g):
    p = g["provider"]
    st.header(p["name"])
    st.markdown(g["summary"])
    gb = g.get("generated_by", {})
    st.caption(
        f"[{p['website']}]({p['website']}) · generated {g['generated_at']} · "
        f"{gb.get('mode', '')} {gb.get('model', '')}".strip()
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Difficulty to start", LEVELS.get(g["difficulty"]["start"]["level"], "?"))
    c2.metric("Difficulty to go public", LEVELS.get(g["difficulty"]["public"]["level"], "?"))
    c3.metric("Time to start", g["time"]["to_start"]["display"])
    c4.metric("Time to approval", g["time"]["to_approval"]["display"])

    tabs = st.tabs(["Steps", "Access ladder", "Requirements", "Limits", "Blockers",
                    "Agent vs human", "Extras", "Evidence", "Raw JSON"])

    with tabs[0]:
        for s in sorted(g["steps"], key=lambda x: x["order"]):
            tag = f" · `{s['applies_to']}`" if s.get("applies_to") else ""
            st.markdown(f"**{s['order']}. ({s['actor']}){tag}** {s['text']}")
            if s.get("claim"):
                render_claim(s["claim"])
        if not g["steps"]:
            st.info("No steps were found.")

    with tabs[1]:
        for t in g["access_ladder"]:
            st.subheader(f"Tier {t['tier']}: {t['name']}")
            st.markdown(f"**Allows:** {t['allows']}  \n**Gate:** {t['gate']}")
            for pre in t.get("prerequisites", []):
                st.markdown(f"- {pre}" if isinstance(pre, str) else f"- {pre.get('text', pre)}")
            for c in t.get("claims", []):
                render_claim(c)
        if "setup_types" in g:
            st.subheader("Setup types")
            stypes = g["setup_types"]
            names = {t["id"]: t["name"] for t in stypes["types"]}
            for t in stypes["types"]:
                st.markdown(f"- **{t['name']}**{' ⭐' if t['recommended'] else ''}: {t['one_line']}")
            rows = [{"": r["label"], **{names.get(c["type_id"], c["type_id"]): c["value"] for c in r["cells"]}}
                    for r in stypes["rows"]]
            if rows:
                st.table(rows)
            rec = stypes["recommendation"]
            if isinstance(rec, dict):
                st.markdown(f"**Recommendation:** {names.get(rec.get('type_id'), rec.get('type_id'))}")
                if rec.get("claim"):
                    render_claim(rec["claim"])

    with tabs[2]:
        for title, key in (("To register", "register"), ("To go public", "go_public")):
            st.subheader(title)
            for r in g["requirements"][key]:
                st.markdown(f"**{r['item']}** — {STATUS.get(r['status'], r['status'])}")
                render_claim(r["claim"])
            if not g["requirements"][key]:
                st.caption("Nothing recorded.")

    with tabs[3]:
        for l in g["limits"]:
            st.markdown(f"**{l['item']}:** {l['value']}")
            render_claim(l["claim"])
        if not g["limits"]:
            st.caption("No limits recorded.")

    with tabs[4]:
        for b in g["blockers"]:
            st.markdown(f"**Issue:** {b['issue']}  \n**Fix:** {b['fix']}")
            render_claim(b["claim"])
        if not g["blockers"]:
            st.caption("No blockers recorded.")

    with tabs[5]:
        a, h = st.columns(2)
        for col, title, key in ((a, "🤖 Agent can", "agent"), (h, "🧑 Human must", "human")):
            with col:
                st.subheader(title)
                for item in g["agent_vs_human"][key]:
                    st.markdown(f"- {item['text']}")
                    render_claim(item["claim"])

    with tabs[6]:
        for e in g.get("extras", []):
            st.subheader(e["title"])
            st.markdown(e["why_it_matters"])
            for c in e["claims"]:
                render_claim(c)
        if not g.get("extras"):
            st.caption("No extras.")

    with tabs[7]:
        ev = g["evidence"]
        st.subheader("Sources")
        for s in ev["sources"]:
            st.markdown(f"- [{s['title']}]({s['url']}) ({s['type']})")
        st.subheader("Not verified")
        for n in ev["not_verified"]:
            st.markdown(f"- **{n['item']}**: {n['note']}")
        if ev["conflicts"]:
            st.subheader("Conflicts")
            st.json(ev["conflicts"])

    with tabs[8]:
        st.json(g, expanded=False)

    st.download_button("Download guide JSON", json.dumps(g, indent=2, ensure_ascii=False),
                       file_name=f"{re.sub(r'[^a-z0-9]+', '-', p['name'].lower()).strip('-')}.json",
                       mime="application/json")


def render_trace(tr):
    steps = tr.get("steps") or []
    if steps:
        st.subheader("Agent steps")
        for s in steps:
            arg = f"({s['arg']})" if s.get("arg") else ""
            with st.expander(f"{s['step']}. {s['action']}{arg}"):
                if s.get("thought"):
                    st.markdown(f"**Thought:** {s['thought']}")
                if s.get("result"):
                    st.caption("Result")
                    st.text(s["result"])
    st.subheader("Pages read")
    for p in tr["pages"]:
        st.markdown(f"- {p['url']} ({p['chars']:,} chars{', thin' if p['thin'] else ''})")
    st.subheader("Findings")
    ok = sum(f["verified"] for f in tr["findings"])
    st.caption(f"{ok} verified, {len(tr['findings']) - ok} dropped")
    for f in tr["findings"]:
        with st.expander(f"{'✅' if f['verified'] else '❌'} [{f['category']}] {f['text'][:90]}"):
            st.markdown(f["text"])
            st.markdown(f"> {f['quote']}")


# ---------------------------------------------------------------- agent run

def run_agent(target, model, max_pages, max_seconds, max_steps, key, log_box):
    slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-") or "guide"
    OUT.mkdir(exist_ok=True)
    out, trace = OUT / f"{slug}.json", OUT / f"{slug}.trace.json"
    cmd = [sys.executable, str(AGENT), target, "--out", str(out), "--trace", str(trace),
           "--max-pages", str(max_pages), "--max-seconds", str(max_seconds), "--max-steps", str(max_steps)]
    if model:
        cmd += ["--model", model]
    env = {**os.environ, "GEMINI_API_KEY": key}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=env, cwd=str(ROOT))
    lines = []
    for line in proc.stdout:
        lines.append(line.rstrip())
        log_box.code("\n".join(lines[-25:]), language="text")
    code = proc.wait()
    return code, out, trace, "\n".join(lines)


# ---------------------------------------------------------------- page

st.set_page_config(page_title="OAuth Guide Agent", page_icon="🔐", layout="wide")
load_env_key()


st.title("🔐 OAuth Guide Agent")
st.caption("Enter an app name or website. The agent finds the developer docs, extracts an OAuth setup guide, "
           "and verifies every quote against the fetched page.")

with st.sidebar:
    st.header("Settings")
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        st.success("GEMINI_API_KEY loaded")
    else:
        key = st.text_input("Gemini API key", type="password")
    model = st.text_input("Model", value=os.environ.get("GEMINI_MODEL", ""), placeholder="auto-detect",
                          help="Defaults to GEMINI_MODEL from .env; if left blank the agent still uses it, or auto-detects when it is unset.")
    max_pages = st.slider("Max pages", 3, 40, 20)
    max_seconds = st.slider("Max seconds", 30, 900, 600, step=10)
    max_steps = st.slider("Agent steps", 0, 40, 25, help="Each step the model chooses: search the web, fetch a page, follow a link, record a finding or finish.")
    st.divider()
    guides = list_guides()
    st.header("Saved guides")
    choice = st.selectbox("Open", ["—"] + list(guides), label_visibility="collapsed")

with st.form("run"):
    c1, c2 = st.columns([4, 1])
    target = c1.text_input("App or site", placeholder="linear.app", label_visibility="collapsed")
    go = c2.form_submit_button("Generate guide", type="primary", use_container_width=True)

if go:
    if not target.strip():
        st.error("Enter an app name or website.")
    elif not key.strip():
        st.error("Set GEMINI_API_KEY in .env, or enter a key in the sidebar.")
    else:
        with st.status(f"Researching {target}…", expanded=True) as status:
            log_box = st.empty()
            code, out, trace, log_text = run_agent(target.strip(), model.strip(), max_pages,
                                                   max_seconds, max_steps, key.strip(), log_box)
            if out.exists() and code in (0, 2):
                status.update(label="Done" if code == 0 else "Done (schema warnings)",
                              state="complete" if code == 0 else "error", expanded=False)
                st.session_state["current"] = str(out)
                st.session_state["current_trace"] = str(trace)
                st.session_state["current_log"] = log_text
            else:
                status.update(label="Agent failed", state="error")
                st.session_state.pop("current", None)

elif choice != "—":
    f = guides[choice]
    st.session_state["current"] = str(f)
    st.session_state["current_trace"] = str(f.with_suffix(".trace.json"))
    st.session_state["current_log"] = ""

cur = st.session_state.get("current")
if cur and Path(cur).exists():
    guide = json.loads(Path(cur).read_text(encoding="utf-8"))
    tp = Path(st.session_state.get("current_trace", ""))
    view, trace_tab, log_tab = st.tabs(["Guide", "Trace", "Log"])
    with view:
        render_guide(guide)
    with trace_tab:
        if tp.is_file():
            render_trace(json.loads(tp.read_text(encoding="utf-8")))
        else:
            st.info("No trace saved for this guide.")
    with log_tab:
        st.code(st.session_state.get("current_log") or "No log for this guide.", language="text")