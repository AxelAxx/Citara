"""Streamlit App + SourcesPanel: the Presentation layer (module 8, FR11 → AC2, AC8).

Pure presentation. This file imports the ``RagEngine`` use case and the domain
*types* it renders (``Answer``, ``Citation``); it builds no prompts, touches no
Chroma, and contains **zero domain logic** (golden rule 1). It also contains **zero
vertical branching** (golden rule 2): the legal/health difference is entirely in the
``VerticalConfig`` the sidebar selects — the UI code below is identical for both.

Import safety: every adapter builds its Ollama/Chroma client lazily, so importing
and running this script never needs a live Ollama. When dependencies are down,
``check_health`` raises a domain error that we translate into the design's
actionable error card — the app shows the fix instead of crashing at import or
on the first query (NFR6/AC7).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from html import escape
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html as _components_html
from streamlit.delta_generator import DeltaGenerator

from core.engine import RagEngine

# Reading the VerticalConfig for UI branding (display_name) is a presentation
# concern, not domain logic. We reuse ingest.py's minimal loader so config is read
# in one place; TODO(module 9): a dedicated config module will own this.
from core.generate import _ABSTENTION_TEXT
from core.ingest import _load_vertical_config
from core.models import (
    Answer,
    Citation,
    CorpusStats,
    EmptyCorpusError,
    ModelNotPulledError,
    OllamaUnreachableError,
    RagEngineError,
    Vertical,
    VerticalConfig,
)

# Brand asset (Citara "C¹" monogram), resolved relative to this file so it works
# regardless of the process CWD. Lives in assets/ (committed), not export/ (ignored).
_APP_DIR = Path(__file__).resolve().parent
_LOGO_PATH = _APP_DIR / "assets" / "citara-mark.svg"

_SPINNER_TEXT = "Generando la respuesta…"
# Safety net for a still-cold model (warm-up failed or hasn't finished): an honest,
# one-off message so the first, slower answer doesn't read as a hang.
_FIRST_SPINNER_TEXT = "Preparando el modelo; la primera respuesta puede tardar unos segundos…"

# --- Citara theme (design tokens + typography) -------------------------------
# One global CSS block derived from export/citara.css: the dark-theme tokens, the
# IBM Plex @import, and typography. Component styles (bubbles, sources, abstention,
# errors) are appended to this block in later sub-steps. Colors are ONLY the
# citara.css tokens — nothing invented. Font rules are scoped to text elements so
# Streamlit's Material icon fonts (expander chevron, sidebar toggle…) stay intact.
_CITARA_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Serif:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root{
  --bg:#101115; --bg2:#0C0D10; --surface:#16181E; --surface2:#1C1F27;
  --elevated:#222631; --border:#282C36; --border-strong:#373C49;
  --text:#ECEEF2; --muted:#9CA0AB; --faint:#686C77;
  --warn:#E6A95C; --warn-tint:rgba(230,169,92,0.13); --warn-line:rgba(230,169,92,0.38);
  --ok:#46CFA6;
  --r-sm:8px; --r-md:12px; --r-lg:18px;
  --font-serif:'IBM Plex Serif',Georgia,serif;
  --font-sans:'IBM Plex Sans',system-ui,sans-serif;
  --font-mono:'IBM Plex Mono',ui-monospace,monospace;
  /* default accent = legal; overridden per-vertical at runtime (config.toml is static) */
  --accent:#7C9CFF; --accent-on:#0C0D10; --accent-tint:rgba(124,156,255,0.13); --accent-line:rgba(124,156,255,0.36);
}

/* Typography: IBM Plex. Scoped to text elements — NOT a universal selector — so the
   Material Symbols icon font Streamlit uses is left alone. */
html, body, .stApp,
.stApp button, .stApp input, .stApp textarea, .stApp select,
[data-testid="stMarkdownContainer"]{
  font-family:var(--font-sans);
}
.stApp h1, .stApp h2, .stApp h3,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3{
  font-family:var(--font-serif); letter-spacing:-.015em;
}
[data-testid="stMarkdownContainer"] code, .stApp code, .stApp pre, .stApp kbd, .mono{
  font-family:var(--font-mono);
}

/* Type helpers (consumed by later component sub-steps). */
.label{ font-family:var(--font-mono); font-size:11px; letter-spacing:.07em; text-transform:uppercase; color:var(--faint); }
.mono{ font-family:var(--font-mono); }
.serif{ font-family:var(--font-serif); }
.muted{ color:var(--muted); }
.faint{ color:var(--faint); }
::selection{ background:var(--accent-tint); }
.dot{ width:7px; height:7px; border-radius:50%; flex-shrink:0; }
.dot-ok{ background:var(--ok); box-shadow:0 0 0 3px rgba(70,207,166,.18); }

/* ---- Boot splash (ported from export/screens/00-splash-animated.html) ---------
   Fixed overlay shown once per session in front of the warm-up; pure-CSS fade-out,
   no JS. Uses --accent tokens so it adapts to the active Vertical. */
.citara-splash{
  position:fixed; inset:0; width:100vw; height:100vh;
  /* Above Streamlit's own chrome: sidebar (z 999991) and header (z 999990) — so the
     splash covers the WHOLE window (sidebar + header + body), nothing shows beneath. */
  z-index:2147483647; display:flex; flex-direction:column;
  align-items:center; justify-content:center;
  /* Block interaction while visible so an accidental click can't rerun and cut the
     splash short; visibility:hidden at the end of the fade releases it afterwards. */
  pointer-events:auto;
  background:radial-gradient(120% 70% at 50% 42%, var(--accent-tint), transparent 60%), var(--bg2);
  animation:citaraSplashOut 3.2s ease forwards;
}
.citara-splash .sp-top{ position:absolute; top:26px; left:0; right:0; display:flex; justify-content:center;
  animation:spFade .9s ease-out both; }
.citara-splash .sp-badge{ display:inline-flex; align-items:center; gap:8px; padding:6px 13px; border-radius:999px;
  background:var(--surface); border:1px solid var(--border); }
.citara-splash .sp-logo{ position:relative; width:132px; height:132px; display:flex; align-items:center; justify-content:center; }
.citara-splash .sp-halo{ position:absolute; inset:-30px; border-radius:50%;
  background:radial-gradient(circle, var(--accent-line), transparent 68%); filter:blur(4px);
  animation:spHalo 1s ease-out .05s both; }
.citara-splash .sp-tile{ position:relative; width:132px; height:132px; border-radius:34px;
  background:var(--accent-tint); border:1px solid var(--accent-line);
  display:flex; align-items:center; justify-content:center; overflow:hidden;
  animation:spTile .9s cubic-bezier(.2,.7,.2,1) .15s both; }
.citara-splash .sp-sweep{ position:absolute; top:0; left:0; width:40%; height:100%;
  background:linear-gradient(90deg, transparent, rgba(255,255,255,.16), transparent);
  animation:spSweep 1.1s ease-in-out 1.15s both; }
.citara-splash .sp-mark{ position:relative; display:inline-block; font-family:var(--font-serif); font-weight:600;
  font-size:76px; line-height:1; letter-spacing:-.02em; color:var(--text); }
.citara-splash .sp-cee{ display:inline-block; animation:spC .6s ease-out .5s both; }
.citara-splash .sp-one{ position:absolute; top:.02em; right:-.30em; display:inline-block; font-family:var(--font-mono);
  font-weight:600; font-size:.30em; color:var(--accent); animation:spOne .6s cubic-bezier(.3,1.4,.4,1) .95s both; }
.citara-splash .sp-word{ margin-top:30px; font-family:var(--font-serif); font-weight:600; font-size:38px;
  letter-spacing:-.01em; color:var(--text); animation:spWord .8s cubic-bezier(.2,.7,.2,1) 1.15s both; }
.citara-splash .sp-rule{ width:46px; height:2px; margin-top:16px; border-radius:2px;
  background:linear-gradient(90deg, transparent, var(--accent), transparent);
  animation:spRule .7s ease-out 1.5s both; }
.citara-splash .sp-tag{ margin-top:16px; font-size:14px; color:var(--muted); text-align:center; max-width:280px;
  line-height:1.5; animation:spFade .8s ease-out 1.7s both; }
.citara-splash .sp-bottom{ position:absolute; bottom:30px; left:0; right:0; display:flex; flex-direction:column;
  align-items:center; gap:14px; animation:spFade .9s ease-out 2.0s both; }
.citara-splash .sp-dots{ display:flex; gap:5px; }
.citara-splash .sp-dots span{ width:7px; height:7px; border-radius:50%; background:var(--accent); animation:spDot 1.4s ease-in-out infinite; }
.citara-splash .sp-dots span:nth-child(2){ animation-delay:.2s; }
.citara-splash .sp-dots span:nth-child(3){ animation-delay:.4s; }

@keyframes spHalo{ 0%{opacity:0; transform:scale(.6);} 45%{opacity:1;} 100%{opacity:.9; transform:scale(1);} }
@keyframes spTile{ 0%{opacity:0; transform:translateY(14px) scale(.82);} 60%{opacity:1; transform:translateY(0) scale(1.04);} 100%{opacity:1; transform:translateY(0) scale(1);} }
@keyframes spC{ 0%{opacity:0; transform:translateY(6px);} 100%{opacity:1; transform:translateY(0);} }
@keyframes spOne{ 0%{opacity:0; transform:translateY(-4px) scale(.4);} 70%{opacity:1; transform:translateY(0) scale(1.25);} 100%{opacity:1; transform:translateY(0) scale(1);} }
@keyframes spWord{ 0%{opacity:0; transform:translateY(10px); letter-spacing:.18em;} 100%{opacity:1; transform:translateY(0); letter-spacing:-.01em;} }
@keyframes spFade{ 0%{opacity:0; transform:translateY(8px);} 100%{opacity:1; transform:translateY(0);} }
@keyframes spRule{ 0%{transform:scaleX(0); opacity:0;} 100%{transform:scaleX(1); opacity:1;} }
@keyframes spSweep{ 0%{transform:translateX(-130%) skewX(-18deg);} 100%{transform:translateX(230%) skewX(-18deg);} }
@keyframes spDot{ 0%,100%{opacity:.3;} 50%{opacity:1;} }
/* Hold the splash, then fade out. visibility:hidden (special-cased to flip only at
   the end) drops it out of the way — no pointer-events in keyframes, since Chromium
   would apply a keyframe-only discrete value for the whole animation. */
@keyframes citaraSplashOut{ 0%,80%{ opacity:1; } 100%{ opacity:0; visibility:hidden; } }

/* ---- Chat bubbles + avatars (ported from export/screens/02-chat.html) ---------
   Pure restyle of st.chat_message: the .row/.bubble-user/.answer/.logo classes from
   citara.css mapped onto Streamlit's stable data-testids (verified against the 1.58
   JS bundle). No Python/layout changes — streaming (st.write_stream) renders into
   the same containers. */
[data-testid="stChatMessage"]{
  background:transparent; padding:0; gap:13px; align-items:flex-start;   /* .row */
}
/* .row.user — right-aligned: row-reverse puts the "Tú" avatar on the right edge */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]){
  flex-direction:row-reverse;
}
/* .bubble-user — the bubble hugs its text instead of stretching the full row */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"]{
  /* margin:0 kills Streamlit's margin:auto, which would center the bubble in the
     leftover row space instead of keeping it against the avatar */
  flex:0 1 auto; width:fit-content; max-width:78%; margin:0;
  background:var(--surface2); border:1px solid var(--border);
  border-radius:14px 14px 4px 14px; padding:12px 16px;
}
/* NOTE: leave the p margins alone — Streamlit's stMarkdownContainer carries a
   -16px bottom margin that cancels the last p's 1rem; zeroing the p margin would
   let that negative margin eat the bubble's bottom padding. */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stMarkdownContainer"] p{
  font-size:15px; line-height:1.55;
}
/* .answer-body — assistant prose in IBM Plex Sans, no bubble (flush on the row) */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stMarkdownContainer"] p{
  font-family:var(--font-sans); font-size:15px; line-height:1.72;
}
/* Replace Streamlit's default material-icon avatars: hide the built-in icon and
   draw the design's marks on the (kept) containers via pseudo-elements. */
[data-testid="stChatMessageAvatarUser"] > *,
[data-testid="stChatMessageAvatarAssistant"] > *{ display:none; }
/* .avatar-user — "Tú" chip */
[data-testid="stChatMessageAvatarUser"]{
  width:30px; height:30px; flex-shrink:0; border-radius:9px;
  background:var(--surface); border:1px solid var(--border);
  display:flex; align-items:center; justify-content:center;
}
[data-testid="stChatMessageAvatarUser"]::after{
  content:'Tú'; font-family:var(--font-mono); font-size:11px; color:var(--muted);
}
/* .logo .avatar — the C¹ monogram tile. Built with pseudo-elements (not the SVG,
   whose blue is baked in) so it follows the per-vertical --accent live. Sizes are
   the design's em math resolved at 32px (C = .56em ⇒ 18px; the ¹ nudged to 6px for
   sub-pixel legibility). */
[data-testid="stChatMessageAvatarAssistant"]{
  position:relative; width:32px; height:32px; flex-shrink:0; border-radius:26%;
  background:var(--accent-tint); border:1px solid var(--accent-line);
  display:flex; align-items:center; justify-content:center;
}
[data-testid="stChatMessageAvatarAssistant"]::before{
  content:'C'; font-family:var(--font-serif); font-weight:600; line-height:1;
  letter-spacing:-.02em; font-size:18px; color:var(--text);
}
[data-testid="stChatMessageAvatarAssistant"]::after{
  content:'1'; position:absolute; top:6px; left:21px; line-height:1;
  font-family:var(--font-mono); font-weight:600; font-size:6px; color:var(--accent);
}

/* ---- SourcesPanel (ported from export/screens/02-chat.html, .sources) ---------
   The st.expander becomes the .sources card (surface, 14px radius, accent chevron);
   each Citation inside renders as a .source-card built in _render_sources_panel.
   Tokens verbatim from citara.css; .src-meta drops the design's bottom margin
   because there is no src-quote below it (see the TODOs in _render_sources_panel). */
[data-testid="stExpander"]{ margin-top:14px; }
[data-testid="stExpander"] details,
[data-testid="stExpander"] > div:first-child{
  background:var(--surface); border:1px solid var(--border); border-radius:14px;
}
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p{
  font-size:12.5px; font-weight:600;
}
[data-testid="stExpander"] summary svg,
[data-testid="stExpander"] summary [data-testid="stIconMaterial"]{
  color:var(--accent);
}
/* Citation rows are horizontal containers (card HTML + a real "Abrir fragmento"
   button) inside a keyed block — the key lands ON the vertical block itself. */
[class*="st-key-citara-sources"]{ gap:9px; }
[class*="st-key-citara-sources"] [data-testid="stHorizontalBlock"]{ gap:9px; align-items:center; }
[class*="st-key-citara-sources"] [data-testid="stHorizontalBlock"] > div:first-child{
  flex:1 1 auto; min-width:0; }
.source-card{ display:flex; align-items:center; gap:13px; padding:13px 14px;
  background:var(--bg); border:1px solid var(--border); border-radius:11px; }
.source-card:hover{ border-color:var(--accent-line); background:var(--surface2); }
[class*="st-key-citara-open-frag"] button{ background:transparent; border:1px solid var(--border);
  border-radius:8px; padding:6px 11px; min-height:0; width:auto; color:var(--muted); }
[class*="st-key-citara-open-frag"] button:hover,
[class*="st-key-citara-open-frag"] button:focus-visible,
[class*="st-key-citara-open-frag"] button:active{
  border-color:var(--accent-line); background:var(--surface2); color:var(--accent); }
[class*="st-key-citara-open-frag"] button p{ font-size:11.5px; }

/* ---- Source fragment viewer (#09-lite, tokens from 09-source-viewer.html) -----
   The dialog shows the REAL chunk text as the mock's paper page. The paper
   colors are citara.css literals on purpose (a printed page stays light in any
   theme; they are design tokens, not new colors). Text only — no PDF render,
   no in-page offsets, no prev/next navigation: that is #09-full. */
.st-key-citara-fragview .frag-head{ display:flex; align-items:center; gap:8px; margin-bottom:14px; }
.st-key-citara-fragview .pdf-page{ position:relative; max-width:392px; margin:0 auto;
  background:#FBFAF6; border:1px solid #E2DDD2; border-radius:5px;
  box-shadow:0 10px 36px -12px rgba(0,0,0,.45); padding:36px 32px; }
.st-key-citara-fragview .pdf-page p{ margin:0; font-family:var(--font-serif); font-size:14px;
  line-height:1.75; color:#2A2620; }
.st-key-citara-fragview mark.hl{ background:#FBE39A; color:#2A2620; padding:1px 2px;
  border-radius:2px; box-shadow:0 0 0 2px #FBE39A; }
.st-key-citara-fragview .frag-note{ margin-top:12px; font-size:11px; color:var(--faint);
  text-align:center; }
.src-index{ width:26px; height:26px; flex-shrink:0; border-radius:7px;
  background:var(--accent-tint); border:1px solid var(--accent-line);
  display:flex; align-items:center; justify-content:center;
  font-family:var(--font-mono); font-size:12px; font-weight:600; color:var(--accent); }
.src-meta{ flex:1; min-width:0; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.src-id{ font-family:var(--font-mono); font-size:12.5px; font-weight:500; }
.src-page{ font-family:var(--font-mono); font-size:10.5px; padding:1px 7px; border-radius:6px;
  background:var(--surface2); border:1px solid var(--border); color:var(--muted); }
.src-type{ margin-left:auto; font-size:10.5px; color:var(--faint); }

/* ---- Abstention (ported from export/screens/02-chat.html) ---------------------
   Calm and neutral on purpose — dashed border, muted greys, NEVER warn/error
   styling: an abstention is the expected honest answer, not a failure (FR8). */
.abstain-label{ display:inline-flex; align-items:center; gap:6px; margin-bottom:8px; padding:3px 9px;
  border-radius:999px; background:var(--surface2); border:1px dashed var(--border-strong);
  font-family:var(--font-mono); font-size:10px; letter-spacing:.05em; text-transform:uppercase;
  color:var(--muted); }
.note{ margin-top:13px; display:flex; gap:11px; background:var(--surface); border:1px solid var(--border);
  border-radius:12px; padding:13px 15px; }
.note-i{ width:20px; height:20px; flex-shrink:0; border-radius:50%; border:1.5px solid var(--muted);
  display:flex; align-items:center; justify-content:center; font-family:var(--font-serif);
  font-style:italic; font-size:12px; color:var(--muted); }
.note-text{ font-size:13px; line-height:1.55; color:var(--muted); }
.note-sub{ font-family:var(--font-mono); font-size:11px; color:var(--faint); }

/* ---- Actionable error card (ported from export/screens/05-errors.html) --------
   Warn tokens — amber "here's the fix", not red alarm. The card look sits on the
   KEYED container (st-key-citara-error-<suffix>): the card mixes raw HTML
   (label/icon/title/body) with real widgets — st.code for a NATIVE copy button,
   st.button for retry/guide — so the amber border must wrap them all.
   Prefix-matched selectors because the key carries a per-instance suffix (the
   history replay can put several cards on one page). */
.state-card{ background:var(--bg); border:1px solid var(--border); border-radius:16px; padding:20px; }
.state-card.warn{ border-color:var(--warn-line); }
[class*="st-key-citara-error-"]{ background:var(--bg); border:1px solid var(--warn-line);
  border-radius:16px; padding:20px; }
[class*="st-key-citara-error-"] [data-testid="stVerticalBlock"]{ gap:0.55rem; }
.err-label{ font-size:10.5px; margin-bottom:14px; }
.err-row{ display:flex; gap:13px; }
.err-icon{ width:30px; height:30px; flex-shrink:0; border-radius:9px; background:var(--warn-tint);
  border:1px solid var(--warn-line); display:flex; align-items:center; justify-content:center;
  font-family:var(--font-serif); font-weight:600; font-size:16px; color:var(--warn); }
.err-main{ flex:1; min-width:0; }
.err-title{ font-size:15px; font-weight:600; margin-bottom:5px; }
.err-body{ font-size:13.5px; line-height:1.55; color:var(--muted); }
.err-body .err-code{ color:var(--text); font-size:12.5px; }
/* the raw English exception, kept visible as an honest secondary trace */
.err-tech{ margin-top:6px; font-family:var(--font-mono); font-size:10.5px; color:var(--faint);
  line-height:1.5; overflow-wrap:anywhere; }
/* command chip + buttons are Streamlit widgets rendered AFTER the HTML block;
   43px inset = icon 30px + the row's 13px gap, aligning them under the body */
[class*="st-key-citara-error-"] [data-testid="stCode"]{ margin-left:43px; }
[class*="st-key-citara-error-"] [data-testid="stCode"] pre{
  background:var(--bg2) !important; border:1px solid var(--border); border-radius:9px;
  font-family:var(--font-mono); font-size:12.5px; padding:9px 12px; }
[class*="st-key-citara-error-"] [data-testid="stHorizontalBlock"]{ margin-left:43px; gap:10px; }
/* .btn-warn / .btn from citara.css; hover/focus repeated so Streamlit's default
   primary-color hover never tints these */
[class*="st-key-citara-retry"] button,
[class*="st-key-citara-retry"] button:hover,
[class*="st-key-citara-retry"] button:focus-visible,
[class*="st-key-citara-retry"] button:active{
  border:none; border-radius:10px; padding:10px 18px; min-height:0; width:auto;
  background:var(--warn); color:var(--bg2); }
[class*="st-key-citara-retry"] button p{ font-size:13.5px; font-weight:600; }
[class*="st-key-citara-guide"] button{
  border:1px solid var(--border-strong); border-radius:10px; padding:10px 18px;
  min-height:0; width:auto; background:transparent; color:var(--muted); }
[class*="st-key-citara-guide"] button:hover,
[class*="st-key-citara-guide"] button:focus-visible,
[class*="st-key-citara-guide"] button:active{
  border-color:var(--border-strong); background:var(--surface2); color:var(--text); }
[class*="st-key-citara-guide"] button p{ font-size:13.5px; }

/* ---- Empty chat state (ported from export/screens/03-chat-empty.html) ---------
   Shown only while the active Vertical's history is empty. The suggestions are
   real st.button widgets restyled as the design's .suggest rows; the keyed
   container (st-key-citara-empty) scopes every rule so no other button changes. */
.st-key-citara-empty{ text-align:center; padding:34px 0 8px; }
.st-key-citara-empty .empty-logo{ position:relative; width:84px; height:84px; margin:0 auto 18px;
  border-radius:26%; background:var(--accent-tint); border:1px solid var(--accent-line);
  display:flex; align-items:center; justify-content:center; }
/* C¹ mark at 84px — same pseudo-element monogram as the chat avatar, scaled with
   the design's em math (C = .56em ⇒ 47px; the ¹ at .30em ⇒ 14px). */
.st-key-citara-empty .empty-logo::before{ content:'C'; font-family:var(--font-serif); font-weight:600;
  font-size:47px; line-height:1; letter-spacing:-.02em; color:var(--text); }
.st-key-citara-empty .empty-logo::after{ content:'1'; position:absolute; top:17px; left:56px;
  font-family:var(--font-mono); font-weight:600; font-size:14px; color:var(--accent); line-height:1; }
/* text-align set per element: Streamlit's markdown container applies its own
   alignment, so the container-level center does not inherit into these. */
.st-key-citara-empty .empty-title{ font-family:var(--font-serif); font-weight:600; font-size:24px;
  color:var(--text); margin:0 0 8px; text-align:center; }
.st-key-citara-empty .empty-sub{ margin:0 auto 28px; max-width:440px; font-size:14.5px;
  color:var(--muted); line-height:1.55; text-align:center; }
.st-key-citara-empty .empty-label{ margin-bottom:12px; text-align:center; }
.st-key-citara-empty [data-testid="stButton"]{ max-width:520px; margin:0 auto; }
.st-key-citara-empty [data-testid="stButton"] > button{
  justify-content:flex-start; text-align:left; gap:11px; padding:13px 15px; border-radius:12px;
  background:var(--surface); border:1px solid var(--border); color:var(--text); min-height:0;
}
/* single-line labels would otherwise center inside the button: Streamlit wraps the
   label in a flex div with justify-content:center that fills the leftover width */
.st-key-citara-empty [data-testid="stButton"] > button > div{ justify-content:flex-start; }
.st-key-citara-empty [data-testid="stButton"] > button [data-testid="stMarkdownContainer"]{
  text-align:left;
}
.st-key-citara-empty [data-testid="stButton"] > button p{ font-size:14px; }
.st-key-citara-empty [data-testid="stButton"] > button::before{
  content:'›'; color:var(--accent); font-family:var(--font-mono); font-size:14px;
}
.st-key-citara-empty [data-testid="stButton"] > button:hover,
.st-key-citara-empty [data-testid="stButton"] > button:focus-visible,
.st-key-citara-empty [data-testid="stButton"] > button:active{
  border-color:var(--accent-line); background:var(--surface2); color:var(--text);
}

/* ---- Welcome / entry screen (tokens from export/screens/01-splash.html) -------
   Two-step entry: a .domain-card per Vertical SELECTS (active = accent tint +
   border, the mock's .domain-card.active); the primary "Comenzar" button ENTERS.
   Cards and CTA are st.button widgets; the letter chip and the sub-label are
   pseudo-elements whose content/colors are injected per-card in _render_welcome
   (button labels are plain markdown — they cannot nest styled children). */
/* Fill the viewport minus Streamlit's header/body chrome and center vertically,
   so the CTA is visible with NO scroll on a ~768px-tall screen. --logo-size is
   the one fluid knob for the C¹ mark: the glyphs below derive from it, so the
   mark scales as one piece instead of drifting apart. */
.st-key-citara-welcome{ text-align:center; padding:4px 0;
  /* offset = 60px header + the 3.5rem/1rem page padding set below (~9rem) */
  min-height:calc(100vh - 9rem); display:flex; flex-direction:column;
  justify-content:center; align-items:center;
  --logo-size:clamp(84px, 11vh, 138px);
  background:radial-gradient(120% 80% at 50% 38%, var(--accent-tint), transparent 55%); }
/* Streamlit's page container pads ~6rem top — at 768px tall that alone pushes
   the CTA below the fold. Reclaim it ONLY while the welcome is on the page
   (:has), so the chat keeps the stock padding. 3.5rem still clears the header. */
.stApp:has(.st-key-citara-welcome) [data-testid="stMainBlockContainer"]{
  padding-top:3.5rem; padding-bottom:1rem; }
/* Compact the container's own vertical rhythm: Streamlit's default 1rem gap ×4
   element slots is pure air here; halving it buys ~32px at 768px. */
.st-key-citara-welcome [data-testid="stVerticalBlock"]{ gap:0.4rem; }
/* guard: keep the inner block full-width under align-items:center, or the card
   row and the CTA would shrink to fit-content */
.st-key-citara-welcome > [data-testid="stVerticalBlock"]{ width:100%; }
/* width:fit-content + margin:auto — Streamlit's markdown container is left-
   aligned, so text-align centering never reaches this block-level badge */
.st-key-citara-welcome .welcome-badge{ display:flex; width:fit-content; align-items:center; gap:8px;
  padding:6px 13px; border-radius:999px; background:var(--surface); border:1px solid var(--border);
  margin:0 auto clamp(10px, 1.6vh, 17px); font-family:var(--font-mono); font-size:11px; color:var(--muted); }
/* C¹ mark, fluid between 84px and the design's 138px. Glyph size/position keep
   the design's ratios of the tile (C = .56 ⇒ 77px at 138; ¹ = .167 ⇒ 23px at
   .20/.66), resolved against --logo-size instead of fixed px. */
.st-key-citara-welcome .welcome-logo{ position:relative; width:var(--logo-size); height:var(--logo-size);
  margin:0 auto clamp(8px, 1.2vh, 10px); border-radius:26%;
  background:var(--accent-tint); border:1px solid var(--accent-line);
  display:flex; align-items:center; justify-content:center; }
.st-key-citara-welcome .welcome-logo::before{ content:'C'; font-family:var(--font-serif); font-weight:600;
  font-size:calc(var(--logo-size)*.56); line-height:1; letter-spacing:-.02em; color:var(--text); }
.st-key-citara-welcome .welcome-logo::after{ content:'1'; position:absolute;
  top:calc(var(--logo-size)*.20); left:calc(var(--logo-size)*.66);
  font-family:var(--font-mono); font-weight:600; font-size:calc(var(--logo-size)*.167);
  color:var(--accent); line-height:1; }
.st-key-citara-welcome .welcome-name{ margin:0 0 clamp(10px, 1.6vh, 16px); font-family:var(--font-serif); font-weight:600;
  font-size:17px; color:var(--text); text-align:center; }
/* padding:0 kills Streamlit's markdown-h1 padding (1.25rem/1rem ⇒ +36px) */
.st-key-citara-welcome .welcome-title{ margin:0 0 clamp(8px, 1.3vh, 10px); padding:0; font-family:var(--font-serif);
  font-weight:600; font-size:clamp(30px, 4.2vh, 42px); line-height:1.12; letter-spacing:-.02em;
  color:var(--text); text-align:center; }
.st-key-citara-welcome .welcome-subtitle{ margin:0 auto clamp(12px, 2.2vh, 22px); max-width:430px; font-size:16px;
  line-height:1.6; color:var(--muted); text-align:center; }
.st-key-citara-welcome .welcome-subtitle strong{ color:var(--text); }
.st-key-citara-welcome .welcome-label{ margin-bottom:8px; text-align:center; }
/* the two-column card row, centered at the design's 540px */
.st-key-citara-welcome [data-testid="stHorizontalBlock"]{ max-width:540px; margin:0 auto; gap:12px; }
/* .domain-card (welcome variant: stacked column) on the st.button */
.st-key-citara-welcome [data-testid="stButton"] > button{
  flex-direction:column; align-items:stretch; gap:10px; padding:18px 18px 16px;
  background:var(--surface); border:1px solid var(--border); border-radius:11px;
  color:var(--text); min-height:0; width:100%;
}
.st-key-citara-welcome [data-testid="stButton"] > button > div{ justify-content:flex-start; }
.st-key-citara-welcome [data-testid="stButton"] > button [data-testid="stMarkdownContainer"]{
  text-align:left;
}
.st-key-citara-welcome [data-testid="stButton"] > button p{
  font-size:13.5px; font-weight:600;  /* .domain-name */
}
.st-key-citara-welcome [data-testid="stButton"] > button::before{
  /* .domain-letter chip — neutral until its card is active; the content and the
     active accent flip are injected per-card in _render_welcome */
  width:30px; height:30px; border-radius:var(--r-sm); display:flex; align-items:center;
  justify-content:center; font-family:var(--font-mono); font-size:13px; font-weight:600;
  background:var(--surface2); color:var(--muted); border:1px solid var(--border);
}
.st-key-citara-welcome [data-testid="stButton"] > button::after{
  /* .domain-meta sub-label; content injected in _render_welcome */
  font-family:var(--font-mono); font-size:10.5px; color:var(--faint); text-align:left;
}
.st-key-citara-welcome [data-testid="stButton"] > button:hover,
.st-key-citara-welcome [data-testid="stButton"] > button:focus-visible,
.st-key-citara-welcome [data-testid="stButton"] > button:active{
  background:var(--surface2); color:var(--text);
}
/* .btn-primary "Comenzar" CTA — shape only; its colors follow the SELECTED
   Vertical and are injected in _render_welcome. Placed after the card rules so
   its equal-specificity overrides (row layout, no chip) win the source-order tie. */
.st-key-citara-welcome .st-key-citara-comenzar{ max-width:540px; margin:0 auto; }
.st-key-citara-welcome .st-key-citara-comenzar button{
  flex-direction:row; justify-content:center; gap:8px; width:100%; min-height:0;
  padding:15px; border:none; border-radius:10px;
  background:var(--accent); color:var(--accent-on);
}
.st-key-citara-welcome .st-key-citara-comenzar button > div{ justify-content:center; }
.st-key-citara-welcome .st-key-citara-comenzar button p{ font-size:15px; font-weight:600; }
.st-key-citara-welcome .welcome-foot{ font-size:12px; color:var(--faint); text-align:center; }

/* ---- Loading answer card (tokens from export/screens/04-loading-answer.html) --
   Shown while retrieval + the first-token wait run; cleared on the first streamed
   fragment (see handle_query). Scoped under the placeholder's st-key so nothing
   leaks into the rest of the chat. Keyframes are citara-prefixed on purpose:
   @keyframes names are page-global, and generic ones (pulse/shimmer) could
   collide with Streamlit's own animations. */
.st-key-citara-loading .loading-label{ font-size:10.5px; margin-bottom:14px; }
.st-key-citara-loading .loading-row{ display:flex; gap:13px; }
/* C¹ avatar tile — same 32px em math as the chat avatar (C = .56em ⇒ 18px), plus
   the mock's pulse while generating */
.st-key-citara-loading .loading-avatar{ position:relative; width:32px; height:32px; flex-shrink:0;
  border-radius:26%; background:var(--accent-tint); border:1px solid var(--accent-line);
  display:flex; align-items:center; justify-content:center;
  animation:citaraPulse 1.4s ease-in-out infinite; }
.st-key-citara-loading .loading-avatar::before{
  content:'C'; font-family:var(--font-serif); font-weight:600; line-height:1;
  letter-spacing:-.02em; font-size:18px; color:var(--text); }
.st-key-citara-loading .loading-avatar::after{
  content:'1'; position:absolute; top:6px; left:21px; line-height:1;
  font-family:var(--font-mono); font-weight:600; font-size:6px; color:var(--accent); }
.st-key-citara-loading .loading-body{ flex:1; min-width:0; }
.st-key-citara-loading .shimmer-line{ height:11px; border-radius:6px; margin-bottom:9px;
  background:linear-gradient(90deg,var(--surface) 0%,var(--surface2) 50%,var(--surface) 100%);
  background-size:200% 100%; animation:citaraShimmer 1.6s linear infinite; }
.st-key-citara-loading .loading-phases{ display:flex; align-items:center; gap:14px; margin-top:15px;
  font-family:var(--font-mono); font-size:11px; }
.st-key-citara-loading .phase-done{ color:var(--accent); }
.st-key-citara-loading .phase-next{ color:var(--faint); }
.st-key-citara-loading .dots{ display:inline-flex; gap:3px; }
.st-key-citara-loading .dots span{ display:inline-block; width:5px; height:5px; border-radius:50%;
  background:var(--accent); animation:citaraDots 1.2s infinite; }
.st-key-citara-loading .dots span:nth-child(2){ animation-delay:.18s; }
.st-key-citara-loading .dots span:nth-child(3){ animation-delay:.36s; }
@keyframes citaraShimmer{ 0%{ background-position:200% 0; } 100%{ background-position:-200% 0; } }
@keyframes citaraPulse{ 0%,100%{ opacity:.55; } 50%{ opacity:1; } }
@keyframes citaraDots{ 0%,80%,100%{ opacity:.25; transform:translateY(0); } 40%{ opacity:1; transform:translateY(-2px); } }

/* ---- Sidebar (tokens from export/screens/02-chat.html: .brand / .local-badge /
   .section-label / .foot-note) --------------------------------------------------
   Everything on the badge is REAL data (VerticalConfig + this run's preflight);
   it renders into a slot filled after _check_dependencies. Scoped under the
   keyed container so nothing leaks outside the sidebar. */
.st-key-citara-sidebar .side-brand{ display:flex; align-items:center; gap:11px; padding:0 4px 4px; }
/* C¹ mark at the design's 38px (same pseudo-element monogram as the chat avatar;
   em math: C = .56em ⇒ 21px, ¹ ⇒ 7px) */
.st-key-citara-sidebar .side-brand-mark{ position:relative; width:38px; height:38px; flex-shrink:0;
  border-radius:26%; background:var(--accent-tint); border:1px solid var(--accent-line);
  display:flex; align-items:center; justify-content:center; }
.st-key-citara-sidebar .side-brand-mark::before{ content:'C'; font-family:var(--font-serif); font-weight:600;
  line-height:1; letter-spacing:-.02em; font-size:21px; color:var(--text); }
.st-key-citara-sidebar .side-brand-mark::after{ content:'1'; position:absolute; top:7px; left:25px;
  line-height:1; font-family:var(--font-mono); font-weight:600; font-size:7px; color:var(--accent); }
.st-key-citara-sidebar .side-brand-text{ display:flex; flex-direction:column; line-height:1.15; gap:1px; }
.st-key-citara-sidebar .side-brand-name{ font-family:var(--font-serif); font-weight:600; font-size:18px;
  color:var(--text); }
.st-key-citara-sidebar .side-brand-sub{ font-size:11.5px; color:var(--faint); }
/* .card .local-badge */
.st-key-citara-sidebar .side-badge{ background:var(--surface); border:1px solid var(--border);
  border-radius:var(--r-md); padding:12px 13px; }
.st-key-citara-sidebar .side-badge-status{ display:flex; align-items:center; gap:8px; margin-bottom:7px;
  font-size:12.5px; font-weight:600; color:var(--text); }
/* amber twin of .dot-ok for the two degraded states; --warn-tint is the halo */
.st-key-citara-sidebar .dot-warn{ background:var(--warn); box-shadow:0 0 0 3px var(--warn-tint); }
/* neutral gray dot for the "Conectando…" interim (engine rebuild in progress) */
.st-key-citara-sidebar .dot-neutral{ background:var(--faint); box-shadow:0 0 0 3px var(--surface2); }
.st-key-citara-sidebar .side-badge-model{ font-family:var(--font-mono); font-size:11px;
  color:var(--muted); margin-bottom:8px; }
.st-key-citara-sidebar .side-badge-local{ font-family:var(--font-mono); font-size:11px; color:var(--faint);
  border-top:1px solid var(--border); padding-top:8px; }
.st-key-citara-sidebar .side-section-label{ padding:0 4px; }
/* .domain-meta token under the switcher: the active Vertical's real doc count */
.st-key-citara-sidebar .side-domain-meta{ font-family:var(--font-mono); font-size:10.5px;
  color:var(--faint); padding:0 4px; }
.st-key-citara-sidebar .side-foot{ padding:14px 4px 0; border-top:1px solid var(--border);
  font-size:11px; color:var(--faint); line-height:1.5; }
/* pin the foot-note to the sidebar bottom (.foot-note's margin-top:auto): the
   keyed class lands ON the stVerticalBlock itself (a flex column) — stretch it
   to the sidebar height and push its last child down. 10rem ≈ the sidebar's
   own chrome (collapse header + paddings) above/below the block. */
.st-key-citara-sidebar{ min-height:calc(100vh - 10rem); }
.st-key-citara-sidebar > div:last-child{ margin-top:auto; }

/* ---- Chat header (tokens from export/screens/02-chat.html .main-head) ---------
   The tag-pill takes the ACTIVE Vertical's accent — the --accent-* vars are
   injected per vertical before this renders, so the pill recolors on switch. */
.st-key-citara-head .head-tags{ display:flex; align-items:center; gap:8px; margin-bottom:9px; }
.st-key-citara-head .tag-pill{ display:inline-flex; align-items:center; gap:6px; padding:3px 9px;
  border-radius:999px; background:var(--accent-tint); border:1px solid var(--accent-line);
  font-family:var(--font-mono); font-size:10.5px; letter-spacing:.04em; text-transform:uppercase;
  color:var(--accent); }
.st-key-citara-head .head-tagline{ font-family:var(--font-mono); font-size:11px; color:var(--faint); }
.st-key-citara-head .head-h1{ margin:6px 0; font-family:var(--font-serif); font-weight:600;
  font-size:30px; letter-spacing:-.015em; color:var(--text); }
.st-key-citara-head .head-subtitle{ margin:0; font-size:14.5px; color:var(--muted);
  max-width:640px; line-height:1.5; }
.st-key-citara-head .head-subtitle strong{ color:var(--text); font-weight:600; }

/* ---- Chat input hint (tokens from citara.css .input-hint) ---------------------
   Flows as the LAST element, right above the pinned chat input: Streamlit's
   bottom container takes no public children, so pinning the hint below the bar
   (as in the mock) would couple to internal DOM — accepted minimal divergence. */
.st-key-citara-input-hint .input-hint{ display:flex; align-items:center; gap:14px;
  flex-wrap:wrap; margin-top:9px; font-size:11px; color:var(--faint); }
.st-key-citara-input-hint .hint-mono{ font-family:var(--font-mono); }

/* ---- Corpus panel (tokens from export/screens/06-corpus.html, loaded state) ---
   3 stat columns, not the mock's 4: "última ingesta" is omitted on purpose —
   ChromaDB keeps no reliable ingest timestamp, showing one would be invented
   data. The model cell is the REAL embedding model from config, never the
   mock's "nomic-embed-text". */
.st-key-citara-corpus .stat-grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }
.st-key-citara-corpus .stat{ background:var(--surface); border:1px solid var(--border);
  border-radius:var(--r-md); padding:15px 16px; }
.st-key-citara-corpus .stat-num{ font-family:var(--font-serif); font-weight:600;
  font-size:26px; line-height:1; color:var(--text); }
.st-key-citara-corpus .stat-model{ font-family:var(--font-mono); font-weight:500;
  font-size:14px; line-height:1.2; word-break:break-all; color:var(--text);
  /* align the mono model name with the serif numbers' baseline block */
  padding-top:6px; }
.st-key-citara-corpus .stat-lbl{ font-size:12px; color:var(--muted); margin-top:6px; }
.st-key-citara-corpus .corpus-label{ margin:4px 0 3px; }
.st-key-citara-corpus .file-rows{ display:flex; flex-direction:column; gap:8px; }
.st-key-citara-corpus .file-row{ display:flex; align-items:center; gap:12px;
  background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:11px 14px; font-family:var(--font-mono); font-size:13px; font-weight:500;
  color:var(--text); }
/* the mock's "Actualizar corpus" button is deliberately a COMMAND chip: st.code
   with its native copy button — re-ingestion from the UI is SPEC §8 future work */
.st-key-citara-corpus [data-testid="stCode"] pre{
  background:var(--bg2) !important; border:1px solid var(--border); border-radius:9px;
  font-family:var(--font-mono); font-size:12.5px; padding:9px 12px; }
.st-key-citara-corpus [data-testid="stVerticalBlock"]{ gap:0.55rem; }
</style>
"""

