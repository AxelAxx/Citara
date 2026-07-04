"""Chat-area layout: empty state, history replay, input, and the query path.

Extracted verbatim from app.py's main() (V2 step 5A). One public entry point,
``render_chat_area``; everything else is private to the module. The known
misplaced-empty-state layout bug moved here WITH the code on purpose — its fix
is step 5B, in theme.py, not in this move.
"""

from __future__ import annotations

import streamlit as st

from core.engine import RagEngine

from core.generate import ABSTENTION_TEXT
from core.models import Answer, RagEngineError, VerticalConfig
from ui.components.error_card import error_presentation, render_error_card
from ui.components.loading_card import (
    FIRST_SPINNER_TEXT,
    SPINNER_TEXT,
    render_loading_card,
    spinner_until_first_token,
)
from ui.components.sources_panel import (
    render_abstention_label,
    render_sources_panel,
)
from ui.state import KEY_HAS_GENERATED, KEY_PENDING_QUERY, queue_query

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


def _is_abstention_text(text: str) -> bool:
    """Detect an abstention answered in prose.

    The deterministic empty-context guard yields ``ABSTENTION_TEXT`` whole, but
    the LLM can also open with that same sentence when the retrieved chunks don't
    actually answer the question. Both cases must get the calm abstention
    treatment — and an answer that says "I can't find this" must not dangle a
    contradictory sources list underneath.
    """
    return text.strip().startswith(ABSTENTION_TEXT)


def render_chat_area(
    engine: RagEngine,
    config: VerticalConfig,
    history: list[dict],
    *,
    dependencies_ok: bool,
) -> None:
    """The chat page body, extracted verbatim from main() (V2 step 5A).

    ``history`` must be the SAME mutable list main() got from history_for:
    _handle_query appends this run's turns to it and derives the live
    key_suffix from len(history) BEFORE each append — the live->history
    contract (fix 9e38ac5) that keeps first clicks from being dropped.
    """

    # Nested (not top-level) on purpose: closing over render_chat_area's params
    # reproduces exactly the closure handle_query had inside main() — the same
    # four objects, no rebinding, zero drift in the verbatim body below.
    def _handle_query(prompt: str) -> None:
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
                presentation = error_presentation(exc, config)
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
                answer = Answer.abstention(full_text or ABSTENTION_TEXT)
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
        _handle_query(prompt)

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
