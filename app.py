"""Streamlit frontend for the TextLens API.

Run with:  streamlit run app.py
Point it at the API with TEXTLENS_API_URL (default http://localhost:8000).
"""

from __future__ import annotations

import html
import os
import time
from typing import Any

import requests
import streamlit as st

API_URL = os.getenv("TEXTLENS_API_URL", "http://localhost:8000").rstrip("/")
POLL_INTERVAL_SECONDS = 1.0
POLL_TIMEOUT_SECONDS = 120
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# Consecutive failed polls tolerated before giving up (e.g. a brief API blip).
MAX_POLL_ERRORS = 5

THEME_NAMES = {
    "customer_experience": "Customer experience",
    "billing_pricing": "Billing & pricing",
    "network_connectivity": "Network & connectivity",
    "technology_product": "Technology & product",
    "business_finance": "Business & finance",
}

st.set_page_config(
    page_title="TextLens - Text intelligence",
    page_icon="◐",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --- API client ---------------------------------------------------------------

class ApiError(Exception):
    pass


def _detail(resp: requests.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    return detail if isinstance(detail, str) else f"HTTP {resp.status_code}"


def upload_file(name: str, data: bytes, force: bool = False) -> dict[str, Any]:
    try:
        resp = requests.post(
            f"{API_URL}/upload", files={"file": (name, data, "text/plain")},
            params={"force": "true"} if force else None, timeout=30,
        )
    except requests.RequestException as exc:
        raise ApiError(f"Couldn't reach the API at {API_URL}.") from exc
    if resp.status_code != 202:
        raise ApiError(_detail(resp))
    return resp.json()


def fetch_insights(run_id: str) -> dict[str, Any]:
    try:
        resp = requests.get(f"{API_URL}/insights/{run_id}", timeout=10)
    except requests.RequestException as exc:
        raise ApiError(f"Couldn't reach the API at {API_URL}.") from exc
    if resp.status_code != 200:
        raise ApiError(_detail(resp))
    return resp.json()


def clear_cache() -> int:
    try:
        resp = requests.delete(f"{API_URL}/cache", timeout=30)
    except requests.RequestException as exc:
        raise ApiError(f"Couldn't reach the API at {API_URL}.") from exc
    if resp.status_code != 200:
        raise ApiError(_detail(resp))
    return resp.json()["deleted"]


@st.cache_data(ttl=5, show_spinner=False)
def api_online() -> bool:
    try:
        return requests.get(f"{API_URL}/health", timeout=2).ok
    except requests.RequestException:
        return False


# --- Styles -------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg: #0d0d0c;
  --surface-1: #1a1a19;
  --surface-2: #222220;
  --hairline: #2e2e2b;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted: #8c8b82;
  --accent: #3987e5;          /* series-1 (dark step) */
  --accent-soft: rgba(57, 135, 229, 0.14);
  --div-neg: #e66767;         /* diverging pole: negative */
  --div-mid: #383835;         /* diverging neutral midpoint */
  --div-pos: #3987e5;         /* diverging pole: positive */
  --status-good: #0ca30c;
  --status-critical: #d03b3b;
  --sans: 'Inter', system-ui, -apple-system, sans-serif;
  --serif: 'Instrument Serif', Georgia, serif;
  --mono: 'JetBrains Mono', ui-monospace, monospace;
  --radius: 18px;
}

/* ---- Streamlit chrome ---- */
html, body, [data-testid="stAppViewContainer"], .stApp {
  background: var(--bg) !important;
  color: var(--text-primary);
  font-family: var(--sans);
}
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
#MainMenu, footer { display: none !important; }
[data-testid="stMainBlockContainer"], .block-container {
  max-width: 1200px !important;
  padding: 0 32px 96px !important;
}
[data-testid="stVerticalBlock"] { gap: 0.75rem; }
.stApp::before {               /* soft light leak */
  content: ""; position: fixed; inset: -20vh -10vw auto auto; width: 70vw; height: 70vh;
  background: radial-gradient(closest-side, rgba(57,135,229,0.16), transparent 70%);
  pointer-events: none; z-index: 0;
}
.stApp::after {                /* film grain */
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0; opacity: .05;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* ---- Native widgets ---- */
[data-testid="stFileUploader"] label { display: none; }
[data-testid="stFileUploaderDropzone"] {
  background: var(--surface-1) !important;
  border: 1px dashed #3d3d39 !important;
  border-radius: var(--radius) !important;
  padding: 28px 24px !important;
  transition: border-color .25s ease, background .25s ease;
}
[data-testid="stFileUploaderDropzone"]:hover {
  border-color: var(--accent) !important; background: #1d1f22 !important;
}
[data-testid="stFileUploaderDropzone"] button {
  border-radius: 999px !important; border: 1px solid var(--hairline) !important;
  background: transparent !important; color: var(--text-primary) !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploaderDropzoneInstructions"] small { color: var(--text-secondary) !important; }
[data-testid="stFileUploaderFile"] { background: var(--surface-2); border-radius: 12px; padding: 8px 12px; }

.stButton > button, [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"] {
  height: 56px; border-radius: 999px !important;
  font-family: var(--sans); font-weight: 500; font-size: 15px; letter-spacing: .01em;
  transition: transform .2s ease, box-shadow .25s ease, background .25s ease;
}
[data-testid="stBaseButton-primary"] {
  background: var(--text-primary) !important; color: #0b0b0b !important; border: none !important;
}
[data-testid="stBaseButton-primary"]:hover:not(:disabled) {
  transform: translateY(-1px); box-shadow: 0 10px 40px -10px rgba(57,135,229,.7);
}
.stButton button p { font-family: var(--sans) !important; font-size: 15px !important; font-weight: 500 !important; color: inherit !important; }
[data-testid="stBaseButton-primary"]:disabled, [data-testid="stBaseButton-primary"][aria-disabled="true"] {
  background: #2a2a28 !important; color: var(--text-muted) !important; box-shadow: none !important;
}
[data-testid="stBaseButton-secondary"] {
  background: transparent !important; color: var(--text-primary) !important;
  border: 1px solid var(--hairline) !important;
}
[data-testid="stBaseButton-secondary"]:hover { border-color: var(--text-secondary) !important; }
[data-testid="stExpander"] details {
  background: var(--surface-1); border: 1px solid var(--hairline) !important; border-radius: var(--radius);
}
[data-testid="stExpander"] summary p { font-family: var(--mono); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--text-secondary); }

/* ---- Typography & layout primitives ---- */
.lx { position: relative; z-index: 1; font-family: var(--sans); color: var(--text-primary); }
.lx * { box-sizing: border-box; }
.eyebrow, .mono {
  font-family: var(--mono); font-size: 11.5px; letter-spacing: .14em;
  text-transform: uppercase; color: var(--text-muted);
}
.section-head {
  display: flex; align-items: baseline; gap: 16px; padding: 56px 0 20px;
  border-top: 1px solid var(--hairline); margin-top: 24px;
}
.section-head .num { font-family: var(--mono); font-size: 12px; color: var(--accent); }
.section-head h2 {
  font-family: var(--serif); font-weight: 400; font-size: clamp(32px, 4vw, 48px);
  line-height: 1; margin: 0; letter-spacing: -.01em;
}
.section-head .aside { margin-left: auto; text-align: right; }

/* ---- Nav ---- */
.nav { display: flex; align-items: center; justify-content: space-between; padding: 28px 0 0; }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 17px; letter-spacing: -.02em; }
.brand-mark {
  width: 26px; height: 26px; border-radius: 50%;
  background: conic-gradient(from 180deg, var(--text-primary) 0 50%, transparent 50% 100%);
  border: 1.5px solid var(--text-primary);
}
.pill {
  display: inline-flex; align-items: center; gap: 8px; padding: 7px 14px; border-radius: 999px;
  border: 1px solid var(--hairline); font-family: var(--mono); font-size: 11px;
  letter-spacing: .1em; text-transform: uppercase; color: var(--text-secondary);
}
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex: none; }
.dot.good { background: var(--status-good); box-shadow: 0 0 0 4px rgba(12,163,12,.18); }
.dot.bad { background: var(--status-critical); box-shadow: 0 0 0 4px rgba(208,59,59,.18); }

