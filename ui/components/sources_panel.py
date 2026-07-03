"""SourcesPanel + abstention rendering (FR8/FR9, AC2/AC3).

Extracted verbatim from app.py (V2 step 3).
"""

from __future__ import annotations

from html import escape

import streamlit as st

from core.generate import ABSTENTION_TEXT
from core.models import Answer, Citation

# --- SourcesPanel (FR9/AC2) --------------------------------------------------


def render_abstention_label() -> None:
    """The dashed «Sin coincidencias» pill shown above an abstention answer."""
    st.markdown(
        '<span class="abstain-label">Sin coincidencias en los documentos</span>',
        unsafe_allow_html=True,
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


def render_sources_panel(answer: Answer, key_suffix: str = "live") -> None:
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
