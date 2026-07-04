"""Read-only corpus dialog (mock 06): real stats through the engine façade.

Extracted verbatim from app.py (V2 step 4) as an inline expander; rebuilt as a
st.dialog opened from the sidebar's "Gestionar corpus" trigger, so the corpus
detail leaves the main chat column (mock 06 is its own screen, not chat body).
"""

from __future__ import annotations

from html import escape

import streamlit as st

from core.engine import RagEngine
from core.models import RagEngineError, VerticalConfig

from ui.components.error_card import error_presentation, render_error_card
from ui.state import KEY_CORPUS_OPEN


@st.dialog("Corpus")
def _corpus_dialog(engine: RagEngine, config: VerticalConfig) -> None:
    """Read-only Corpus detail (mock 06, loaded state) with REAL stats.

    Presentation calls the engine façade only — never ChromaDB (golden rule 1).
    The mock's "Actualizar corpus" button renders as a command chip because
    re-ingestion from the UI is SPEC §8 future work: the honest control is the
    real CLI command, copyable via st.code's native button. No last-ingested
    stat (no reliable source) and the embedding model comes from config.
    """
    try:
        stats = engine.corpus_stats()
    except RagEngineError as exc:
        render_error_card(**error_presentation(exc, config), key_suffix="corpus")
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


def render_corpus_dialog(engine: RagEngine, config: VerticalConfig) -> None:
    """Open the corpus dialog iff the sidebar's trigger set the flag this run.

    Called unconditionally by main each render cycle; consumes KEY_CORPUS_OPEN
    (one-shot) so a rerun without a new click never reopens the dialog.
    st.dialog provides the native dark backdrop and close-on-dismiss.
    """
    if st.session_state.get(KEY_CORPUS_OPEN):
        st.session_state[KEY_CORPUS_OPEN] = False
        _corpus_dialog(engine, config)