/* ---- Hero ---- */
.hero { padding: 72px 0 8px; }
.hero h1 {
  font-family: var(--serif); font-weight: 400; margin: 18px 0 0;
  font-size: clamp(56px, 9.5vw, 132px); line-height: .92; letter-spacing: -.025em;
}
.hero h1 em { font-style: italic; color: var(--accent); }
.hero h1 .reveal { display: inline-block; animation: rise .9s cubic-bezier(.2,.7,.1,1) both; }
.hero h1 .reveal:nth-child(2) { animation-delay: .08s; }
.hero h1 .reveal:nth-child(3) { animation-delay: .16s; }
.hero-foot {
  display: grid; grid-template-columns: 1.1fr 1fr; gap: 48px; align-items: end; margin-top: 40px;
}
.lede { color: var(--text-secondary); font-size: 18px; line-height: 1.55; max-width: 34ch; margin: 0; font-weight: 300; }
.specs { display: flex; gap: 28px; justify-content: flex-end; flex-wrap: wrap; }
.specs div { border-left: 1px solid var(--hairline); padding-left: 14px; }
.specs b { display: block; font-weight: 500; font-size: 15px; margin-top: 4px; color: var(--text-primary); }
@keyframes rise { from { opacity: 0; transform: translateY(28px); filter: blur(6px); } to { opacity: 1; transform: none; filter: none; } }

.upload-label { display: flex; gap: 14px; align-items: baseline; margin: 8px 0 10px; }
.upload-label .num { color: var(--accent); }
.upload-label h3 { font-family: var(--serif); font-weight: 400; font-size: 30px; margin: 0; }

/* ---- Run pipeline ---- */
.pipeline {
  background: var(--surface-1); border: 1px solid var(--hairline); border-radius: var(--radius);
  padding: 28px; margin-top: 8px;
}
.pipeline-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 26px; gap: 12px; flex-wrap: wrap; }
.pipeline-top .file { font-size: 20px; font-weight: 500; letter-spacing: -.01em; }
.steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.step { position: relative; padding-top: 16px; }
.step .bar { height: 3px; border-radius: 3px; background: var(--hairline); overflow: hidden; position: relative; }
.step.done .bar { background: var(--text-primary); }
.step.active .bar::after {
  content: ""; position: absolute; inset: 0; width: 40%;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: sweep 1.2s ease-in-out infinite;
}
.step .name { margin-top: 14px; font-size: 14px; font-weight: 500; color: var(--text-muted); }
.step.done .name, .step.active .name { color: var(--text-primary); }
.step .sub { font-family: var(--mono); font-size: 10.5px; color: var(--text-muted); margin-top: 4px; letter-spacing: .04em; }
@keyframes sweep { from { transform: translateX(-100%); } to { transform: translateX(250%); } }

