"""Streamlit App + SourcesPanel: the Presentation layer (module 8, FR11 → AC2, AC8).

Pure presentation. This file imports the ``RagEngine`` use case and the domain
*types* it renders (``Answer``, ``Citation``); it builds no prompts, touches no
Chroma, and contains **zero domain logic** (golden rule 1). It also contains **zero
vertical branching** (golden rule 2): the legal/health difference is entirely in the
``VerticalConfig`` the sidebar selects — the UI code below is identical for both.

Import safety: every adapter builds its Ollama/Chroma client lazily, so importing
and running this script never needs a live Ollama. When dependencies are down,
``check_health`` raises a domain error that we translate into a friendly
``st.error`` — the app shows an actionable message instead of crashing at import or
on the first query (NFR6/AC7).
"""

from __future__ import annotations

from collections.abc import Iterator

import streamlit as st

from core.engine import RagEngine

# Reading the VerticalConfig for UI branding (display_name) is a presentation
# concern, not domain logic. We reuse ingest.py's minimal loader so config is read
# in one place; TODO(module 9): a dedicated config module will own this.
from core.generate import _ABSTENTION_TEXT
from core.ingest import _load_vertical_config
from core.models import (
    Answer,
    EmptyCorpusError,
    ModelNotPulledError,
    OllamaUnreachableError,
    RagEngineError,
    Vertical,
    VerticalConfig,
)

_SPINNER_TEXT = "Generando la respuesta…"
# Safety net for a still-cold model (warm-up failed or hasn't finished): an honest,
# one-off message so the first, slower answer doesn't read as a hang.
_FIRST_SPINNER_TEXT = "Preparando el modelo; la primera respuesta puede tardar unos segundos…"
_ABSTENTION_NOTE = (
    "Sin fuentes: la respuesta no se encontró en los documentos (abstención). "
    "Esto es el comportamiento esperado, no un error."
)


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
            config = _load_vertical_config(vertical)
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
    engine = RagEngine.from_vertical_config(_load_vertical_config(Vertical(vertical_value)))
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


# --- error translation (NFR6/AC7) --------------------------------------------


def _check_dependencies(engine: RagEngine) -> bool:
    """Run the aggregated preflight, surfacing domain errors as actionable UI.

    Returns True when all prerequisites are met. On failure we render the exact,
    actionable message (start Ollama / pull the model / ingest the corpus) rather
    than a raw traceback, and return False so the caller can block querying.
    """
    try:
        engine.check_health()
        return True
    except OllamaUnreachableError as exc:
        st.error(f"🔌 Ollama no está disponible.\n\n{exc}")
    except ModelNotPulledError as exc:
        st.error(f"📦 Falta un modelo en Ollama.\n\n{exc}")
    except EmptyCorpusError as exc:
        st.error(f"📂 El corpus está vacío.\n\n{exc}")
    except RagEngineError as exc:
        # Any other domain error: still actionable by construction, never a traceback.
        st.error(str(exc))
    return False


# --- SourcesPanel (FR9/AC2) --------------------------------------------------


def _render_sources_panel(answer: Answer) -> None:
    """Render the Citations behind one Answer: document_id + page (+ section).

    Abstention is shown explicitly as an expected state (no sources), never styled
    as an error — abstaining is the correct behaviour when context is insufficient.
    """
    if answer.is_abstention:
        st.caption(f"ℹ️ {_ABSTENTION_NOTE}")
        return

    with st.expander(f"📚 Fuentes ({len(answer.citations)})"):
        for citation in answer.citations:
            line = f"**{citation.document_id}** — pág. {citation.page}"
            if citation.section:
                line += f" · {citation.section}"
            st.markdown(line)


# --- chat history (per Vertical) ---------------------------------------------


def _history_for(vertical_value: str) -> list[dict]:
    """The chat history for a Vertical, isolated from the others.

    Keyed by Vertical so switching legal↔health does not mix two distinct
    conversations (and their sources) into one thread.
    """
    histories = st.session_state.setdefault("histories", {})
    return histories.setdefault(vertical_value, [])