# Splash overlay markup. The version/model line from the design is intentionally
# dropped (placeholder "v0.4 · llama3.1" — the real model is qwen2.5:7b, and there
# is no version source of truth); the pulsing dots stay as an honest loading cue.
_SPLASH_HTML = """
<div class="citara-splash" id="citara-splash" style="display:none">
  <div class="sp-top">
    <span class="sp-badge"><span class="dot dot-ok"></span><span class="mono" style="font-size:11px; color:var(--muted);">100% local · sin nube</span></span>
  </div>
  <div class="sp-logo">
    <div class="sp-halo"></div>
    <div class="sp-tile"><span class="sp-sweep"></span><span class="sp-mark"><span class="sp-cee">C</span><sup class="sp-one">1</sup></span></div>
  </div>
  <div class="sp-word">Citara</div>
  <div class="sp-rule"></div>
  <div class="sp-tag">Respuestas con su fuente exacta</div>
  <div class="sp-bottom"><div class="sp-dots"><span></span><span></span><span></span></div></div>
</div>
"""

# One-time client-side guard. The overlay above ships hidden (display:none); this
# script — the only way to run JS in Streamlit is a components iframe — reveals it
# exactly once per PAGE LOAD via a window-level flag on the parent. The flag resets
# on a real reload (new window ⇒ splash plays again) but persists across Streamlit's
# reruns and its startup double-run (same window ⇒ never replays). Keyed on a window
# global, NOT sessionStorage, precisely so a reload replays it. Pure-CSS/session_state
# can't do this: Streamlit remounts the markdown element and the CSS animation replays.
_SPLASH_GUARD = """
<script>
(function(){
  try{
    var w = window.parent, d = w.document;
    var el = d.getElementById('citara-splash');
    if(!el) return;
    if(w.__citaraSplashPlayed){
      el.style.display = 'none';   // a remount within this page load — keep it hidden
    } else {
      w.__citaraSplashPlayed = true;
      el.style.display = 'flex';   // first mount this page load — reveal & play once
    }
  }catch(e){ /* if the parent isn't reachable, just leave the splash hidden */ }
})();
</script>
"""

