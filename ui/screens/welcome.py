"""Welcome / entry screen (mock 01): brand, domain cards, two-step Comenzar.

Extracted from app.py as V2 step 4 — verbatim except _vertical_options, whose
enum iteration became the documented BYOD seam. The corpus-stat helpers the
cards share with the sidebar live in ui.components.corpus_meta (V2 step 6b-1).
"""

from __future__ import annotations

import streamlit as st

from core.models import RagEngineError, Vertical
from ui.components.corpus_meta import corpus_stats_for, document_count_label
from ui.state import KEY_VERTICAL, config_for, enter_chat, select_vertical
from ui.theme import accent_for


@st.cache_data(show_spinner=False)
def _vertical_options() -> list[tuple[str, str]]:
    """The selectable Verticals as (value, display_name), skipping any unconfigured.

    Cached as data because it is just a cheap read of small YAML files; building the
    option list once per session is enough.
    """
    # BYOD seam: the ONE place that decides WHICH collections exist. Today the
    # available collections are exactly the configured Vertical enum values; in
    # V3 this line will list the user's runtime-created Collections instead.
    # Everything downstream (cards, switcher, routing) iterates the returned
    # options and hardcodes neither the count nor the ids.
    available_collection_ids = [vertical.value for vertical in Vertical]

    options: list[tuple[str, str]] = []
    for collection_id in available_collection_ids:
        try:
            config = config_for(collection_id)
        except RagEngineError:
            continue  # a collection with no/invalid YAML simply isn't offered
        options.append((collection_id, config.display_name))
    return options


def render_welcome(options: list[tuple[str, str]]) -> None:
    """The entry screen: brand, headline, one selectable card per Vertical, CTA.

    Two-step model: a card SELECTS its Vertical; only "Comenzar" ENTERS the
    chat. Everything on a card is DERIVED, never hardcoded per vertical (golden
    rule 2): title from domain_name (display_name when unset), chip letter from
    domain_letter, sub-label from domain_sublabel — all VerticalConfig — and the
    accent from accent_for. Chip and sub-label are pseudo-elements fed
    by the data-driven <style> block below, because st.button labels cannot
    nest styled children.
    """
    # A selection must exist before any click so one card renders active and
    # "Comenzar" has a target: default to the first configured Vertical.
    st.session_state.setdefault(KEY_VERTICAL, options[0][0])
    selected = st.session_state[KEY_VERTICAL]
    with st.container(key="citara-welcome"):
        st.markdown(
            '<div class="welcome-badge"><span class="dot dot-ok"></span>'
            "<span>100% local · sin nube</span></div>"
            '<div class="welcome-logo"></div>'
            '<div class="welcome-name">Citara</div>'
            '<h1 class="welcome-title">Pregunta a tus<br>documentos.</h1>'
            '<p class="welcome-subtitle">Citara responde en español basándose '
            "<strong>solo</strong> en tus documentos, y cita la fuente exacta de "
            "cada afirmación. Todo el procesamiento ocurre en tu equipo.</p>"
            '<div class="label welcome-label">Elige un dominio para empezar</div>',
            unsafe_allow_html=True,
        )
        card_css: list[str] = []
        selected_title = ""
        for column, (value, display_name) in zip(st.columns(len(options)), options):
            config = config_for(value)
            accent = accent_for(value)
            # Fail-safe, not fail-silent: an old YAML without domain_name still
            # renders a titled card — the long display_name — never an empty one.
            card_title = config.domain_name or display_name
            card_css.append(
                # Chip letter is config DATA (domain_letter, not value[0] —
                # health's chip is "S", not "H"). The sub-label carries the REAL
                # document count via the light corpus_stats_for façade (cached;
                # no LLM warm-up on the welcome).
                f".st-key-citara-welcome .st-key-citara-domain-{value} button::before"
                f"{{content:'{config.domain_letter}';}}"
                f".st-key-citara-welcome .st-key-citara-domain-{value} button::after"
                f"{{content:'{document_count_label(config, corpus_stats_for(value))}';}}"
                f".st-key-citara-welcome .st-key-citara-domain-{value} button:hover"
                f"{{border-color:{accent['line']};}}"
            )
            if value == selected:
                selected_title = card_title
                # .domain-card.active — accent tint + border on the card, chip
                # flipped to solid accent (the mock's .active .domain-letter).
                # Hover/focus states repeated so the generic gray hover above
                # never washes out the active card.
                card_css.append(
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button,"
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button:hover,"
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button:focus-visible,"
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button:active"
                    f"{{background:{accent['tint']}; border-color:{accent['line']}; color:var(--text);}}"
                    f".st-key-citara-welcome .st-key-citara-domain-{value} button::before"
                    f"{{background:{accent['accent']}; color:{accent['on']}; border:none;}}"
                )
            with column:
                st.button(
                    card_title,
                    key=f"citara-domain-{value}",
                    width="stretch",
                    on_click=select_vertical,
                    args=(value,),
                )
        # The CTA's colors track the SELECTION, not the page accent — main() brands
        # the welcome once with the first Vertical, so var(--accent) would lag.
        cta_accent = accent_for(selected)
        card_css.append(
            ".st-key-citara-welcome .st-key-citara-comenzar button,"
            ".st-key-citara-welcome .st-key-citara-comenzar button:hover,"
            ".st-key-citara-welcome .st-key-citara-comenzar button:focus-visible,"
            ".st-key-citara-welcome .st-key-citara-comenzar button:active"
            f"{{background:{cta_accent['accent']}; color:{cta_accent['on']}; border:none;}}"
        )
        st.markdown(f"<style>{''.join(card_css)}</style>", unsafe_allow_html=True)
        st.button(
            f"Comenzar · {selected_title} →",
            key="citara-comenzar",
            width="stretch",
            on_click=enter_chat,
        )
        st.markdown(
            '<div class="welcome-foot">No se envía nada a internet · '
            "sin telemetría · sin cuentas</div>",
            unsafe_allow_html=True,
        )
