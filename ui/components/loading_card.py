"""Loading state-card + first-token stream primer (mock 04).

Extracted verbatim from app.py (V2 step 3). The spinner copys cross the
module boundary (handle_query composes them), so they are public constants.
"""

from __future__ import annotations

from collections.abc import Iterator

import streamlit as st

SPINNER_TEXT = "Generando la respuesta…"
# Safety net for a still-cold model (warm-up failed or hasn't finished): an honest,
# one-off message so the first, slower answer doesn't read as a hang.
FIRST_SPINNER_TEXT = "Preparando el modelo; la primera respuesta puede tardar unos segundos…"


def render_loading_card(label_text: str) -> None:
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


def spinner_until_first_token(text_stream: Iterator[str]) -> Iterator[str]:
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
