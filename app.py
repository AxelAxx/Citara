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
from core.generate import _ABSTENTION_TEXT
from core.models import (
    Answer,
    RagEngineError,
    VerticalConfig,
)

# _error_presentation / _is_abstention_text are module-private on purpose: app.py
# borrows them only until step 5 moves handle_query into ui/layout.py (provisional
# cross-module private imports, same criterion as _ABSTENTION_TEXT above).
from ui.components.error_card import _error_presentation, render_error_card
from ui.components.loading_card import (
    FIRST_SPINNER_TEXT,
    SPINNER_TEXT,
    render_loading_card,
    spinner_until_first_token,
)
from ui.components.sidebar import render_ollama_badge
from ui.components.sources_panel import (
    _is_abstention_text,
    render_abstention_label,
    render_sources_panel,
)
from ui.screens.corpus import render_corpus_panel

# welcome's options producer and cached corpus-stat helpers stay welcome-private:
# main borrows them only until the sidebar/routing move in V2 steps 5-6
# (provisional cross-module private imports, same criterion as above).
from ui.screens.welcome import (
    _corpus_stats_for,
    _document_count_label,
    _vertical_options,
    render_welcome,
)
from ui.state import (
    KEY_ENTERED,
    KEY_HAS_GENERATED,
    KEY_PENDING_QUERY,
    KEY_VERTICAL,
    KEY_VERTICAL_WIDGET,
    config_for,
    history_for,
    queue_query,
    sync_vertical,
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
        render_error_card(**_error_presentation(exc, config), key_suffix="preflight")
        return exc


# --- chat history (per Vertical) ---------------------------------------------


def _render_history(history: list[dict]) -> None:
    for index, message in enumerate(history):
        with st.chat_message(message["role"]):
            # Failed turns re-render as the same actionable card, not raw text.
            # Index-suffixed keys: several failed turns = several cards, and
            # their retry/guide buttons must not collide.
            if message.get("error") is not None:
                render_error_card(**message["error"], key_suffix=f"history-{index}")
                continue
            answer = message.get("answer")
            # Design order: the abstention pill sits ABOVE the answer body.
            if message["role"] == "assistant" and answer is not None and answer.is_abstention:
                render_abstention_label()
            st.markdown(message["text"])
            # Assistant turns carry their Answer so the SourcesPanel survives reruns.
            if message["role"] == "assistant" and answer is not None:
                render_sources_panel(answer, key_suffix=f"history-{index}")


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
                on_click=queue_query,
                args=(question,),
            )


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

    options = _vertical_options()
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

    values = [value for value, _ in options]
    labels = {value: label for value, label in options}

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
        current = st.session_state.setdefault(KEY_VERTICAL, values[0])
        vertical_value = st.selectbox(
            "Selecciona el dominio",
            values,
            index=values.index(current),
            format_func=lambda v: labels.get(v, v),
            key=KEY_VERTICAL_WIDGET,
            on_change=sync_vertical,
            # the mock's .section-label above replaces the widget's visible
            # label; the label itself stays for accessibility
            label_visibility="collapsed",
        )
        # Real document count for the ACTIVE Vertical — same cached route and
        # same format as the welcome cards, so the two can never diverge.
        active_config = config_for(vertical_value)
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
        render_ollama_badge(badge_slot, config, exc)
        render_error_card(**_error_presentation(exc, config), key_suffix="engine")
        st.stop()

    preflight_error = _check_dependencies(engine, config)
    dependencies_ok = preflight_error is None
    render_ollama_badge(badge_slot, config, preflight_error)

    # Read-only Corpus section under the header — real counts through the
    # engine façade; presentation never touches ChromaDB (golden rule 1).
    render_corpus_panel(engine, config)

    history = history_for(vertical_value)

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
        first_query = not st.session_state.get(KEY_HAS_GENERATED, False)
        spinner_text = FIRST_SPINNER_TEXT if first_query else SPINNER_TEXT

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
                            render_loading_card(spinner_text)
                    # The first next() inside blocks through the first-token wait
                    # (cold model load included); the card lives exactly that long.
                    primed = spinner_until_first_token(streamed.text_stream)
                finally:
                    # Success, RagEngineError or empty stream alike — never leave
                    # the card orphaned above the answer or the error card.
                    loading_slot.empty()
                # Reserve a slot ABOVE the streamed text: a prose abstention is
                # only recognizable once the full text has arrived, but the design
                # places the abstention pill before the answer body.
                label_slot = st.empty()
                full_text = st.write_stream(primed)
                st.session_state[KEY_HAS_GENERATED] = True
            except RagEngineError as exc:
                # Retrieval/generation failures (empty Collection, Ollama dropped,
                # model not pulled) all carry actionable messages — Ollama-down
                # raises on the first streamed fragment, before any text is shown.
                # Surface them as the design's error card, keep the app alive.
                presentation = _error_presentation(exc, config)
                # The suffix must be STABLE across the live→history transition
                # (same fix as the SourcesPanel): a button click triggers a
                # rerun where this card re-renders from history — with a "live-"
                # key the clicked widget would not exist in the new run and the
                # first "Ver guía" click would be silently dropped (retry only
                # survived because its action IS the rerun). This failed turn is
                # appended right below, so its history index IS len(history).
                render_error_card(**presentation, key_suffix=f"history-{len(history)}")
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
                    render_abstention_label()
            else:
                answer = Answer(text=full_text, citations=streamed.citations)
            # The suffix must be STABLE across the live→history transition: a
            # button click reruns the script, where this same panel re-renders
            # from history — with a different key the clicked widget would not
            # exist in the new run and the click would be silently dropped.
            # This assistant turn is appended right below, so its history index
            # IS len(history) at this moment (the user turn is already in).
            render_sources_panel(answer, key_suffix=f"history-{len(history)}")

        history.append({"role": "assistant", "text": answer.text, "answer": answer})

    # A queued example-question click (see _render_empty_state) is consumed at the
    # top of the render cycle, before anything is painted, so its rerun flows
    # through the exact same path as a typed prompt.
    pending_query = st.session_state.pop(KEY_PENDING_QUERY, None)

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
