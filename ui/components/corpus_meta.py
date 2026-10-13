"""Shared corpus-meta formatting used by both the welcome cards and the sidebar.

These two helpers have two consumers on different screens (welcome cards +
sidebar meta), so neither screen may own them privately — that was a
cross-module private import. Kept out of state.py because that module is the
session-state contract, and this is pure read/format over the engine façade.
"""

from __future__ import annotations

import streamlit as st

from core.engine import RagEngine
from core.models import CorpusStats, VerticalConfig
from ui.state import config_for


@st.cache_data(show_spinner=False)
def corpus_stats_for(vertical_value: str) -> CorpusStats:
    """Cached Corpus snapshot per Vertical — the ONE route welcome AND sidebar use.

    Goes through the LIGHT engine façade (VectorStore only): the welcome needs
    counts for BOTH Verticals, and building full engines there would trigger the
    LLM warm-up (~6s each) before the user even picked one. cache_data, not
    resource: a small immutable value object; the Corpus only changes via the
    offline ingest CLI, so reruns can reuse it (the same staleness trade-off
    _load_engine already accepts).
    """
    return RagEngine.corpus_stats_for(config_for(vertical_value))


def document_count_label(config: VerticalConfig, stats: CorpusStats) -> str:
    """ "{domain_sublabel} · {n} documento(s)" — the ONE format welcome and sidebar share.

    The count is the REAL one from CorpusStats (the mock's "14 documentos" was a
    placeholder); an empty sublabel degrades to the bare count (fail-safe).
    """
    noun = "documento" if stats.document_count == 1 else "documentos"
    count = f"{stats.document_count} {noun}"
    return f"{config.domain_sublabel} · {count}" if config.domain_sublabel else count