# Per-vertical accent tokens — copied verbatim from export/citara.css (.v-legal /
# .v-salud). health → the "salud" green accent. No colors outside these tokens.
_ACCENT_BY_VERTICAL: dict[str, dict[str, str]] = {
    "legal": {
        "accent": "#7C9CFF", "on": "#0C0D10",
        "tint": "rgba(124,156,255,0.13)", "line": "rgba(124,156,255,0.36)",
    },
    "health": {
        "accent": "#46CFA6", "on": "#06120D",
        "tint": "rgba(70,207,166,0.13)", "line": "rgba(70,207,166,0.36)",
    },
}


def _render_splash() -> None:
    """Render the boot splash — exactly once per page load, in front of the warm-up.

    Rendered before ``_load_engine`` so the overlay is in the DOM while the LLM
    warm-up blocks server-side: the branded ~2.3s animation plays in the browser
    exactly while Qwen loads into VRAM, hiding the cold-start behind the mark.

    Getting "exactly once" is harder than it looks. Streamlit runs the script twice
    in quick succession on first load (initial run + init rerun) and *remounts* the
    markdown element unpredictably on reruns — and a remount replays a CSS entrance
    animation. A ``session_state`` gate makes it worse (it changes the tree between
    the two startup runs, forcing the remount). So neither pure CSS nor a Python gate
    can guarantee a single play — verified empirically (both produced two plays).

    Fix: ship the overlay hidden and let a tiny client-side guard reveal it once per
    page load, keyed on a ``window`` global that resets on reload but survives reruns
    (see ``_SPLASH_GUARD``). On any remount the overlay stays hidden — no replay, no
    flash. JS runs only inside a components iframe, hence the ``_components_html``.
    """
    st.markdown(_SPLASH_HTML, unsafe_allow_html=True)
    # height=0: the guard is behaviour-only (reaches into the parent to reveal the
    # overlay once), so its iframe must take up no visible space.
    _components_html(_SPLASH_GUARD, height=0)


