"""Citara theme: design tokens, global CSS, boot splash, and per-collection accents.

Extracted from app.py as V2 step 1 (presentation refactor): the CSS/HTML blocks
moved verbatim -- byte-identical -- only the module seam is new. The one new
surface is ``accent_for``: call sites resolve a collection's accent through it
instead of the raw legal/health dict, so the closed pair stays an internal detail
replaceable by per-collection config (V3/BYOD) without touching callers.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html as _components_html

# Brand asset (Citara "C¹" monogram), resolved relative to the repo root — one level
# up from ui/ — so it works regardless of the process CWD. Lives in assets/
# (committed), not export/ (ignored).
_REPO_ROOT = Path(__file__).resolve().parent.parent
LOGO_PATH = _REPO_ROOT / "assets" / "citara-mark.svg"

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
   pseudo-elements whose content/colors are injected per-card in render_welcome
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
     active accent flip are injected per-card in render_welcome */
  width:30px; height:30px; border-radius:var(--r-sm); display:flex; align-items:center;
  justify-content:center; font-family:var(--font-mono); font-size:13px; font-weight:600;
  background:var(--surface2); color:var(--muted); border:1px solid var(--border);
}
.st-key-citara-welcome [data-testid="stButton"] > button::after{
  /* .domain-meta sub-label; content injected in render_welcome */
  font-family:var(--font-mono); font-size:10.5px; color:var(--faint); text-align:left;
}
.st-key-citara-welcome [data-testid="stButton"] > button:hover,
.st-key-citara-welcome [data-testid="stButton"] > button:focus-visible,
.st-key-citara-welcome [data-testid="stButton"] > button:active{
  background:var(--surface2); color:var(--text);
}
/* .btn-primary "Comenzar" CTA — shape only; its colors follow the SELECTED
   Vertical and are injected in render_welcome. Placed after the card rules so
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


def accent_for(collection_id: str) -> dict[str, str]:
    """Accent token set for one collection, defaulting safely for unknown ids.

    The default mirrors the :root fallback in ``_CITARA_CSS`` (the legal blue), so
    an id with no declared accent — e.g. a future runtime-created collection —
    renders with the neutral brand accent instead of raising. BYOD lens: callers
    key by an opaque id (today the Vertical enum values); the closed legal/health
    pair is this module's private detail, to be replaced by per-collection config
    in V3 without touching any caller.
    """
    return _ACCENT_BY_VERTICAL.get(collection_id, _ACCENT_BY_VERTICAL["legal"])


def render_splash() -> None:
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


def inject_theme(vertical_value: str) -> None:
    """Inject the global Citara CSS, then override --accent for the active Vertical.

    config.toml sets a single static primaryColor, so the per-vertical accent (legal
    blue / health green) is driven here through the --accent CSS variable that our
    custom components consume. Re-injected each rerun; cheap and idempotent (Streamlit
    updates the same DOM node in place rather than accumulating <style> blocks).
    """
    st.markdown(_CITARA_CSS, unsafe_allow_html=True)
    a = accent_for(vertical_value)
    st.markdown(
        "<style>:root{"
        f"--accent:{a['accent']}; --accent-on:{a['on']};"
        f"--accent-tint:{a['tint']}; --accent-line:{a['line']};"
        "}</style>",
        unsafe_allow_html=True,
    )
