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

import re
from collections.abc import Iterator
from html import escape

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.engine import RagEngine

# Reading the VerticalConfig for UI branding (display_name) is a presentation
# concern, not domain logic. We reuse ingest.py's minimal loader so config is read
# in one place; TODO(module 9): a dedicated config module will own this.
from core.generate import _ABSTENTION_TEXT
from core.ingest import load_vertical_config
from core.models import (
    Answer,
    Citation,
    CorpusStats,
    EmptyCorpusError,
    ModelNotPulledError,
    OllamaUnreachableError,
    RagEngineError,
    Vertical,
    VerticalConfig,
)
from ui.state import (
    KEY_ENTERED,
    KEY_HAS_GENERATED,
    KEY_PENDING_QUERY,
    KEY_VERTICAL,
    KEY_VERTICAL_WIDGET,
    config_for,
    enter_chat,
    history_for,
    queue_query,
    select_vertical,
    sync_vertical,
)
from ui.theme import LOGO_PATH, accent_for, inject_theme, render_splash

_SPINNER_TEXT = "Generando la respuesta…"
# Safety net for a still-cold model (warm-up failed or hasn't finished): an honest,
# one-off message so the first, slower answer doesn't read as a hang.
_FIRST_SPINNER_TEXT = "Preparando el modelo; la primera respuesta puede tardar unos segundos…"


# --- cached construction -----------------------------------------------------


@st.cache_data(show_spinner=False)
def _vertical_options() -> list[tuple[str, str]]:
    """The selectable Verticals as (value, display_name), skipping any unconfigured.

    Cached as data because it is just a cheap read of small YAML files; building the
    option list once per session is enough.
    """
    options: list[tuple[str, str]] = []
    for vertical in Vertical:
        try:
            config = load_vertical_config(vertical)
        except RagEngineError:
            continue  # a Vertical with no/invalid YAML simply isn't offered
        options.append((vertical.value, config.display_name))
    return options


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


@st.cache_data(show_spinner=False)
def _corpus_stats_for(vertical_value: str) -> CorpusStats:
    """Cached Corpus snapshot per Vertical — the ONE route welcome AND sidebar use.

    Goes through the LIGHT engine façade (VectorStore only): the welcome needs
    counts for BOTH Verticals, and building full engines there would trigger the
    LLM warm-up (~6s each) before the user even picked one. cache_data, not
    resource: a small immutable value object; the Corpus only changes via the
    offline ingest CLI, so reruns can reuse it (the same staleness trade-off
    _load_engine already accepts).
    """
    return RagEngine.corpus_stats_for(config_for(vertical_value))


def _document_count_label(config: VerticalConfig, stats: CorpusStats) -> str:
    """"{domain_sublabel} · {n} documento(s)" — the ONE format welcome and sidebar share.

    The count is the REAL one from CorpusStats (the mock's "14 documentos" was a
    placeholder); an empty sublabel degrades to the bare count (fail-safe).
    """
    noun = "documento" if stats.document_count == 1 else "documentos"
    count = f"{stats.document_count} {noun}"
    return f"{config.domain_sublabel} · {count}" if config.domain_sublabel else count


# --- error translation (NFR6/AC7) --------------------------------------------

# All user-visible error copy is born HERE, in Spanish: core/ raises technical
# English messages (those are code, kept as the .err-tech trace), and this layer
# maps the TYPED exception to the mock's actionable card. Commands and model
# names come from the VerticalConfig — never from mock literals (the mock says
# "llama3.1 · 4,7 GB"; the real model is whatever llm_model says, and the weight
# is omitted because there is no reliable source for it).

# core quotes the offending model name single-quoted in its messages.
_QUOTED = re.compile(r"'([^']+)'")


