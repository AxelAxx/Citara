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

from html import escape

import streamlit as st

from core.engine import RagEngine
from core.models import (
    RagEngineError,
    VerticalConfig,
)

from ui.components.chat_header import render_chat_header

# error_presentation is shared public API: the boot/preflight cards here and the
# query path in ui/layout.py map errors through the same function.
from ui.components.error_card import error_presentation, render_error_card
from ui.components.sidebar import render_ollama_badge, render_sidebar
from ui.layout import render_chat_area
from ui.screens.corpus import render_corpus_panel
from ui.screens.welcome import render_welcome
from ui.state import (
    KEY_ENTERED,
    config_for,
    history_for,
    vertical_options,
)
from ui.theme import LOGO_PATH, inject_theme, render_splash


# --- cached construction -----------------------------------------------------


@st.cache_resource(show_spinner=False)
def _load_engine(vertical_value: str) -> RagEngine:
    """Build (and cache) the RagEngine for a Vertical.

    ``cache_resource`` because the engine owns the expensive, reusable Ollama/Chroma
    clients — rebuilding them on every Streamlit rerun (which happens on every
    interaction) would be wasteful and slow. Keyed by the Vertical value, so
    switching Vertical loads that Vertical's engine and keeps each cached.
    """
    engine = RagEngine.from_vertical_config(config_for(vertical_value))
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
        render_error_card(**error_presentation(exc, config), key_suffix="preflight")
        return exc


# --- main --------------------------------------------------------------------


def main() -> None:
    # Brand the tab with the Citara mark; fall back to an emoji if the SVG icon
    # can't be loaded (older runtime / path issue) so startup never breaks on chrome.
    try:
        st.set_page_config(page_title="Citara", page_icon=str(LOGO_PATH), layout="centered")
    except Exception:
        st.set_page_config(page_title="Citara", page_icon="📄", layout="centered")

    # Persistent brand mark (top-left of app + sidebar). st.logo lands in Streamlit
    # ≥1.35 (here 1.58); keep a defensive fallback in case the API/asset is missing.
    try:
        st.logo(str(LOGO_PATH))
    except Exception:
        with st.sidebar:
            st.image(str(LOGO_PATH), width=40)

    options = vertical_options()
    if not options:
        # No Vertical yet, so no accent to pick — inject the base theme (default
        # legal accent) just so this card renders styled.
        inject_theme("legal")
        render_error_card(
            kind="config",
            title="No hay ninguna Vertical configurada",
            body=escape(
                "Añade config/<vertical>.yaml (p. ej. config/health.yaml) antes "
                "de arrancar la app."
            ),
            key_suffix="boot",
        )
        st.stop()

    # values stays in main for the routing below: the welcome (no Vertical picked
    # yet) is branded with the FIRST configured accent, values[0].
    values = [value for value, _ in options]

    # Routing: until a domain card is clicked, the welcome IS the page. `entered`
    # persists for the whole session, so a mid-session Vertical switch (sidebar)
    # never routes back here; a browser reload starts a fresh session → welcome.
    if not st.session_state.get(KEY_ENTERED, False):
        # No Vertical picked yet — brand the welcome (and the splash covering it
        # on first load) with the first configured accent.
        inject_theme(values[0])
        render_splash()
        render_welcome(options)
        return

    # The sidebar owns badge_slot's position (above the switcher); main fills it
    # below, once build+preflight produce a state to show (see render_sidebar).
    vertical_value, badge_slot = render_sidebar(options)

    # Apply the Citara theme + the selected Vertical's accent before rendering the
    # page body, so title/chat pick up IBM Plex and the right accent immediately.
    inject_theme(vertical_value)

    # Splash BEFORE building the engine: the overlay flushes to the browser, then
    # _load_engine (below) blocks on the LLM warm-up — so the animation covers the
    # cold-start. Rendered every run at a stable position (see render_splash) so it
    # plays exactly once per page load and never replays on reruns.
    render_splash()

    config: VerticalConfig = config_for(vertical_value)
    # The engine (re)build below can block for seconds (warm-up on a Vertical
    # switch): paint the honest "Conectando…" interim now — earliest point where
    # config (the badge's model line) exists — so the slot never sits empty.
    render_ollama_badge(badge_slot, config, None, connecting=True)
    # Pre-engine on purpose: the header paints BEFORE _load_engine blocks on the
    # warm-up, and AFTER inject_theme (its tag-pill uses the --accent-* vars).
    render_chat_header(config)

    try:
        engine = _load_engine(vertical_value)
    except RagEngineError as exc:
        # A failure to even build the engine (e.g. a missing dependency) — actionable.
        # cache_resource does not memoize exceptions, so the retry rerun rebuilds.
        # Fill the badge honestly before stopping: an empty slot reads as broken.
        render_ollama_badge(badge_slot, config, exc)
        render_error_card(**error_presentation(exc, config), key_suffix="engine")
        st.stop()

    preflight_error = _check_dependencies(engine, config)
    dependencies_ok = preflight_error is None
    render_ollama_badge(badge_slot, config, preflight_error)

    # Read-only Corpus section under the header — real counts through the
    # engine façade; presentation never touches ChromaDB (golden rule 1).
    render_corpus_panel(engine, config)

    history = history_for(vertical_value)

    render_chat_area(engine, config, history, dependencies_ok=dependencies_ok)


main()
