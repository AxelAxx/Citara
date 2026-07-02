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

from core.engine import RagEngine

# Reading the VerticalConfig for UI branding (display_name) is a presentation
# concern, not domain logic. We reuse ingest.py's minimal loader so config is read
# in one place; TODO(module 9): a dedicated config module will own this.
from core.generate import _ABSTENTION_TEXT
from core.ingest import _load_vertical_config
from core.models import (
    Answer,
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
.sources-list{ display:flex; flex-direction:column; gap:9px; }
.source-card{ display:flex; align-items:center; gap:13px; padding:13px 14px;
  background:var(--bg); border:1px solid var(--border); border-radius:11px; }
.source-card:hover{ border-color:var(--accent-line); background:var(--surface2); }
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
   .state-card.warn with the warn tokens — amber "here's the fix", not red alarm;
   every RagEngineError carries its own actionable message. */
.state-card{ background:var(--bg); border:1px solid var(--border); border-radius:16px; padding:20px; }
.state-card.warn{ border-color:var(--warn-line); }
.err-label{ font-size:10.5px; margin-bottom:14px; }
.err-row{ display:flex; gap:13px; }
.err-icon{ width:30px; height:30px; flex-shrink:0; border-radius:9px; background:var(--warn-tint);
  border:1px solid var(--warn-line); display:flex; align-items:center; justify-content:center;
  font-family:var(--font-serif); font-weight:600; font-size:16px; color:var(--warn); }
.err-main{ flex:1; min-width:0; }
.err-title{ font-size:15px; font-weight:600; margin-bottom:5px; }
.err-body{ font-size:13.5px; line-height:1.55; color:var(--muted); margin-bottom:13px; }
.err-body .err-code{ color:var(--text); font-size:12.5px; }
.cmd{ display:flex; align-items:center; gap:8px; background:var(--bg2); border:1px solid var(--border);
  border-radius:9px; padding:9px 12px; }
.cmd + .cmd{ margin-top:8px; }
.cmd .sym{ font-family:var(--font-mono); font-size:12px; color:var(--warn); }
/* undo Streamlit's markdown <code> chrome (pink text, tinted bg) inside the chip */
.cmd code{ font-family:var(--font-mono); font-size:12.5px; color:var(--text); background:none; padding:0; }

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


# --- error translation (NFR6/AC7) --------------------------------------------

# Exception type → (category, title) for the actionable error card, checked in
# order (most specific first); anything else falls back to the generic entry in
# _error_presentation. Titles are the user-facing Spanish headline; the exception
# text itself (with the fix) becomes the card body.
_ERROR_PRESENTATION: list[tuple[type[RagEngineError], tuple[str, str]]] = [
    (OllamaUnreachableError, ("servicio", "Ollama no está disponible")),
    (ModelNotPulledError, ("modelo", "Falta un modelo en Ollama")),
    (EmptyCorpusError, ("corpus", "El corpus está vacío")),
]

# Backticked segments inside domain-error messages; the ones that look like shell
# commands get promoted to a copy-friendly command chip on the card.
_BACKTICKED = re.compile(r"`([^`]+)`")
_CMD_PREFIXES = ("ollama ", "python ", "streamlit ", "pip ", "uv ")


def _error_presentation(exc: RagEngineError) -> dict[str, str]:
    """Map a domain error to the card fields (category, title, detail)."""
    for exc_type, (category, title) in _ERROR_PRESENTATION:
        if isinstance(exc, exc_type):
            return {"category": category, "title": title, "detail": str(exc)}
    return {"category": "motor", "title": "No se pudo completar la operación", "detail": str(exc)}


def _render_error_card(category: str, title: str, detail: str) -> None:
    """Render an actionable error as the design's state-card (05-errors.html).

    The card body is the exception's own message (already actionable, golden
    rule 5); any backticked shell command in it is additionally lifted into a
    `$ …` command chip so the fix is copy-friendly. Warn tokens, never red.
    """
    body = escape(detail)
    chips = "".join(
        f'<div class="cmd"><span class="sym">$</span><code>{command}</code></div>'
        for command in _BACKTICKED.findall(body)
        if command.startswith(_CMD_PREFIXES)
    )
    body = _BACKTICKED.sub(r'<span class="mono err-code">\1</span>', body)
    st.markdown(
        '<div class="state-card warn">'
        f'<div class="label err-label">Error accionable · {escape(category)}</div>'
        '<div class="err-row"><div class="err-icon">!</div>'
        f'<div class="err-main"><div class="err-title">{escape(title)}</div>'
        f'<div class="err-body">{body}</div>{chips}</div></div></div>',
        unsafe_allow_html=True,
    )


def _check_dependencies(engine: RagEngine) -> bool:
    """Run the aggregated preflight, surfacing domain errors as actionable UI.

    Returns True when all prerequisites are met. On failure we render the exact,
    actionable fix (start Ollama / pull the model / ingest the corpus) as the
    design's error card rather than a raw traceback, and return False so the
    caller can block querying.
    """
    try:
        engine.check_health()
        return True
    except RagEngineError as exc:
        _render_error_card(**_error_presentation(exc))
    return False


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


def _render_sources_panel(answer: Answer) -> None:
    """Render the Citations behind one Answer: document_id + page (+ section).

    Abstention is shown explicitly as an expected state (no sources), never styled
    as an error — abstaining is the correct behaviour when context is insufficient.
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
        # One .source-card per Citation (index chip + mono document_id + page pill,
        # + section when present). document_id/section come from corpus files, so
        # escape them before embedding in HTML.
        #
        # TODO: the design's «src-quote» passage and the "Abrir fragmento" viewer
        # need the chunk text on Citation — requires core/ changes, out of scope.
        # TODO: inline [n] markers in the answer body (the design's .cite) need the
        # Generator to emit marker positions; not built yet.
        cards: list[str] = []
        for index, citation in enumerate(answer.citations, start=1):
            meta = (
                f'<span class="src-id">{escape(citation.document_id)}</span>'
                f'<span class="src-page">pág. {citation.page}</span>'
            )
            if citation.section:
                meta += f'<span class="src-type">{escape(citation.section)}</span>'
            cards.append(
                '<div class="source-card">'
                f'<div class="src-index">{index}</div>'
                f'<div class="src-meta">{meta}</div>'
                "</div>"
            )
        st.markdown(
            f'<div class="sources-list">{"".join(cards)}</div>',
            unsafe_allow_html=True,
        )


# --- chat history (per Vertical) ---------------------------------------------


def _history_for(vertical_value: str) -> list[dict]:
    """The chat history for a Vertical, isolated from the others.

    Keyed by Vertical so switching legal↔health does not mix two distinct
    conversations (and their sources) into one thread.
    """
    histories = st.session_state.setdefault("histories", {})
    return histories.setdefault(vertical_value, [])


def _render_history(history: list[dict]) -> None:
    for message in history:
        with st.chat_message(message["role"]):
            # Failed turns re-render as the same actionable card, not raw text.
            if message.get("error") is not None:
                _render_error_card(**message["error"])
                continue
            answer = message.get("answer")
            # Design order: the abstention pill sits ABOVE the answer body.
            if message["role"] == "assistant" and answer is not None and answer.is_abstention:
                _render_abstention_label()
            st.markdown(message["text"])
            # Assistant turns carry their Answer so the SourcesPanel survives reruns.
            if message["role"] == "assistant" and answer is not None:
                _render_sources_panel(answer)


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

    Writes the sidebar selectbox's own session key, so the welcome and the
    switcher share ONE source of truth for the active Vertical. Selecting is
    deliberately NOT entering — that is "Comenzar"'s job (_enter_chat).
    """
    st.session_state["vertical"] = vertical_value


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
                # health's chip is "S", not "H"); sub-label has no counts.
                f".st-key-citara-welcome .st-key-citara-domain-{value} button::before"
                f"{{content:'{config.domain_letter}';}}"
                f".st-key-citara-welcome .st-key-citara-domain-{value} button::after"
                f"{{content:'{config.domain_sublabel}';}}"
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
            category="config",
            title="No hay ninguna Vertical configurada",
            detail=(
                "Añade config/<vertical>.yaml (p. ej. config/health.yaml) antes "
                "de arrancar la app."
            ),
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

    # Sidebar Vertical switcher — the ONLY thing that differs between demos. The UI
    # code that follows is identical regardless of which Vertical is chosen.
    with st.sidebar:
        st.header("Vertical")
        vertical_value = st.selectbox(
            "Selecciona el dominio",
            values,
            format_func=lambda v: labels.get(v, v),
            # Shares the welcome's source of truth: the domain card wrote
            # st.session_state["vertical"] before this widget first exists, so
            # the widget seeds itself from that key. No index override — with
            # index=None the widget starts empty instead of reading the key.
            key="vertical",
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
    st.title(config.display_name)  # branding from VerticalConfig
    st.caption("Pregunta en español; las respuestas se basan solo en los documentos.")

    try:
        engine = _load_engine(vertical_value)
    except RagEngineError as exc:
        # A failure to even build the engine (e.g. a missing dependency) — actionable.
        _render_error_card(**_error_presentation(exc))
        st.stop()

    dependencies_ok = _check_dependencies(engine)

    history = _history_for(vertical_value)

    def handle_query(prompt: str) -> None:
        """The single query path, shared by st.chat_input and the example buttons.

        Nested on purpose: it closes over this run's engine/history/preflight
        instead of threading them through parameters or session state.
        """
        if not dependencies_ok:
            # Dependencies are down; the error is already on screen. Don't attempt
            # a query that would only fail deeper in.
            st.warning("Resuelve el problema indicado arriba antes de preguntar.")
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
                # the citations derived from the retrieved context. The spinner
                # covers retrieval AND the wait for the first token (where a cold
                # model would load), then write_stream renders the tokens as they
                # arrive.
                with st.spinner(spinner_text):
                    streamed = engine.answer_stream(prompt)
                    primed = _spinner_until_first_token(streamed.text_stream)
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
                presentation = _error_presentation(exc)
                _render_error_card(**presentation)
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
            _render_sources_panel(answer)

        history.append({"role": "assistant", "text": answer.text, "answer": answer})

    # A queued example-question click (see _render_empty_state) is consumed at the
    # top of the render cycle, before anything is painted, so its rerun flows
    # through the exact same path as a typed prompt.
    pending_query = st.session_state.pop("pending_query", None)

    # st.chat_input is read BEFORE the empty state on purpose: its value decides
    # whether the welcome renders, and the widget pins itself to the bottom of the
    # page regardless of call order.
    prompt = st.chat_input("Escribe tu pregunta…") or pending_query

    if not history and not prompt:
        _render_empty_state(config)

    _render_history(history)

    if not prompt:
        return
    handle_query(prompt)


main()