def _inject_theme(vertical_value: str) -> None:
    """Inject the global Citara CSS, then override --accent for the active Vertical.

    config.toml sets a single static primaryColor, so the per-vertical accent (legal
    blue / health green) is driven here through the --accent CSS variable that our
    custom components consume. Re-injected each rerun; cheap and idempotent (Streamlit
    updates the same DOM node in place rather than accumulating <style> blocks).
    """
    st.markdown(_CITARA_CSS, unsafe_allow_html=True)
    a = _ACCENT_BY_VERTICAL.get(vertical_value, _ACCENT_BY_VERTICAL["legal"])
    st.markdown(
        "<style>:root{"
        f"--accent:{a['accent']}; --accent-on:{a['on']};"
        f"--accent-tint:{a['tint']}; --accent-line:{a['line']};"
        "}</style>",
        unsafe_allow_html=True,
    )


# --- cached construction -----------------------------------------------------


@st.cache_data(show_spinner=False)
def _vertical_options() -> list[tuple[str, str]]:
    """The selectable Verticals as (value, display_name), skipping any unconfigured.

    Cached as data because it is just a cheap read of small YAML files; building the
    option list once per session is enough.
    """
    options: list[tuple[str, str]] = []
    for vertical in Vertical:
        try:
            config = _load_vertical_config(vertical)
        except RagEngineError:
            continue  # a Vertical with no/invalid YAML simply isn't offered
        options.append((vertical.value, config.display_name))
    return options