def _error_presentation(exc: RagEngineError, config: VerticalConfig) -> dict[str, str | None]:
    """Map a domain error to the card fields (Spanish copy + real command)."""
    host = escape(config.ollama_base_url.removeprefix("http://").removeprefix("https://"))
    if isinstance(exc, OllamaUnreachableError):
        return {
            "kind": "servicio",
            "title": "Ollama no está disponible",
            "body": (
                "No se pudo conectar con el modelo local en "
                f'<span class="mono err-code">{host}</span>. '
                "Arráncalo en una terminal y reintenta."
            ),
            "command": "ollama serve",
            "technical": str(exc),
            "llm_model": config.llm_model,
            "host": config.ollama_base_url,
        }
    if isinstance(exc, ModelNotPulledError):
        # The missing model can be the LLM or the Embedder's (both preflights
        # raise this type); core carries it single-quoted in the message. The
        # llm_model fallback keeps the command real either way.
        match = _QUOTED.search(str(exc))
        model = match.group(1) if match else config.llm_model
        return {
            "kind": "modelo",
            "title": "El modelo no está descargado",
            "body": (
                f'El modelo <span class="mono err-code">{escape(model)}</span> '
                "no está en Ollama. Descárgalo una sola vez para empezar."
            ),
            "command": f"ollama pull {model}",
            "technical": str(exc),
            "llm_model": config.llm_model,
            "host": config.ollama_base_url,
        }
    if isinstance(exc, EmptyCorpusError):
        return {
            "kind": "corpus",
            "title": "El corpus está vacío",
            "body": (
                "No hay documentos ingestados para esta Vertical. Coloca los PDF en "
                f'<span class="mono err-code">{escape(config.corpus_path)}</span> '
                "y lanza la ingesta desde una terminal."
            ),
            "command": f"python -m core.ingest --vertical {config.vertical.value}",
            "technical": str(exc),
        }
    return {
        "kind": "motor",
        "title": "No se pudo completar la operación",
        "body": (
            "La operación falló de forma inesperada. El detalle técnico de "
            "abajo indica la causa."
        ),
        "technical": str(exc),
    }


@st.dialog("Poner Ollama en marcha")
def _show_install_guide(llm_model: str, host: str) -> None:
    """Spanish step-by-step to install/start Ollama and pull the model.

    Real commands only, model/host from VerticalConfig — the same honesty rule
    as the card itself.
    """
    st.markdown(
        "**1 · Instala Ollama** (una sola vez) desde "
        "[ollama.com/download](https://ollama.com/download)."
    )
    st.markdown(f"**2 · Arranca el servidor** en una terminal; debe quedar escuchando en `{host}`:")
    st.code("ollama serve", language="bash")
    st.markdown("**3 · Descarga el modelo** (una sola vez):")
    st.code(f"ollama pull {llm_model}", language="bash")
    st.markdown("**4 · Vuelve aquí** y pulsa «Reintentar conexión».")


def _render_error_card(
    kind: str,
    title: str,
    body: str,
    command: str | None = None,
    technical: str | None = None,
    llm_model: str | None = None,
    host: str | None = None,
    key_suffix: str = "live",
) -> None:
    """Render an actionable error as the mock's state-card (05-errors.html).

    HTML paints the static part (``body`` is presentation-crafted HTML; dynamic
    values are escaped in _error_presentation). The command is st.code so the
    copy button is REAL (native), and the buttons are real widgets: retry reruns
    the script — the health preflight re-executes on every run — and the guide
    opens a dialog. ``key_suffix`` keeps widget keys unique: the history replay
    plus a live card can put several of these on one page.
    """
    tech_html = f'<div class="err-tech">{escape(technical)}</div>' if technical else ""
    with st.container(key=f"citara-error-{key_suffix}"):
        st.markdown(
            f'<div class="label err-label">Error accionable · {escape(kind)}</div>'
            '<div class="err-row"><div class="err-icon">!</div>'
            f'<div class="err-main"><div class="err-title">{escape(title)}</div>'
            f'<div class="err-body">{body}</div>{tech_html}</div></div>',
            unsafe_allow_html=True,
        )
        if command:
            st.code(command, language="bash")
        # Buttons only where they are functional (the Ollama cards). Download
        # arrives in #05b; "choose another model" is icebox — neither is faked.
        if kind in ("servicio", "modelo") and llm_model and host:
            with st.container(horizontal=True):
                if st.button("Reintentar conexión", key=f"citara-retry-{key_suffix}"):
                    st.rerun()
                if st.button("Ver guía de instalación", key=f"citara-guide-{key_suffix}"):
                    _show_install_guide(llm_model, host)