/* ---- Result source (cache vs NLP) ---- */
.source .pill.big { font-size: 12.5px; padding: 9px 16px; color: var(--text-primary); }
.dot.cache { background: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); }
.dot.forced { background: #e0a84a; box-shadow: 0 0 0 4px rgba(224,168,74,.18); }
.source .steps { grid-template-columns: repeat(5, 1fr); }
.source .step.nlp .bar { background: var(--text-primary); }
.source .step.cache .bar { background: var(--accent); }
.source .step .name { color: var(--text-primary); }
.source .step.cache .sub { color: var(--accent); }
.cache-controls { font-size: 13px; color: var(--text-muted); margin-top: 2px; }

.notice {
  display: flex; gap: 14px; align-items: flex-start; background: var(--surface-1);
  border: 1px solid var(--hairline); border-left: 3px solid var(--status-critical);
  border-radius: 12px; padding: 16px 18px; margin-top: 8px; color: var(--text-secondary); font-size: 14.5px;
}
.notice b { color: var(--text-primary); font-weight: 500; display: block; margin-bottom: 2px; }
.notice .icon { color: var(--status-critical); font-weight: 600; }

/* ---- Marquee ---- */
.marquee {
  overflow: hidden; border-top: 1px solid var(--hairline);
  margin: 56px -32px -24px; padding: 22px 0 4px;
  mask-image: linear-gradient(90deg, transparent, #000 10%, #000 90%, transparent);
}
.marquee-track { display: flex; gap: 48px; width: max-content; animation: scroll 38s linear infinite; }
.marquee span { font-family: var(--serif); font-size: 44px; line-height: 1; white-space: nowrap; color: var(--text-secondary); }
.marquee span:nth-of-type(odd) { font-style: italic; color: var(--text-primary); }
.marquee i { font-style: normal; color: var(--accent); font-size: 28px; align-self: center; }
@keyframes scroll { to { transform: translateX(-50%); } }

/* ---- Stat tiles ---- */
.stats { display: grid; grid-template-columns: 1.6fr 1fr 1fr 1fr; gap: 12px; }
.tile {
  background: var(--surface-1); border: 1px solid var(--hairline); border-radius: var(--radius);
  padding: 24px; display: flex; flex-direction: column; justify-content: space-between; min-height: 190px;
  transition: border-color .25s ease, transform .25s ease;
}
.tile:hover { border-color: #45453f; transform: translateY(-2px); }
.tile .label { font-size: 13.5px; color: var(--text-secondary); }
.tile .value { font-weight: 500; font-size: 44px; letter-spacing: -.03em; line-height: 1; margin-top: 24px; }
.tile.hero-tile .value { font-size: clamp(64px, 8vw, 104px); letter-spacing: -.045em; }
.tile .note { font-size: 13px; color: var(--text-muted); margin-top: 10px; }
.tone-value { display: flex; align-items: center; gap: 12px; text-transform: capitalize; }
.tone-value .dot { width: 14px; height: 14px; }

/* ---- Bar lists (keywords, themes) ---- */
.panel { background: var(--surface-1); border: 1px solid var(--hairline); border-radius: var(--radius); padding: 28px; }
.panel-title { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 18px; }
.panel-title h3 { margin: 0; font-size: 16px; font-weight: 500; letter-spacing: -.01em; }
.bars { display: flex; flex-direction: column; }
.bar-row {
  position: relative; display: grid; grid-template-columns: 34px 150px minmax(0, 1fr);
  align-items: center; gap: 14px; padding: 9px 8px; margin: 0 -8px; border-radius: 10px;
  transition: background .2s ease;
}
.bar-row:hover { background: var(--surface-2); }
/* Fixed label columns: every row in a list shares one baseline, so bar
   lengths are comparable across rows. */
.bars.themes .bar-row { grid-template-columns: 34px 180px minmax(0, 1fr); }
.bar-row .rank { font-family: var(--mono); font-size: 11.5px; color: var(--text-muted); }
.bar-row .word { font-size: 15px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* Fill widths are a pure % of the track's content box (proportional to the data);
   right padding reserves room for the value label at the bar tip. */
.bar-row .track {
  display: flex; align-items: center; gap: 10px; border-left: 1px solid var(--hairline);
  min-height: 20px; padding-right: 44px;
}

.bar-row .fill {
  flex: none; height: 12px; background: var(--accent); border-radius: 0 4px 4px 0;
  transform-origin: left; animation: grow .9s cubic-bezier(.2,.7,.1,1) both;
}
.bar-row .count { font-family: var(--mono); font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; }
.dominant { padding: 4px 0 18px; margin-bottom: 8px; border-bottom: 1px solid var(--hairline); }
.dominant b { display: block; font-family: var(--serif); font-weight: 400; font-size: 34px; line-height: 1.1; margin-top: 6px; }
@keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
[data-tip]:hover::after {
  content: attr(data-tip); position: absolute; right: 8px; top: -30px; z-index: 5;
  background: var(--text-primary); color: #0b0b0b; font-size: 12px; font-weight: 500;
  padding: 6px 10px; border-radius: 8px; white-space: nowrap; pointer-events: none;
}
.footnote { font-size: 12.5px; color: var(--text-muted); margin-top: 16px; line-height: 1.5; }

/* ---- Tone ---- */
.grid-2 { display: grid; grid-template-columns: 1.25fr 1fr; gap: 12px; }
.stack { display: flex; gap: 2px; height: 44px; margin-top: 8px; }
.seg {
  position: relative; display: flex; align-items: center; padding: 0 12px; min-width: 6px;
  font-family: var(--mono); font-size: 12px; font-weight: 500;
  animation: grow .9s cubic-bezier(.2,.7,.1,1) both; transform-origin: left;
}
.seg:first-child { border-radius: 4px 0 0 4px; }
.seg:last-child { border-radius: 0 4px 4px 0; }
.seg:only-child { border-radius: 4px; }
.seg.neg { background: var(--div-neg); color: #0b0b0b; }
.seg.neu { background: var(--div-mid); color: #ffffff; }
.seg.pos { background: var(--div-pos); color: #0b0b0b; }
.legend { display: flex; gap: 22px; margin-top: 14px; flex-wrap: wrap; }
.legend span { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-secondary); }
.legend .sw { width: 10px; height: 10px; border-radius: 3px; }
.scale { position: relative; height: 56px; margin-top: 34px; }
.scale .axis { position: absolute; left: 0; right: 0; top: 18px; height: 1px; background: var(--hairline); }
.scale .zero { position: absolute; left: 50%; top: 10px; width: 1px; height: 17px; background: #4a4a45; }
.scale .marker {
  position: absolute; top: 18px; width: 16px; height: 16px; border-radius: 50%;
  transform: translate(-50%, -50%); box-shadow: 0 0 0 2px var(--surface-1);
  animation: slide 1s cubic-bezier(.2,.7,.1,1) both;
}
.scale .marker-label {
  position: absolute; top: -12px; transform: translate(-50%, -100%);
  font-family: var(--mono); font-size: 12px; color: var(--text-primary); white-space: nowrap;
}
.scale .ticks { position: absolute; left: 0; right: 0; top: 34px; display: flex; justify-content: space-between; }
.scale .ticks span { font-family: var(--mono); font-size: 11px; color: var(--text-muted); }
@keyframes slide { from { left: 50% !important; opacity: 0; } }
.indicators { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--hairline); border-radius: 12px; overflow: hidden; margin-top: 26px; }
.indicators div { background: var(--surface-1); padding: 16px; }
.indicators b { display: block; font-size: 26px; font-weight: 500; letter-spacing: -.02em; margin-top: 6px; }

/* ---- Insights ---- */
.insights { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.insight {
  background: var(--surface-1); border: 1px solid var(--hairline); border-radius: var(--radius);
  padding: 26px; display: flex; gap: 18px;
}
.insight .idx { font-family: var(--mono); font-size: 12px; color: var(--accent); padding-top: 4px; }
.insight h4 { margin: 0 0 6px; font-family: var(--serif); font-weight: 400; font-size: 26px; line-height: 1.1; }
.insight p { margin: 0; color: var(--text-secondary); font-size: 14.5px; line-height: 1.55; }

/* ---- Meta footer ---- */
.meta { display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; padding: 28px 0 0; margin-top: 40px; border-top: 1px solid var(--hairline); }
.meta b { display: block; font-family: var(--mono); font-size: 12px; font-weight: 400; color: var(--text-secondary); margin-top: 6px; word-break: break-all; }
.colophon { display: flex; justify-content: space-between; margin-top: 72px; color: var(--text-muted); font-size: 13px; }
.colophon .big { font-family: var(--serif); font-size: clamp(40px, 7vw, 88px); color: var(--text-primary); line-height: 1; letter-spacing: -.02em; }

/* ---- Responsive ---- */
@media (max-width: 900px) {
  [data-testid="stMainBlockContainer"], .block-container { padding: 0 16px 64px !important; }
  .hero-foot, .grid-2, .insights { grid-template-columns: 1fr; }
  .specs { justify-content: flex-start; }
  .stats { grid-template-columns: 1fr 1fr; }
  .stats .hero-tile, .stats .tile:last-child { grid-column: 1 / -1; }
  .meta { grid-template-columns: 1fr 1fr; }
  .marquee { margin: 40px -16px 0; }
  .steps { grid-template-columns: 1fr 1fr; row-gap: 22px; }
  .bar-row { grid-template-columns: 24px 104px minmax(0, 1fr) !important; gap: 10px; }
  .bars.themes .bar-row { grid-template-columns: 24px 150px minmax(0, 1fr) !important; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
"""


# --- HTML building blocks -----------------------------------------------------

def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render(markup: str) -> None:
    st.html(f'<div class="lx">{markup}</div>')


def section(num: str, title: str, aside: str = "") -> None:
    aside_html = f'<div class="aside mono">{aside}</div>' if aside else ""
    render(
        f'<div class="section-head"><span class="num">{num}</span>'
        f"<h2>{title}</h2>{aside_html}</div>"
    )


def nav() -> None:
    online = api_online()
    status = (
        '<span class="dot good"></span>API connected'
        if online
        else '<span class="dot bad"></span>API offline'
    )
    render(
        '<div class="nav"><div class="brand"><span class="brand-mark"></span>textlens</div>'
        f'<div class="pill" title="{esc(API_URL)}">{status}</div></div>'
    )


def hero() -> None:
    render(
        '<div class="hero">'
        '<div class="eyebrow">Text intelligence · NLTK · Prefect · Redis</div>'
        '<h1><span class="reveal">Read</span> <span class="reveal"><em>between</em></span> '
        '<span class="reveal">the lines.</span></h1>'
        '<div class="hero-foot">'
        '<p class="lede">Drop in any plain-text file. We count it, find what it keeps '
        "returning to, read its tone and surface the themes underneath.</p>"
        '<div class="specs">'
        '<div><span class="mono">Format</span><b>.txt · UTF-8</b></div>'
        '<div><span class="mono">Limit</span><b>5 MB</b></div>'
        '<div><span class="mono">Output</span><b>Live dashboard</b></div>'
        "</div></div></div>"
    )


def notice(title: str, body: str) -> None:
    render(
        f'<div class="notice"><span class="icon">✕</span><div><b>{esc(title)}</b>'
        f"{esc(body)}</div></div>"
    )


def pipeline(filename: str, status: str, elapsed: float, run_id: str) -> None:
    # Index of the step currently in progress; earlier steps are done.
    active = {"pending": 1, "running": 2}.get(status, 3)
    steps = [
        ("Uploaded", "file received"),
        ("Queued", "waiting for a worker"),
        ("Analysing", "tokens → keywords · tone · themes"),
        ("Ready", "building dashboard"),
    ]
    cells = "".join(
        f'<div class="step {"done" if i < active else "active" if i == active else ""}">'
        f'<div class="bar"></div><div class="name">{name}</div><div class="sub">{sub}</div></div>'
        for i, (name, sub) in enumerate(steps)
    )
    render(
        '<div class="pipeline"><div class="pipeline-top">'
        f'<div><div class="mono">Now processing</div><div class="file">{esc(filename)}</div></div>'
        f'<div class="pill"><span class="dot good"></span>{elapsed:0.1f}s · {esc(status)}</div>'
        f'</div><div class="steps">{cells}</div>'
        f'<div class="footnote mono">run {esc(run_id)}</div></div>'
    )


STEP_LABELS = {
    "tokens": "Tokenize",
    "stats": "Counts",
    "keywords": "Keywords",
    "tone": "Tone",
    "themes": "Themes",
}


def cache_source(run: dict[str, Any]) -> None:
    """Banner saying whether this result came from the Redis cache or the NLP pipeline."""
    cache = run.get("cache")
    if cache is None:  # runs recorded before per-step tracking existed
        hit = bool(run.get("cache_hit"))
        cache = {"result": "cache" if hit else "nlp", "steps": {}, "forced": False}
    steps = cache.get("steps") or {}

    if cache.get("forced"):
        dot, headline = "forced", "Recomputed · cache skipped"
        detail = "Every step was re-run by the NLP pipeline and the cache was refreshed."
    elif cache["result"] == "cache":
        dot, headline = "cache", "Served from Redis cache"
        detail = "This exact text was analysed before; the stored result was returned instantly."
    elif "cache" in steps.values():
        dot, headline = "good", "Computed · partly cached"
        detail = "Some steps were reused from the cache; the rest ran through the NLP pipeline."
    else:
        dot, headline = "good", "Computed by NLP pipeline"
        detail = "Nothing was cached for this text, so every step ran fresh."

    cells = "".join(
        f'<div class="step {src}"><div class="bar"></div>'
        f'<div class="name">{STEP_LABELS.get(step, step)}</div>'
        f'<div class="sub">{"Redis cache" if src == "cache" else "NLP pipeline"}</div></div>'
        for step, src in steps.items()
    )
    strip = f'<div class="steps">{cells}</div>' if cells else ""
    render(
        '<div class="pipeline source"><div class="pipeline-top">'
        f'<div><div class="mono">Result source</div><div class="footnote" style="margin-top:6px">{detail}</div></div>'
        f'<div class="pill big"><span class="dot {dot}"></span>{headline}</div>'
        f"</div>{strip}</div>"
    )


def marquee(keywords: list[dict[str, Any]]) -> None:
    words = [k["word"] for k in keywords] or ["no", "keywords", "found"]
    items = "".join(f"<span>{esc(w)}</span><i>✳</i>" for w in words)
    # Content is duplicated so the -50% translate loops seamlessly.
    render(f'<div class="marquee" aria-hidden="true"><div class="marquee-track">{items}{items}</div></div>')


def stat_tiles(result: dict[str, Any]) -> None:
    words, sentences = result["word_count"], result["sentence_count"]
    avg = words / sentences if sentences else 0
    pace = "Punchy" if avg < 12 else "Balanced" if avg <= 20 else "Dense"
    tone = result["tone"]
    tone_dot = {"positive": "var(--div-pos)", "negative": "var(--div-neg)"}.get(
        tone["label"], "#8c8b82"
    )
    render(
        '<div class="stats">'
        f'<div class="tile hero-tile"><div class="label">Words</div>'
        f'<div><div class="value">{words:,}</div><div class="note">punctuation excluded</div></div></div>'
        f'<div class="tile"><div class="label">Sentences</div>'
        f'<div><div class="value">{sentences:,}</div><div class="note">detected by Punkt</div></div></div>'
        f'<div class="tile"><div class="label">Words per sentence</div>'
        f'<div><div class="value">{avg:0.1f}</div><div class="note">{pace} rhythm</div></div></div>'
        f'<div class="tile"><div class="label">Overall tone</div>'
        f'<div><div class="value tone-value"><span class="dot" style="background:{tone_dot}"></span>'
        f'{esc(tone["label"])}</div><div class="note">compound {tone["scores"]["compound"]:+.2f}</div></div></div>'
        "</div>"
    )


def keyword_panel(keywords: list[dict[str, Any]]) -> None:
    if not keywords:
        render('<div class="panel"><div class="footnote">No keywords - the text has no content words.</div></div>')
        return
    top = max(k["count"] for k in keywords)
    total = sum(k["count"] for k in keywords)
    rows = []
    for i, k in enumerate(keywords, 1):
        width = k["count"] / top * 100
        share = k["count"] / total * 100
        noun = "occurrence" if k["count"] == 1 else "occurrences"
        rows.append(
            f'<div class="bar-row" data-tip="{esc(k["word"])} - {k["count"]} {noun} · {share:.0f}% of top keywords">'
            f'<span class="rank">{i:02d}</span><span class="word">{esc(k["word"])}</span>'
            f'<span class="track"><span class="fill" style="width:{width:.1f}%;'
            f'animation-delay:{i * 45}ms"></span><span class="count">{k["count"]}</span></span></div>'
        )
    tie_note = ""
    if len({k["count"] for k in keywords}) == 1:
        tie_note = (
            '<div class="footnote">Every keyword appears equally often, so the order '
            "reflects first appearance in the text.</div>"
        )
    render(
        '<div class="panel"><div class="panel-title"><h3>Top keywords by frequency</h3>'
        '<span class="mono">stopwords removed</span></div>'
        f'<div class="bars">{"".join(rows)}</div>{tie_note}</div>'
    )


def tone_panel(tone: dict[str, Any]) -> None:
    s = tone["scores"]
    parts = [("neg", "Negative", s["neg"]), ("neu", "Neutral", s["neu"]), ("pos", "Positive", s["pos"])]
    total = sum(v for _, _, v in parts) or 1
    segs = []
    for key, name, value in parts:
        pct = value / total * 100
        if pct <= 0:
            continue
        # Only label inside a segment when the text comfortably fits.
        label = f"{pct:.0f}%" if pct >= 12 else ""
        segs.append(
            f'<div class="seg {key}" style="flex:{pct:.2f}" data-tip="{name} - {pct:.0f}%">{label}</div>'
        )
    stack = "".join(segs) or '<div class="seg neu" style="flex:1"></div>'
    legend = "".join(
        f'<span><i class="sw" style="background:var(--div-{"mid" if k == "neu" else k})"></i>'
        f"{name} {v / total * 100:.0f}%</span>"
        for k, name, v in parts
    )
    compound = s["compound"]
    pos = (compound + 1) / 2 * 100
    marker_color = "var(--div-pos)" if compound >= 0.05 else "var(--div-neg)" if compound <= -0.05 else "#8c8b82"
    ind = tone["indicators"]
    render(
        '<div class="panel"><div class="panel-title"><h3>Sentiment mix</h3>'
        '<span class="mono">VADER</span></div>'
        f'<div class="stack">{stack}</div><div class="legend">{legend}</div>'
        '<div class="scale"><div class="axis"></div><div class="zero"></div>'
        f'<div class="marker" style="left:{pos:.1f}%;background:{marker_color}">'
        f'<span class="marker-label">{compound:+.2f}</span></div>'
        '<div class="ticks"><span>−1 negative</span><span>0</span><span>positive +1</span></div></div>'
        '<div class="indicators">'
        f'<div><span class="mono">Exclaims</span><b>{ind["exclamation_count"]}</b></div>'
        f'<div><span class="mono">Questions</span><b>{ind["question_count"]}</b></div>'
        f'<div><span class="mono">Shouting</span><b>{ind["uppercase_word_ratio"] * 100:.1f}%</b></div>'
        "</div></div>"
    )


def theme_panel(themes: dict[str, Any]) -> None:
    scores = themes["scores"]
    if not scores:
        render(
            '<div class="panel"><div class="panel-title"><h3>Themes</h3></div>'
            '<div class="footnote">No theme trigger words found in this text.</div></div>'
        )
        return
    top = max(scores.values())
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    rows = []
    for i, (theme, n) in enumerate(ordered, 1):
        name = THEME_NAMES.get(theme, theme.replace("_", " ").capitalize())
        rows.append(
            f'<div class="bar-row" data-tip="{esc(name)} - {n} trigger word{"s" if n != 1 else ""}">'
            f'<span class="rank">{i:02d}</span><span class="word">{esc(name)}</span>'
            f'<span class="track"><span class="fill" style="width:{n / top * 100:.1f}%;'
            f'animation-delay:{i * 60}ms"></span><span class="count">{n}</span></span></div>'
        )
    dominant = " & ".join(THEME_NAMES.get(t, t) for t in themes["dominant"])
    render(
        '<div class="panel"><div class="panel-title"><h3>Theme signals</h3>'
        '<span class="mono">trigger words</span></div>'
        f'<div class="dominant"><span class="mono">Dominant</span><b>{esc(dominant)}</b></div>'
        f'<div class="bars themes">{"".join(rows)}</div></div>'
    )


def build_insights(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Plain-language takeaways derived from the raw analysis."""
    out: list[tuple[str, str]] = []
    tone, scores = result["tone"], result["tone"]["scores"]

    label, c = tone["label"], scores["compound"]
    if label == "positive" and scores["neg"] >= 0.05:
        out.append(("Positive, with friction",
                    f"The overall read is positive ({c:+.2f}), but {scores['neg'] * 100:.0f}% "
                    "of the language is negative. There are complaints mixed in."))
    elif label == "negative" and scores["pos"] >= 0.05:
        out.append(("Negative, not hostile",
                    f"The overall read is negative ({c:+.2f}), though {scores['pos'] * 100:.0f}% "
                    "of the language is still positive."))
    else:
        out.append((f"Reads {label}",
                    f"Compound sentiment is {c:+.2f} on a −1 to +1 scale; "
                    f"{scores['neu'] * 100:.0f}% of the wording is neutral."))

    themes = result["themes"]
    if themes["dominant"]:
        ranked = sorted(themes["scores"].items(), key=lambda kv: -kv[1])
        lead = " & ".join(THEME_NAMES.get(t, t) for t in themes["dominant"])
        body = f"{lead} leads with {ranked[0][1]} trigger words"
        if len(ranked) > len(themes["dominant"]):
            runner, n = ranked[len(themes["dominant"])]
            body += f", ahead of {THEME_NAMES.get(runner, runner).lower()} ({n})"
        out.append((f"Mostly about {lead.lower()}", body + "."))
    else:
        out.append(("No clear theme", "None of the tracked themes are mentioned in this text."))

    kws = result["top_keywords"]
    if kws and kws[0]["count"] > 1:
        out.append((f"“{kws[0]['word']}” keeps coming back",
                    f"It's the most frequent content word, used {kws[0]['count']} times."))
    elif kws:
        out.append(("Varied vocabulary",
                    "No content word repeats, so there's no single recurring subject."))

    words, sentences = result["word_count"], result["sentence_count"]
    avg = words / sentences if sentences else 0
    ind = tone["indicators"]
    if ind["uppercase_word_ratio"] >= 0.05 or ind["exclamation_count"] >= 3:
        out.append(("Raised voice",
                    f"{ind['exclamation_count']} exclamation marks and "
                    f"{ind['uppercase_word_ratio'] * 100:.0f}% all-caps words suggest strong emotion."))
    elif ind["question_count"]:
        out.append(("Open questions",
                    f"The writer asks {ind['question_count']} question"
                    f"{'s' if ind['question_count'] != 1 else ''}; they may expect a reply."))
    else:
        out.append(("Measured delivery",
                    f"About {avg:.0f} words per sentence, with no questions and little emphasis."))
    return out


def insight_cards(result: dict[str, Any]) -> None:
    cards = "".join(
        f'<div class="insight"><span class="idx">{i:02d}</span><div>'
        f"<h4>{esc(title)}</h4><p>{esc(body)}</p></div></div>"
        for i, (title, body) in enumerate(build_insights(result), 1)
    )
    render(f'<div class="insights">{cards}</div>')


def meta_footer(run: dict[str, Any], elapsed: float | None) -> None:
    if (run.get("cache") or {}).get("forced"):
        cached = "Recomputed (cache skipped)"
    else:
        cached = "Redis cache hit" if run.get("cache_hit") else "Fresh analysis"
    took = f"{elapsed:0.1f}s · {cached}" if elapsed is not None else cached
    render(
        '<div class="meta">'
        f'<div><span class="mono">File</span><b>{esc(run.get("filename") or "-")}</b></div>'
        f'<div><span class="mono">Processed</span><b>{esc(took)}</b></div>'
        f'<div><span class="mono">Run ID</span><b>{esc(run.get("run_id", "-"))}</b></div>'
        f'<div><span class="mono">Prefect flow run</span><b>{esc(run.get("flow_run_id") or "-")}</b></div>'
        "</div>"
    )


# --- State & polling ------------------------------------------------------------

def init_state() -> None:
    defaults = {"phase": "idle", "run_id": None, "filename": None, "started": None,
                "run": None, "error": None, "elapsed": None, "poll_errors": 0}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset() -> None:
    for key in ("phase", "run_id", "filename", "started", "run", "error", "elapsed", "poll_errors"):
        st.session_state.pop(key, None)
    init_state()


def submit(file) -> None:
    data = file.getvalue()
    if len(data) > MAX_UPLOAD_BYTES:
        st.session_state.update(phase="error", error=("File too large", "The limit is 5 MB."))
        return
    try:
        resp = upload_file(file.name, data, force=st.session_state.get("force", False))
    except ApiError as exc:
        st.session_state.update(phase="error", error=("Upload rejected", str(exc)))
        return
    st.session_state.update(
        phase="polling", run_id=resp["run_id"], filename=file.name,
        started=time.monotonic(), run={"status": resp["status"]}, error=None, poll_errors=0,
    )


@st.fragment(run_every=POLL_INTERVAL_SECONDS)
def poll() -> None:
    """Re-runs on its own every second; triggers a full rerun once the run finishes."""
    ss = st.session_state
    if ss.phase != "polling":
        return
    elapsed = time.monotonic() - ss.started
    try:
        run = fetch_insights(ss.run_id)
        ss.poll_errors = 0
    except ApiError as exc:
        ss.poll_errors += 1
        if ss.poll_errors >= MAX_POLL_ERRORS:
            ss.update(phase="error", error=("Lost contact with the API", str(exc)))
            st.rerun()
        run = ss.run

    status = run.get("status", "pending")
    if status == "completed":
        ss.update(phase="done", run=run, elapsed=elapsed)
        st.rerun()
    elif status == "failed":
        ss.update(phase="error", error=("Analysis failed", run.get("error") or "Unknown error"))
        st.rerun()
    elif elapsed > POLL_TIMEOUT_SECONDS:
        ss.update(phase="error", error=(
            "Still running", f"No result after {POLL_TIMEOUT_SECONDS}s. Run ID: {ss.run_id}"))
        st.rerun()

    ss.run = run
    pipeline(ss.filename, status, elapsed, ss.run_id)


# --- Page -----------------------------------------------------------------------

def upload_section() -> None:
    ss = st.session_state
    busy = ss.phase == "polling"
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        render(
            '<div class="upload-label"><span class="num mono">01</span><h3>Start with a file</h3></div>'
            '<p class="lede" style="font-size:15px;max-width:40ch">Upload a .txt file and press analyse. '
            "Processing runs in the background; this page updates by itself.</p>"
        )
    with right:
        file = st.file_uploader(
            "Text file", type=["txt"], disabled=busy, label_visibility="collapsed",
            key=f"uploader-{ss.get('uploader_key', 0)}",
        )
        if ss.phase == "done":
            b1, b2 = st.columns(2)
            with b1:
                if st.button("Analyse new file", type="primary", disabled=file is None, width="stretch"):
                    submit(file)
                    st.rerun()
            with b2:
                if st.button("Clear results", type="secondary", width="stretch"):
                    reset()
                    ss.uploader_key = ss.get("uploader_key", 0) + 1
                    st.rerun()
        elif st.button("Analyse text  →", type="primary", disabled=file is None or busy, width="stretch"):
            submit(file)
            st.rerun()
        cache_controls(busy)


def cache_controls(busy: bool) -> None:
    left, right = st.columns([1.4, 1], vertical_alignment="center")
    with left:
        st.toggle("Skip cache, re-run NLP", key="force", disabled=busy,
                  help="Ignore any cached result for this file and recompute every step.")
    with right:
        if st.button("Clear cache", type="secondary", disabled=busy, width="stretch",
                     help="Delete every cached NLP result in Redis."):
            try:
                n = clear_cache()
            except ApiError as exc:
                st.toast(f"Couldn't clear the cache: {exc}", icon="⚠️")
            else:
                st.toast(f"Cleared {n} cached entr{'y' if n == 1 else 'ies'}", icon="🧹")


def dashboard(run: dict[str, Any]) -> None:
    result = run["result"]
    marquee(result["top_keywords"])
    cache_source(run)

    section("02", "At a glance", "Overview")
    stat_tiles(result)

    section("03", "What it keeps saying", f"{len(result['top_keywords'])} keywords")
    keyword_panel(result["top_keywords"])

    section("04", "How it sounds", "Tone & themes")
    col_a, col_b = st.columns([1.25, 1], gap="small")
    with col_a:
        tone_panel(result["tone"])
    with col_b:
        theme_panel(result["themes"])

    section("05", "What it means", "Generated insights")
    insight_cards(result)

    with st.expander("Data table & raw JSON"):
        st.dataframe(
            [{"rank": i, "keyword": k["word"], "count": k["count"]}
             for i, k in enumerate(result["top_keywords"], 1)],
            hide_index=True, width="stretch",
        )
        st.json(result, expanded=False)

    meta_footer(run, st.session_state.elapsed)


def main() -> None:
    init_state()
    st.html(CSS)
    nav()
    hero()
    upload_section()

    ss = st.session_state
    if ss.phase == "polling":
        poll()
    elif ss.phase == "error" and ss.error:
        notice(*ss.error)
    elif ss.phase == "done" and ss.run:
        dashboard(ss.run)

    if not api_online():
        notice("Backend unreachable",
               f"Start the API (or its port-forward) at {API_URL}, or set TEXTLENS_API_URL.")

    render(
        '<div class="colophon"><div class="big">textlens<span style="color:var(--accent)">.</span></div>'
        '<div style="align-self:end;text-align:right">FastAPI · Prefect · Redis · NLTK<br>'
        "Built for reading text at a glance.</div></div>"
    )


main()