@st.cache_resource(show_spinner=False)
def _load_engine(vertical_value: str) -> RagEngine:
    """Build (and cache) the RagEngine for a Vertical.

    ``cache_resource`` because the engine owns the expensive, reusable Ollama/Chroma
    clients — rebuilding them on every Streamlit rerun (which happens on every
    interaction) would be wasteful and slow. Keyed by the Vertical value, so
    switching Vertical loads that Vertical's engine and keeps each cached.
    """
    engine = RagEngine.from_vertical_config(_load_vertical_config(Vertical(vertical_value)))
    # Warm up the LLM here, inside the memoized builder, so it preloads Qwen into
    # VRAM once per Vertical (on first construction) — never on every rerun — while
    # the user is still reading the UI. This turns the ~4.7GB cold-start into
    # startup latency instead of first-query latency.
    #
    # Best-effort: a warm-up failure (e.g. Ollama down) must NOT block startup. We
    # swallow it because warm-up is a pure optimization and the *same* actionable
    # error is surfaced loudly a moment later by _check_dependencies() — so this is
    # not a silent "hide the cause", it is "don't fail twice" (golden rule 5).
    try:
        engine.warm_up()
    except RagEngineError:
        pass
    return engine


@st.cache_data(show_spinner=False)
def _corpus_stats_for(vertical_value: str) -> CorpusStats:
    """Cached Corpus snapshot per Vertical — the ONE route welcome AND sidebar use.

    Goes through the LIGHT engine façade (VectorStore only): the welcome needs
    counts for BOTH Verticals, and building full engines there would trigger the
    LLM warm-up (~6s each) before the user even picked one. cache_data, not
    resource: a small immutable value object; the Corpus only changes via the
    offline ingest CLI, so reruns can reuse it (the same staleness trade-off
    _load_engine already accepts).
    """
    return RagEngine.corpus_stats_for(_load_vertical_config(Vertical(vertical_value)))


def _document_count_label(config: VerticalConfig, stats: CorpusStats) -> str:
    """"{domain_sublabel} · {n} documento(s)" — the ONE format welcome and sidebar share.

    The count is the REAL one from CorpusStats (the mock's "14 documentos" was a
    placeholder); an empty sublabel degrades to the bare count (fail-safe).
    """
    noun = "documento" if stats.document_count == 1 else "documentos"
    count = f"{stats.document_count} {noun}"
    return f"{config.domain_sublabel} · {count}" if config.domain_sublabel else count


# --- error translation (NFR6/AC7) --------------------------------------------

# All user-visible error copy is born HERE, in Spanish: core/ raises technical
# English messages (those are code, kept as the .err-tech trace), and this layer
# maps the TYPED exception to the mock's actionable card. Commands and model
# names come from the VerticalConfig — never from mock literals (the mock says
# "llama3.1 · 4,7 GB"; the real model is whatever llm_model says, and the weight
# is omitted because there is no reliable source for it).

# core quotes the offending model name single-quoted in its messages.
_QUOTED = re.compile(r"'([^']+)'")


def _error_presentation(exc: RagEngineError, config: VerticalConfig) -> dict[str, str | None]:
    """Map a domain error to the card fields (Spanish copy + real command)."""
    host = escape(config.ollama_base_url.removeprefix("http://").removeprefix("https://"))
    if isinstance(exc, OllamaUnreachableError):
        return {
            "kind": "servicio",
            "title": "Ollama no está disponible",
            "body": (
                "No se pudo conectar con el modelo local en "
                f'<span class="mono err-code">{host}</span>. '
                "Arráncalo en una terminal y reintenta."
            ),
            "command": "ollama serve",
            "technical": str(exc),
            "llm_model": config.llm_model,
            "host": config.ollama_base_url,
        }
    if isinstance(exc, ModelNotPulledError):
        # The missing model can be the LLM or the Embedder's (both preflights
        # raise this type); core carries it single-quoted in the message. The
        # llm_model fallback keeps the command real either way.
        match = _QUOTED.search(str(exc))
        model = match.group(1) if match else config.llm_model
        return {
            "kind": "modelo",
            "title": "El modelo no está descargado",
            "body": (
                f'El modelo <span class="mono err-code">{escape(model)}</span> '
                "no está en Ollama. Descárgalo una sola vez para empezar."
            ),
            "command": f"ollama pull {model}",
            "technical": str(exc),
            "llm_model": config.llm_model,
            "host": config.ollama_base_url,
        }
    if isinstance(exc, EmptyCorpusError):
        return {
            "kind": "corpus",
            "title": "El corpus está vacío",
            "body": (
                "No hay documentos ingestados para esta Vertical. Coloca los PDF en "
                f'<span class="mono err-code">{escape(config.corpus_path)}</span> '
                "y lanza la ingesta desde una terminal."
            ),
            "command": f"python -m core.ingest --vertical {config.vertical.value}",
            "technical": str(exc),
        }
    return {
        "kind": "motor",
        "title": "No se pudo completar la operación",
        "body": (
            "La operación falló de forma inesperada. El detalle técnico de "
            "abajo indica la causa."
        ),
        "technical": str(exc),
    }


