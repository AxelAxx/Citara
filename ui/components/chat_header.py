"""Permanent chat header (mock .main-head).

Extracted verbatim from main() (V2 cabo 2). Pre-engine: only needs config + the
theme injected by inject_theme, whose --accent-* vars color the tag-pill — must
render before _load_engine so it covers the warm-up.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from core.models import VerticalConfig


def render_chat_header(config: VerticalConfig) -> None:
    """The chat page's permanent header: tag-pill, tagline, h1, subtitle.

    Order dependency: must render AFTER inject_theme(vertical_value) — the
    .tag-pill takes the active Vertical's accent from its --accent-* CSS vars.
    """
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
