"""Sidebar (mock 02): brand, Ollama-badge slot, Vertical switcher cards, corpus, foot.

render_ollama_badge was extracted verbatim from app.py in V2 step 3; the sidebar
frame (render_sidebar) followed in V2 step 6b-2b. The switcher was rebuilt from a
selectbox into the mock's .domain-card row buttons (welcome button-card pattern).
"""

from __future__ import annotations

from html import escape

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.models import ModelNotPulledError, RagEngineError, VerticalConfig
from ui.components.corpus_meta import corpus_stats_for, document_count_label
from ui.state import KEY_CORPUS_OPEN, KEY_VERTICAL, config_for, select_vertical
from ui.theme import accent_for


def render_sidebar(options: list[tuple[str, str]]) -> tuple[str, DeltaGenerator]:
    """The sidebar frame: brand, badge slot, Vertical switcher cards, corpus, foot.

    Tokens from export/citara.css (.domain-card/.domain-letter/.domain-meta).
    The switcher is the mock's pair of domain cards — the SAME button-card
    pattern as the welcome (select_vertical writes the flat KEY_VERTICAL
    directly; buttons hold no value, so the old selectbox widget-key + sync
    callback are gone). Card chrome (letter chip, real doc count, active
    accent) is injected per-card as data-driven CSS, exactly like the welcome
    cards, so the two switchers can never diverge.

    Badge lifecycle contract: the sidebar CREATES badge_slot and fixes its
    position (the st.empty renders the badge ABOVE the switcher); main FILLS it
    after engine build + preflight — the badge state needs the preflight
    result, which only exists once the engine is built.
    """
    values = [value for value, _ in options]
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
        # A selection must exist before any click (same seeding as the welcome).
        st.session_state.setdefault(KEY_VERTICAL, values[0])
        selected = st.session_state[KEY_VERTICAL]
        card_css: list[str] = []
        for value, display_name in options:
            config = config_for(value)
            accent = accent_for(value)
            card_css.append(
                # Chip letter is config DATA (domain_letter); the sub-label
                # carries the REAL document count via the light corpus_stats_for
                # façade — same cached route and same format as the welcome
                # cards, so the two can never diverge.
                f".st-key-citara-sidebar .st-key-citara-vertical-{value} button::before"
                f"{{content:'{config.domain_letter}';}}"
                f".st-key-citara-sidebar .st-key-citara-vertical-{value} button::after"
                f"{{content:'{document_count_label(config, corpus_stats_for(value))}';}}"
                f".st-key-citara-sidebar .st-key-citara-vertical-{value} button:hover"
                f"{{border-color:{accent['line']};}}"
            )
            if value == selected:
                # .domain-card.active — accent tint + border, chip flipped to
                # solid accent. Hover/focus repeated so the generic hover never
                # washes out the active card (same trick as the welcome).
                # !important: the active state must win the specificity tie with
                # the base [class*] rule regardless of <style> injection order.
                card_css.append(
                    f".st-key-citara-sidebar .st-key-citara-vertical-{value} button,"
                    f".st-key-citara-sidebar .st-key-citara-vertical-{value} button:hover,"
                    f".st-key-citara-sidebar .st-key-citara-vertical-{value} button:focus-visible,"
                    f".st-key-citara-sidebar .st-key-citara-vertical-{value} button:active"
                    f"{{background:{accent['tint']} !important; border-color:{accent['line']} !important; color:var(--text);}}"
                    f".st-key-citara-sidebar .st-key-citara-vertical-{value} button::before"
                    f"{{background:{accent['accent']} !important; color:{accent['on']} !important; border:none !important;}}"
                )
            st.button(
                # Short name like the mock ("Normativa legal"), not the long
                # display_name — same fail-safe fallback as the welcome cards.
                config.domain_name or display_name,
                key=f"citara-vertical-{value}",
                width="stretch",
                on_click=select_vertical,
                args=(value,),
            )
        st.markdown(f"<style>{''.join(card_css)}</style>", unsafe_allow_html=True)
        vertical_value = selected

        # Corpus block (mock 02): status derived from document_count, not
        # hardcoded (fail-safe: an empty corpus must not read "listo").
        stats = corpus_stats_for(vertical_value)
        chunks_fmt = f"{stats.chunk_count:,}".replace(",", " ")
        docs_noun = "doc" if stats.document_count == 1 else "docs"
        corpus_ready = stats.document_count > 0
        st.markdown(
            '<div class="label side-section-label" style="padding-top:22px;">Corpus</div>'
            '<div class="side-corpus">'
            '<div class="side-corpus-status">'
            f'<span class="dot {"dot-ok" if corpus_ready else "dot-neutral"}"></span>'
            f'<span class="side-corpus-status-text">{"Corpus listo" if corpus_ready else "Corpus vacío"}</span></div>'
            f'<div class="side-corpus-sub">{stats.document_count} {docs_noun} · {chunks_fmt} fragmentos</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        # Trigger only: the flag is consumed by render_corpus_dialog in main's
        # render cycle, which opens the st.dialog over the page.
        if st.button("Gestionar corpus ↓", key="citara-corpus-open"):
            st.session_state[KEY_CORPUS_OPEN] = True

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