@st.dialog("Poner Ollama en marcha")
def _show_install_guide(llm_model: str, host: str) -> None:
    """Spanish step-by-step to install/start Ollama and pull the model.

    Real commands only, model/host from VerticalConfig — the same honesty rule
    as the card itself.
    """
    st.markdown(
        "**1 · Instala Ollama** (una sola vez) desde "
        "[ollama.com/download](https://ollama.com/download)."
    )
    st.markdown(f"**2 · Arranca el servidor** en una terminal; debe quedar escuchando en `{host}`:")
    st.code("ollama serve", language="bash")
    st.markdown("**3 · Descarga el modelo** (una sola vez):")
    st.code(f"ollama pull {llm_model}", language="bash")
    st.markdown("**4 · Vuelve aquí** y pulsa «Reintentar conexión».")


def _render_error_card(
    kind: str,
    title: str,
    body: str,
    command: str | None = None,
    technical: str | None = None,
    llm_model: str | None = None,
    host: str | None = None,
    key_suffix: str = "live",
) -> None:
    """Render an actionable error as the mock's state-card (05-errors.html).

    HTML paints the static part (``body`` is presentation-crafted HTML; dynamic
    values are escaped in _error_presentation). The command is st.code so the
    copy button is REAL (native), and the buttons are real widgets: retry reruns
    the script — the health preflight re-executes on every run — and the guide
    opens a dialog. ``key_suffix`` keeps widget keys unique: the history replay
    plus a live card can put several of these on one page.
    """
    tech_html = f'<div class="err-tech">{escape(technical)}</div>' if technical else ""
    with st.container(key=f"citara-error-{key_suffix}"):
        st.markdown(
            f'<div class="label err-label">Error accionable · {escape(kind)}</div>'
            '<div class="err-row"><div class="err-icon">!</div>'
            f'<div class="err-main"><div class="err-title">{escape(title)}</div>'
            f'<div class="err-body">{body}</div>{tech_html}</div></div>',
            unsafe_allow_html=True,
        )
        if command:
            st.code(command, language="bash")
        # Buttons only where they are functional (the Ollama cards). Download
        # arrives in #05b; "choose another model" is icebox — neither is faked.
        if kind in ("servicio", "modelo") and llm_model and host:
            with st.container(horizontal=True):
                if st.button("Reintentar conexión", key=f"citara-retry-{key_suffix}"):
                    st.rerun()
                if st.button("Ver guía de instalación", key=f"citara-guide-{key_suffix}"):
                    _show_install_guide(llm_model, host)


def _render_corpus_panel(engine: RagEngine, config: VerticalConfig) -> None:
    """Read-only Corpus section (mock 06, loaded state) with REAL stats.

    Presentation calls the engine façade only — never ChromaDB (golden rule 1).
    The mock's "Actualizar corpus" button renders as a command chip because
    re-ingestion from the UI is SPEC §8 future work: the honest control is the
    real CLI command, copyable via st.code's native button. No last-ingested
    stat (no reliable source) and the embedding model comes from config.
    """
    with st.expander("Corpus"):
        try:
            stats = engine.corpus_stats()
        except RagEngineError as exc:
            _render_error_card(**_error_presentation(exc, config), key_suffix="corpus")
            return
        chunks_fmt = f"{stats.chunk_count:,}".replace(",", " ")  # mock: "3 412"
        rows = "".join(
            f'<div class="file-row">{escape(document_id)}</div>'
            for document_id in stats.document_ids
        )
        with st.container(key="citara-corpus"):
            st.markdown(
                '<div class="stat-grid">'
                f'<div class="stat"><div class="stat-num">{stats.document_count}</div>'
                '<div class="stat-lbl">Documentos</div></div>'
                f'<div class="stat"><div class="stat-num">{chunks_fmt}</div>'
                '<div class="stat-lbl">Fragmentos · vectores</div></div>'
                f'<div class="stat"><div class="stat-model">{escape(stats.embedding_model)}</div>'
                '<div class="stat-lbl">Modelo de embedding</div></div></div>',
                unsafe_allow_html=True,
            )
            if rows:
                st.markdown(
                    '<div class="label corpus-label">Documentos ingestados</div>'
                    f'<div class="file-rows">{rows}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                '<div class="label corpus-label">Actualizar corpus (desde terminal)</div>',
                unsafe_allow_html=True,
            )
            st.code(
                f"python -m core.ingest --vertical {config.vertical.value}",
                language="bash",
            )


def _check_dependencies(engine: RagEngine, config: VerticalConfig) -> RagEngineError | None:
    """Run the aggregated preflight, surfacing domain errors as actionable UI.

    Returns None when all prerequisites are met; on failure it renders the
    exact, actionable fix as the design's error card rather than a raw
    traceback, and returns the domain error. The caller derives its boolean
    query gate from it AND the sidebar badge derives its honest state — both
    from this ONE check_health call per rerun (which is also what makes the
    card's "Reintentar conexión", a plain rerun, honest).
    """
    try:
        engine.check_health()
        return None
    except RagEngineError as exc:
        _render_error_card(**_error_presentation(exc, config), key_suffix="preflight")
        return exc


def _render_ollama_badge(
    slot: DeltaGenerator,
    config: VerticalConfig,
    preflight_error: RagEngineError | None,
    connecting: bool = False,
) -> None:
    """Fill the sidebar's .local-badge slot with the REAL Ollama state.

    Three honest states from the preflight that already ran (never a second
    check_health, never a hardcoded green): connected, model-not-pulled (the
    server DID answer — claiming "no connection" would lie the other way), and
    unreachable. ``connecting`` paints the honest interim while the engine
    (re)builds — the slot must never sit empty during a Vertical switch; the
    real state overwrites this same slot once the preflight resolves. Model
    and host come from VerticalConfig, not mock literals.
    """
    if connecting:
        dot, status = "dot-neutral", "Conectando…"
    elif preflight_error is None:
        dot, status = "dot-ok", "Conectado a Ollama"
    elif isinstance(preflight_error, ModelNotPulledError):
        dot, status = "dot-warn", "Modelo no descargado"
    else:
        dot, status = "dot-warn", "Sin conexión con Ollama"
    host = escape(config.ollama_base_url.removeprefix("http://").removeprefix("https://"))
    slot.markdown(
        '<div class="side-badge">'
        f'<div class="side-badge-status"><span class="dot {dot}"></span>'
        f"<span>{status}</span></div>"
        f'<div class="side-badge-model">{escape(config.llm_model)} · {host}</div>'
        '<div class="side-badge-local">Sin conexión a la nube · 100% local</div>'
        "</div>",
        unsafe_allow_html=True,
    )


# --- SourcesPanel (FR9/AC2) --------------------------------------------------


def _render_abstention_label() -> None:
    """The dashed «Sin coincidencias» pill shown above an abstention answer."""
    st.markdown(
        '<span class="abstain-label">Sin coincidencias en los documentos</span>',
        unsafe_allow_html=True,
    )


def _is_abstention_text(text: str) -> bool:
    """Detect an abstention answered in prose.

    The deterministic empty-context guard yields ``_ABSTENTION_TEXT`` whole, but
    the LLM can also open with that same sentence when the retrieved chunks don't
    actually answer the question. Both cases must get the calm abstention
    treatment — and an answer that says "I can't find this" must not dangle a
    contradictory sources list underneath.
    """
    return text.strip().startswith(_ABSTENTION_TEXT)


@st.dialog("Fragmento citado")
def _show_citation_fragment(citation: Citation) -> None:
    """#09-lite source viewer: the REAL chunk text behind one Citation.

    Styled as the mock's paper page (09-source-viewer.html). Text only, straight
    from the retrieved Chunk's provenance — no PDF render, no in-page offsets,
    no prev/next navigation (that is #09-full, a later sub-step).
    """
    passage = escape(citation.chunk_text).replace("\n", "<br>")
    header = (
        f'<span class="src-id">{escape(citation.document_id)}</span>'
        f'<span class="src-page">pág. {citation.page}</span>'
    )
    if citation.section:
        header += f'<span class="src-type">{escape(citation.section)}</span>'
    with st.container(key="citara-fragview"):
        st.markdown(
            f'<div class="frag-head">{header}</div>'
            f'<div class="pdf-page"><p><mark class="hl">{passage}</mark></p></div>'
            '<div class="frag-note">Fragmento recuperado tal cual del documento.</div>',
            unsafe_allow_html=True,
        )


