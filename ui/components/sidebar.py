"""Sidebar (mock 02): brand, Ollama-badge slot, Vertical switcher, meta, foot-note.

render_ollama_badge was extracted verbatim from app.py in V2 step 3; the sidebar
frame (render_sidebar) followed in V2 step 6b-2b, also verbatim.
"""

from __future__ import annotations

from html import escape

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.models import ModelNotPulledError, RagEngineError, VerticalConfig
from ui.components.corpus_meta import corpus_stats_for, document_count_label
from ui.state import KEY_VERTICAL, KEY_VERTICAL_WIDGET, config_for, sync_vertical


def render_sidebar(options: list[tuple[str, str]]) -> tuple[str, DeltaGenerator]:
    """The sidebar frame: brand, badge slot, Vertical switcher, meta, foot-note.

    Tokens from export/screens/02-chat.html. The switcher is the ONLY thing
    that differs between demos; everything after it is identical regardless of
    which Vertical is chosen.

    Badge lifecycle contract: the sidebar CREATES badge_slot and fixes its
    position (the st.empty renders the badge ABOVE the switcher); main FILLS it
    after engine build + preflight — the badge state needs the preflight
    result, which only exists once the engine is built.
    """
    values = [value for value, _ in options]
    labels = {value: label for value, label in options}
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
            f"{escape(document_count_label(active_config, corpus_stats_for(vertical_value)))}"
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="side-foot">Todo el procesamiento ocurre en tu equipo.</div>',
            unsafe_allow_html=True,
        )
    return vertical_value, badge_slot


def render_ollama_badge(
    slot: DeltaGenerator,
    config: VerticalConfig,
    preflight_error: RagEngineError | None,
    connecting: bool = False,
) -> None:
    """Fill the sidebar's .local-badge slot with the REAL Ollama state.

    Three honest states from the preflight that already ran (never a second
    check_health, never a hardcoded green): connected, model-not-pulled (the
    server DID answer — claiming "no connection" would lie the other way), and
    unreachable. ``connecting`` paints the honest interim while the engine
    (re)builds — the slot must never sit empty during a Vertical switch; the
    real state overwrites this same slot once the preflight resolves. Model
    and host come from VerticalConfig, not mock literals.
    """
    if connecting:
        dot, status = "dot-neutral", "Conectando…"
    elif preflight_error is None:
        dot, status = "dot-ok", "Conectado a Ollama"
    elif isinstance(preflight_error, ModelNotPulledError):
        dot, status = "dot-warn", "Modelo no descargado"
    else:
        dot, status = "dot-warn", "Sin conexión con Ollama"
    host = escape(config.ollama_base_url.removeprefix("http://").removeprefix("https://"))
    slot.markdown(
        '<div class="side-badge">'
        f'<div class="side-badge-status"><span class="dot {dot}"></span>'
        f"<span>{status}</span></div>"
        f'<div class="side-badge-model">{escape(config.llm_model)} · {host}</div>'
        '<div class="side-badge-local">Sin conexión a la nube · 100% local</div>'
        "</div>",
        unsafe_allow_html=True,
    )