def _render_corpus_panel(engine: RagEngine, config: VerticalConfig) -> None:
    """Read-only Corpus section (mock 06, loaded state) with REAL stats.

    Presentation calls the engine façade only — never ChromaDB (golden rule 1).
    The mock's "Actualizar corpus" button renders as a command chip because
    re-ingestion from the UI is SPEC §8 future work: the honest control is the
    real CLI command, copyable via st.code's native button. No last-ingested
    stat (no reliable source) and the embedding model comes from config.
    """
    with st.expander("Corpus"):
        try:
            stats = engine.corpus_stats()
        except RagEngineError as exc:
            _render_error_card(**_error_presentation(exc, config), key_suffix="corpus")
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
        _render_error_card(**_error_presentation(exc, config), key_suffix="preflight")
        return exc


def _render_ollama_badge(
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


# --- SourcesPanel (FR9/AC2) --------------------------------------------------


def _render_abstention_label() -> None:
    """The dashed «Sin coincidencias» pill shown above an abstention answer."""
    st.markdown(
        '<span class="abstain-label">Sin coincidencias en los documentos</span>',
        unsafe_allow_html=True,
    )


def _is_abstention_text(text: str) -> bool:
    """Detect an abstention answered in prose.

    The deterministic empty-context guard yields ``_ABSTENTION_TEXT`` whole, but
    the LLM can also open with that same sentence when the retrieved chunks don't
    actually answer the question. Both cases must get the calm abstention
    treatment — and an answer that says "I can't find this" must not dangle a
    contradictory sources list underneath.
    """
    return text.strip().startswith(_ABSTENTION_TEXT)


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


def _render_sources_panel(answer: Answer, key_suffix: str = "live") -> None:
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


# --- chat history (per Vertical) ---------------------------------------------


def _render_history(history: list[dict]) -> None:
    for index, message in enumerate(history):
        with st.chat_message(message["role"]):
            # Failed turns re-render as the same actionable card, not raw text.
            # Index-suffixed keys: several failed turns = several cards, and
            # their retry/guide buttons must not collide.
            if message.get("error") is not None:
                _render_error_card(**message["error"], key_suffix=f"history-{index}")
                continue
            answer = message.get("answer")
            # Design order: the abstention pill sits ABOVE the answer body.
            if message["role"] == "assistant" and answer is not None and answer.is_abstention:
                _render_abstention_label()
            st.markdown(message["text"])
            # Assistant turns carry their Answer so the SourcesPanel survives reruns.
            if message["role"] == "assistant" and answer is not None:
                _render_sources_panel(answer, key_suffix=f"history-{index}")


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


def _render_welcome(options: list[tuple[str, str]]) -> None:
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
                f"{{content:'{_document_count_label(config, _corpus_stats_for(value))}';}}"
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


def _render_loading_card(label_text: str) -> None:
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


def _spinner_until_first_token(text_stream: Iterator[str]) -> Iterator[str]:
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
        _render_error_card(
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
        _render_welcome(options)
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
    _render_ollama_badge(badge_slot, config, None, connecting=True)
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
        _render_ollama_badge(badge_slot, config, exc)
        _render_error_card(**_error_presentation(exc, config), key_suffix="engine")
        st.stop()

    preflight_error = _check_dependencies(engine, config)
    dependencies_ok = preflight_error is None
    _render_ollama_badge(badge_slot, config, preflight_error)

    # Read-only Corpus section under the header — real counts through the
    # engine façade; presentation never touches ChromaDB (golden rule 1).
    _render_corpus_panel(engine, config)

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
        spinner_text = _FIRST_SPINNER_TEXT if first_query else _SPINNER_TEXT

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
                            _render_loading_card(spinner_text)
                    # The first next() inside blocks through the first-token wait
                    # (cold model load included); the card lives exactly that long.
                    primed = _spinner_until_first_token(streamed.text_stream)
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
                _render_error_card(**presentation, key_suffix=f"history-{len(history)}")
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
                    _render_abstention_label()
            else:
                answer = Answer(text=full_text, citations=streamed.citations)
            # The suffix must be STABLE across the live→history transition: a
            # button click reruns the script, where this same panel re-renders
            # from history — with a different key the clicked widget would not
            # exist in the new run and the click would be silently dropped.
            # This assistant turn is appended right below, so its history index
            # IS len(history) at this moment (the user turn is already in).
            _render_sources_panel(answer, key_suffix=f"history-{len(history)}")

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