def _render_sources_panel(answer: Answer, key_suffix: str = "live") -> None:
    """Render the Citations behind one Answer: document_id + page (+ section).

    Abstention is shown explicitly as an expected state (no sources), never styled
    as an error — abstaining is the correct behaviour when context is insufficient.
    ``key_suffix`` keeps the "Abrir fragmento" button keys unique across the
    history replay and the live answer (same pattern as the error cards).
    """
    if answer.is_abstention:
        # Calm .note box from the design — neutral greys, no alarm.
        st.markdown(
            '<div class="note"><span class="note-i">i</span><div class="note-text">'
            "Esto es una respuesta esperada, no un fallo. Citara se abstiene cuando "
            "la pregunta queda fuera de los documentos cargados."
            '<br><span class="note-sub">Sin fragmentos con coincidencia suficiente</span>'
            "</div></div>",
            unsafe_allow_html=True,
        )
        return

    with st.expander(f"Fuentes ({len(answer.citations)})"):
        # One row per Citation: the .source-card HTML (index chip + mono
        # document_id + page pill, + section when present) beside a REAL
        # "Abrir fragmento" button opening the #09-lite viewer. document_id/
        # section come from corpus files, so escape them before embedding.
        #
        # TODO: inline [n] markers in the answer body (the design's .cite) need the
        # Generator to emit marker positions; not built yet.
        with st.container(key=f"citara-sources-{key_suffix}"):
            for index, citation in enumerate(answer.citations, start=1):
                meta = (
                    f'<span class="src-id">{escape(citation.document_id)}</span>'
                    f'<span class="src-page">pág. {citation.page}</span>'
                )
                if citation.section:
                    meta += f'<span class="src-type">{escape(citation.section)}</span>'
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.markdown(
                        '<div class="source-card">'
                        f'<div class="src-index">{index}</div>'
                        f'<div class="src-meta">{meta}</div>'
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    # No captured text (e.g. a Citation from an older session
                    # history) → no button; never open an empty viewer.
                    if citation.chunk_text:
                        if st.button(
                            "Abrir fragmento",
                            key=f"citara-open-frag-{key_suffix}-{index}",
                        ):
                            _show_citation_fragment(citation)


# --- chat history (per Vertical) ---------------------------------------------


def _history_for(vertical_value: str) -> list[dict]:
    """The chat history for a Vertical, isolated from the others.

    Keyed by Vertical so switching legal↔health does not mix two distinct
    conversations (and their sources) into one thread.
    """
    histories = st.session_state.setdefault("histories", {})
    return histories.setdefault(vertical_value, [])


def _render_history(history: list[dict]) -> None:
    for index, message in enumerate(history):
        with st.chat_message(message["role"]):
            # Failed turns re-render as the same actionable card, not raw text.
            # Index-suffixed keys: several failed turns = several cards, and
            # their retry/guide buttons must not collide.
            if message.get("error") is not None:
                _render_error_card(**message["error"], key_suffix=f"history-{index}")
                continue
            answer = message.get("answer")
            # Design order: the abstention pill sits ABOVE the answer body.
            if message["role"] == "assistant" and answer is not None and answer.is_abstention:
                _render_abstention_label()
            st.markdown(message["text"])
            # Assistant turns carry their Answer so the SourcesPanel survives reruns.
            if message["role"] == "assistant" and answer is not None:
                _render_sources_panel(answer, key_suffix=f"history-{index}")


def _queue_query(question: str) -> None:
    """on_click of an example-question button: queue it for the next rerun.

    The queued value is consumed at the top of main's render cycle and fed
    through the exact same path as a typed ``st.chat_input`` prompt — one
    handler for both entry points, no duplicated query flow.
    """
    st.session_state["pending_query"] = question


def _render_empty_state(config: VerticalConfig) -> None:
    """The welcome / empty chat state: C¹ monogram, greeting, example questions.

    The example questions are ``VerticalConfig`` data (golden rule 2: nothing
    vertical-specific hardcoded in presentation); a Vertical without them still
    gets the greeting, just with no suggestion list.
    """
    with st.container(key="citara-empty"):
        st.markdown(
            '<div class="empty-logo"></div>'
            '<div class="empty-title">Hola, soy Citara</div>'
            '<p class="empty-sub">Respondo en español basándome solo en los documentos '
            "cargados, y cito la fuente exacta de cada afirmación.</p>",
            unsafe_allow_html=True,
        )
        if not config.example_questions:
            return
        st.markdown(
            '<div class="label empty-label">Prueba a preguntar</div>',
            unsafe_allow_html=True,
        )
        for index, question in enumerate(config.example_questions):
            st.button(
                question,
                key=f"citara-suggest-{index}",
                width="stretch",
                on_click=_queue_query,
                args=(question,),
            )


def _select_vertical(vertical_value: str) -> None:
    """on_click of a welcome domain card: select the Vertical, stay on the welcome.

    Writes the flat "vertical" state — the ONE source of truth for the active
    Vertical, which the sidebar switcher seeds from and syncs back to (see
    _sync_vertical). Selecting is deliberately NOT entering — that is
    "Comenzar"'s job (_enter_chat).
    """
    st.session_state["vertical"] = vertical_value


def _sync_vertical() -> None:
    """on_change of the sidebar switcher: copy the widget value to "vertical".

    The widget key and the flat key are deliberately separate — binding the
    widget directly to "vertical" desyncs on first mount (see the comment at
    the selectbox in main).
    """
    st.session_state["vertical"] = st.session_state["vertical_widget"]


def _enter_chat() -> None:
    """on_click of the welcome's "Comenzar" button: enter the chat.

    ``entered`` stays True for the rest of the session — switching Verticals
    mid-session must never route back through the welcome.
    """
    st.session_state["entered"] = True


def _render_welcome(options: list[tuple[str, str]]) -> None:
    """The entry screen: brand, headline, one selectable card per Vertical, CTA.

    Two-step model: a card SELECTS its Vertical; only "Comenzar" ENTERS the
    chat. Everything on a card is DERIVED, never hardcoded per vertical (golden
    rule 2): title from domain_name (display_name when unset), chip letter from
    domain_letter, sub-label from domain_sublabel — all VerticalConfig — and the
    accent from _ACCENT_BY_VERTICAL. Chip and sub-label are pseudo-elements fed
    by the data-driven <style> block below, because st.button labels cannot
    nest styled children.
    """
    # A selection must exist before any click so one card renders active and
    # "Comenzar" has a target: default to the first configured Vertical.
    st.session_state.setdefault("vertical", options[0][0])
    selected = st.session_state["vertical"]
    with st.container(key="citara-welcome"):
        st.markdown(
            '<div class="welcome-badge"><span class="dot dot-ok"></span>'
            "<span>100% local · sin nube</span></div>"
            '<div class="welcome-logo"></div>'
            '<div class="welcome-name">Citara</div>'
            '<h1 class="welcome-title">Pregunta a tus<br>documentos.</h1>'
            '<p class="welcome-subtitle">Citara responde en español basándose '
            "<strong>solo</strong> en tus documentos, y cita la fuente exacta de "
            "cada afirmación. Todo el procesamiento ocurre en tu equipo.</p>"
            '<div class="label welcome-label">Elige un dominio para empezar</div>',
            unsafe_allow_html=True,
        )
        card_css: list[str] = []
        selected_title = ""
        for column, (value, display_name) in zip(st.columns(len(options)), options):
            config = _load_vertical_config(Vertical(value))
            accent = _ACCENT_BY_VERTICAL.get(value, _ACCENT_BY_VERTICAL["legal"])
            # Fail-safe, not fail-silent: an old YAML without domain_name still
            # renders a titled card — the long display_name — never an empty one.
            card_title = config.domain_name or display_name
            card_css.append(
                # Chip letter is config DATA (domain_letter, not value[0] —
                # health's chip is "S", not "H"). The sub-label carries the REAL
                # document count via the light corpus_stats_for façade (cached;
                # no LLM warm-up on the welcome).
                f".st-key-citara-welcome .st-key-citara-domain-{value} button::before"
                f"{{content:'{config.domain_letter}';}}"
                f".st-key-citara-welcome .st-key-citara-domain-{value} button::after"
                f"{{content:'{_document_count_label(config, _corpus_stats_for(value))}';}}"
                f".st-key-citara-welcome .st-key-citara-domain-{value} button:hover"
                f"{{border-color:{accent['line']};}}"
            )
            if value == selected:
                selected_title = card_title
                # .domain-card.active — accent tint + border on the card, chip
                # flipped to solid accent (the mock's .active .domain-letter).
                # Hover/focus states repeated so the generic gray hover above
                # never washes out the active card.
                card_css.append(
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button,"
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button:hover,"
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button:focus-visible,"
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button:active"
                    f"{{background:{accent['tint']}; border-color:{accent['line']}; color:var(--text);}}"
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button::before"
                    f"{{background:{accent['accent']}; color:{accent['on']}; border:none;}}"
                )
            with column:
                st.button(
                    card_title,
                    key=f"citara-domain-{value}",
                    width="stretch",
                    on_click=_select_vertical,
                    args=(value,),
                )
        # The CTA's colors track the SELECTION, not the page accent — main() brands
        # the welcome once with the first Vertical, so var(--accent) would lag.
        cta_accent = _ACCENT_BY_VERTICAL.get(selected, _ACCENT_BY_VERTICAL["legal"])
        card_css.append(
            ".st-key-citara-welcome .st-key-citara-comenzar button,"
            ".st-key-citara-welcome .st-key-citara-comenzar button:hover,"
            ".st-key-citara-welcome .st-key-citara-comenzar button:focus-visible,"
            ".st-key-citara-welcome .st-key-citara-comenzar button:active"
            f"{{background:{cta_accent['accent']}; color:{cta_accent['on']}; border:none;}}"
        )
        st.markdown(f"<style>{''.join(card_css)}</style>", unsafe_allow_html=True)
        st.button(
            f"Comenzar · {selected_title} →",
            key="citara-comenzar",
            width="stretch",
            on_click=_enter_chat,
        )
        st.markdown(
            '<div class="welcome-foot">No se envía nada a internet · '
            "sin telemetría · sin cuentas</div>",
            unsafe_allow_html=True,
        )


def _render_loading_card(label_text: str) -> None:
    """The mock's loading state-card: pulsing C¹ avatar, shimmer lines, phase row.

    Static presentation mapped to REAL stream milestones, never to timers:
    retrieval already ran (eager, in answer_stream) by the time this paints, so
    "Recuperando fragmentos" is shown done; the card is cleared on the first
    streamed token, which IS the "Redactando" transition. No fake progress.
    """
    st.markdown(
        '<div class="state-card">'
        f'<div class="label loading-label">{label_text}</div>'
        '<div class="loading-row">'
        '<span class="loading-avatar"></span>'
        '<div class="loading-body">'
        '<div class="shimmer-line" style="width:100%;"></div>'
        '<div class="shimmer-line" style="width:92%;"></div>'
        '<div class="shimmer-line" style="width:64%; margin-bottom:0;"></div>'
        '<div class="loading-phases">'
        '<span class="phase-done">✓ Recuperando fragmentos</span>'
        '<span class="phase-next">· Redactando con citas</span>'
        '<span class="dots"><span></span><span></span><span></span></span>'
        "</div></div></div></div>",
        unsafe_allow_html=True,
    )


def _spinner_until_first_token(text_stream: Iterator[str]) -> Iterator[str]:
    """Pull the first fragment eagerly, then re-emit it followed by the rest.

    The cold-model load and the wait for the first token happen on the *first*
    ``next()`` of the stream. Draining that one fragment inside the caller's
    ``st.spinner`` keeps the spinner up across that wait (retrieval + first token),
    then ``st.write_stream`` takes over and renders the tokens as they arrive. Any
    generation error (Ollama down, model missing) surfaces here, still inside the
    caller's try/except.
    """
    iterator = iter(text_stream)
    try:
        first = next(iterator)
    except StopIteration:
        first = None

    def _rejoined() -> Iterator[str]:
        if first is not None:
            yield first
        yield from iterator

    return _rejoined()


# --- main --------------------------------------------------------------------


def main() -> None:
    # Brand the tab with the Citara mark; fall back to an emoji if the SVG icon
    # can't be loaded (older runtime / path issue) so startup never breaks on chrome.
    try:
        st.set_page_config(page_title="Citara", page_icon=str(_LOGO_PATH), layout="centered")
    except Exception:
        st.set_page_config(page_title="Citara", page_icon="📄", layout="centered")

    # Persistent brand mark (top-left of app + sidebar). st.logo lands in Streamlit
    # ≥1.35 (here 1.58); keep a defensive fallback in case the API/asset is missing.
    try:
        st.logo(str(_LOGO_PATH))
    except Exception:
        with st.sidebar:
            st.image(str(_LOGO_PATH), width=40)

    options = _vertical_options()
    if not options:
        # No Vertical yet, so no accent to pick — inject the base theme (default
        # legal accent) just so this card renders styled.
        _inject_theme("legal")
        _render_error_card(
            kind="config",
            title="No hay ninguna Vertical configurada",
            body=escape(
                "Añade config/<vertical>.yaml (p. ej. config/health.yaml) antes "
                "de arrancar la app."
            ),
            key_suffix="boot",
        )
        st.stop()

    values = [value for value, _ in options]
    labels = {value: label for value, label in options}

    # Routing: until a domain card is clicked, the welcome IS the page. `entered`
    # persists for the whole session, so a mid-session Vertical switch (sidebar)
    # never routes back here; a browser reload starts a fresh session → welcome.
    if not st.session_state.get("entered", False):
        # No Vertical picked yet — brand the welcome (and the splash covering it
        # on first load) with the first configured accent.
        _inject_theme(values[0])
        _render_splash()
        _render_welcome(options)
        return

    # Sidebar: brand, Ollama-badge slot, Vertical switcher, foot-note (tokens from
    # export/screens/02-chat.html). The badge state needs the preflight result,
    # which only exists once the engine below is built — the st.empty slot keeps
    # the badge ABOVE the switcher while its content arrives later. The switcher
    # is the ONLY thing that differs between demos; everything after it is
    # identical regardless of which Vertical is chosen.
    with st.sidebar, st.container(key="citara-sidebar"):
        st.markdown(
            '<div class="side-brand"><span class="side-brand-mark"></span>'
            '<span class="side-brand-text"><span class="side-brand-name">Citara</span>'
            '<span class="side-brand-sub">Respuestas con fuente</span></span></div>',
            unsafe_allow_html=True,
        )
        badge_slot = st.empty()
        st.markdown(
            '<div class="label side-section-label">Dominio activo</div>',
            unsafe_allow_html=True,
        )
        # "vertical" (flat session state) is the ONE source of truth for the
        # active Vertical; the widget deliberately has its OWN key. Sharing the
        # key looked cleaner but desyncs: a value written by a welcome on_click
        # renders as index 0 on the widget's first mount, and the next rerun
        # clobbers the session with it (reverting the Vertical to legal).
        current = st.session_state.setdefault("vertical", values[0])
        vertical_value = st.selectbox(
            "Selecciona el dominio",
            values,
            index=values.index(current),
            format_func=lambda v: labels.get(v, v),
            key="vertical_widget",
            on_change=_sync_vertical,
            # the mock's .section-label above replaces the widget's visible
            # label; the label itself stays for accessibility
            label_visibility="collapsed",
        )
        # Real document count for the ACTIVE Vertical — same cached route and
        # same format as the welcome cards, so the two can never diverge.
        active_config = _load_vertical_config(Vertical(vertical_value))
        st.markdown(
            '<div class="side-domain-meta">'
            f"{escape(_document_count_label(active_config, _corpus_stats_for(vertical_value)))}"
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="side-foot">Todo el procesamiento ocurre en tu equipo.</div>',
            unsafe_allow_html=True,
        )

    # Apply the Citara theme + the selected Vertical's accent before rendering the
    # page body, so title/chat pick up IBM Plex and the right accent immediately.
    _inject_theme(vertical_value)

    # Splash BEFORE building the engine: the overlay flushes to the browser, then
    # _load_engine (below) blocks on the LLM warm-up — so the animation covers the
    # cold-start. Rendered every run at a stable position (see _render_splash) so it
    # plays exactly once per page load and never replays on reruns.
    _render_splash()

    config: VerticalConfig = _load_vertical_config(Vertical(vertical_value))
    # The engine (re)build below can block for seconds (warm-up on a Vertical
    # switch): paint the honest "Conectando…" interim now — earliest point where
    # config (the badge's model line) exists — so the slot never sits empty.
    _render_ollama_badge(badge_slot, config, None, connecting=True)
    # Chat header (the mock's .main-head): accent tag-pill with the short
    # Vertical name (fail-safe fallback to display_name, like the welcome
    # cards), the config-sourced tagline (omitted whole when empty), the long
    # display_name as h1, and a static subtitle. Deliberately NOT shared with
    # the welcome's subtitle: the two copys differ in the mock ("tus
    # documentos" vs. "los documentos cargados").
    tagline_html = (
        f'<span class="head-tagline">{escape(config.domain_tagline)}</span>'
        if config.domain_tagline
        else ""
    )
    with st.container(key="citara-head"):
        st.markdown(
            '<div class="head-tags">'
            f'<span class="tag-pill">{escape(config.domain_name or config.display_name)}</span>'
            f"{tagline_html}</div>"
            f'<h1 class="head-h1">{escape(config.display_name)}</h1>'
            '<p class="head-subtitle">Pregunta en español; las respuestas se basan '
            "<strong>solo</strong> en los documentos cargados, con la fuente exacta "
            "de cada afirmación.</p>",
            unsafe_allow_html=True,
        )

    try:
        engine = _load_engine(vertical_value)
    except RagEngineError as exc:
        # A failure to even build the engine (e.g. a missing dependency) — actionable.
        # cache_resource does not memoize exceptions, so the retry rerun rebuilds.
        # Fill the badge honestly before stopping: an empty slot reads as broken.
        _render_ollama_badge(badge_slot, config, exc)
        _render_error_card(**_error_presentation(exc, config), key_suffix="engine")
        st.stop()

    preflight_error = _check_dependencies(engine, config)
    dependencies_ok = preflight_error is None
    _render_ollama_badge(badge_slot, config, preflight_error)

    # Read-only Corpus section under the header — real counts through the
    # engine façade; presentation never touches ChromaDB (golden rule 1).
    _render_corpus_panel(engine, config)

    history = _history_for(vertical_value)

    def handle_query(prompt: str) -> None:
        """The single query path, shared by st.chat_input and the example buttons.

        Nested on purpose: it closes over this run's engine/history/preflight
        instead of threading them through parameters or session state.
        """
        if not dependencies_ok:
            # Dependencies are down; the actionable card — with its own retry —
            # is already on screen. Don't attempt a query that would only fail
            # deeper in, and don't stack a redundant banner (not in the mock).
            return

        # Show the user's question immediately, before any generation, so the slow
        # LLM (1–2 min on local hardware) never makes the app look hung waiting on
        # a spinner.
        history.append({"role": "user", "text": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # First question of the session? If warm-up didn't fully hide the cold
        # start, show an honest heads-up. Simple per-session flag.
        first_query = not st.session_state.get("has_generated", False)
        spinner_text = _FIRST_SPINNER_TEXT if first_query else _SPINNER_TEXT

        with st.chat_message("assistant"):
            try:
                # Consume the engine's PUBLIC streaming seam — the UI knows nothing
                # about the Retriever/Generator inside. answer_stream() runs
                # retrieval eagerly and returns the still-lazy text generator plus
                # the citations derived from the retrieved context.
                streamed = engine.answer_stream(prompt)
                # The loading state-card replaces st.spinner, mapped to real
                # milestones. Citations are already known here (retrieval eager):
                # empty citations ⇒ the hard guard abstains WITHOUT calling the
                # LLM and its only fragment arrives at once — a "generating" card
                # there would be a lie, so skip it. (Soft abstention — citations
                # present but the LLM declines in prose — does show the card:
                # real retrieval and real generation happened.)
                loading_slot = st.empty()
                try:
                    if streamed.citations:
                        with loading_slot.container(key="citara-loading"):
                            _render_loading_card(spinner_text)
                    # The first next() inside blocks through the first-token wait
                    # (cold model load included); the card lives exactly that long.
                    primed = _spinner_until_first_token(streamed.text_stream)
                finally:
                    # Success, RagEngineError or empty stream alike — never leave
                    # the card orphaned above the answer or the error card.
                    loading_slot.empty()
                # Reserve a slot ABOVE the streamed text: a prose abstention is
                # only recognizable once the full text has arrived, but the design
                # places the abstention pill before the answer body.
                label_slot = st.empty()
                full_text = st.write_stream(primed)
                st.session_state["has_generated"] = True
            except RagEngineError as exc:
                # Retrieval/generation failures (empty Collection, Ollama dropped,
                # model not pulled) all carry actionable messages — Ollama-down
                # raises on the first streamed fragment, before any text is shown.
                # Surface them as the design's error card, keep the app alive.
                presentation = _error_presentation(exc, config)
                # "live-" prefix: this run's history was replayed with
                # "history-N" suffixes, so the in-flight card can never collide.
                _render_error_card(**presentation, key_suffix=f"live-{len(history)}")
                history.append(
                    {"role": "assistant", "text": str(exc), "answer": None, "error": presentation}
                )
                return

            # Rebuild the Answer for the SourcesPanel + history. Abstention ⇔ no
            # citations (empty context, deterministic guard) OR the text opens with
            # the abstention sentence (the LLM declined despite retrieved context)
            # — in both cases showing sources under "I can't find this" would
            # contradict the answer, so the Answer drops them.
            if not streamed.citations or _is_abstention_text(full_text):
                answer = Answer.abstention(full_text or _ABSTENTION_TEXT)
                with label_slot.container():
                    _render_abstention_label()
            else:
                answer = Answer(text=full_text, citations=streamed.citations)
            # The suffix must be STABLE across the live→history transition: a
            # button click reruns the script, where this same panel re-renders
            # from history — with a different key the clicked widget would not
            # exist in the new run and the click would be silently dropped.
            # This assistant turn is appended right below, so its history index
            # IS len(history) at this moment (the user turn is already in).
            _render_sources_panel(answer, key_suffix=f"history-{len(history)}")

        history.append({"role": "assistant", "text": answer.text, "answer": answer})

    # A queued example-question click (see _render_empty_state) is consumed at the
    # top of the render cycle, before anything is painted, so its rerun flows
    # through the exact same path as a typed prompt.
    pending_query = st.session_state.pop("pending_query", None)

    # st.chat_input is read BEFORE the empty state on purpose: its value decides
    # whether the welcome renders, and the widget pins itself to the bottom of the
    # page regardless of call order. The placeholder reuses domain_tagline (#02b)
    # — per-Vertical data from config, with the generic fail-safe when unset.
    placeholder = (
        f"Escribe tu pregunta sobre {config.domain_tagline}…"
        if config.domain_tagline
        else "Escribe tu pregunta…"
    )
    prompt = st.chat_input(placeholder) or pending_query

    if not history and not prompt:
        _render_empty_state(config)

    _render_history(history)

    if prompt:
        handle_query(prompt)

    # The hint renders AFTER handle_query so it is always the page's last flowed
    # element, sitting right above the pinned input even on the turn a fresh
    # answer streams in. Static generic copy — not vertical data.
    with st.container(key="citara-input-hint"):
        st.markdown(
            '<div class="input-hint"><span>Solo se usan los documentos de esta '
            "colección.</span>"
            '<span class="hint-mono">Procesado en tu equipo · sin telemetría</span></div>',
            unsafe_allow_html=True,
        )


main()