def _render_history(history: list[dict]) -> None:
    for message in history:
        with st.chat_message(message["role"]):
            st.markdown(message["text"])
            # Assistant turns carry their Answer so the SourcesPanel survives reruns.
            if message["role"] == "assistant" and message.get("answer") is not None:
                _render_sources_panel(message["answer"])


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
    st.set_page_config(page_title="rag-engine", page_icon="📄", layout="centered")

    options = _vertical_options()
    if not options:
        st.error(
            "No hay ninguna Vertical configurada. Añade config/<vertical>.yaml "
            "(p. ej. config/health.yaml) antes de arrancar la app."
        )
        st.stop()

    values = [value for value, _ in options]
    labels = {value: label for value, label in options}

    # Sidebar Vertical selector — the ONLY thing that differs between demos. The UI
    # code that follows is identical regardless of which Vertical is chosen.
    with st.sidebar:
        st.header("Vertical")
        vertical_value = st.selectbox(
            "Selecciona el dominio",
            values,
            format_func=lambda v: labels.get(v, v),
        )

    config: VerticalConfig = _load_vertical_config(Vertical(vertical_value))
    st.title(config.display_name)  # branding from VerticalConfig
    st.caption("Pregunta en español; las respuestas se basan solo en los documentos.")

    try:
        engine = _load_engine(vertical_value)
    except RagEngineError as exc:
        # A failure to even build the engine (e.g. a missing dependency) — actionable.
        st.error(str(exc))
        st.stop()

    dependencies_ok = _check_dependencies(engine)

    history = _history_for(vertical_value)
    _render_history(history)

    prompt = st.chat_input("Escribe tu pregunta…")
    if not prompt:
        return

    if not dependencies_ok:
        # Dependencies are down; the error is already on screen. Don't attempt a
        # query that would only fail deeper in.
        st.warning("Resuelve el problema indicado arriba antes de preguntar.")
        return

    # Show the user's question immediately, before any generation, so the slow LLM
    # (1–2 min on local hardware) never makes the app look hung waiting on a spinner.
    history.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # First question of the session? If warm-up didn't fully hide the cold start,
    # show an honest heads-up. Simple per-session flag — no elaborate detection.
    first_query = not st.session_state.get("has_generated", False)
    spinner_text = _FIRST_SPINNER_TEXT if first_query else _SPINNER_TEXT

    with st.chat_message("assistant"):
        try:
            # Consume the engine's PUBLIC streaming seam — the UI knows nothing about
            # the Retriever/Generator inside. answer_stream() runs retrieval eagerly
            # and returns the still-lazy text generator plus the citations derived from
            # the retrieved context. The spinner covers retrieval AND the wait for the
            # first token (where a cold model would load), then write_stream renders
            # the tokens as they arrive.
            with st.spinner(spinner_text):
                streamed = engine.answer_stream(prompt)
                primed = _spinner_until_first_token(streamed.text_stream)
            full_text = st.write_stream(primed)
            st.session_state["has_generated"] = True
        except RagEngineError as exc:
            # Retrieval/generation failures (empty Collection, Ollama dropped, model
            # not pulled) all carry actionable messages — Ollama-down raises on the
            # first streamed fragment, before any text is shown. Surface them, keep
            # the app alive.
            st.error(str(exc))
            history.append({"role": "assistant", "text": str(exc), "answer": None})
            return

        # Rebuild the Answer for the SourcesPanel + history. No citations ⇔ empty
        # context ⇔ the stream carried the abstention text; otherwise the streamed
        # text is grounded on the citations the engine derived.
        if not streamed.citations:
            answer = Answer.abstention(full_text or _ABSTENTION_TEXT)
        else:
            answer = Answer(text=full_text, citations=streamed.citations)
        _render_sources_panel(answer)

    history.append({"role": "assistant", "text": answer.text, "answer": answer})


main()
