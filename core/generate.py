"""Generator: grounded prompt + local LLM + citations (module 6, FR7–FR9 → AC2, AC3, G4).

Designated *adapter* for the generation side: the ``requests``/Ollama call lives
**only here**, lazily, behind one class, so the rest of ``core/`` stays
framework-free (golden rule 1) and a missing dependency fails loud and actionable
instead of as an ImportError at collection time.

Why a direct HTTP call instead of an SDK: this module talks to Ollama's stable
``POST /api/chat`` endpoint with ``requests`` rather than ``langchain-ollama``'s
``ChatOllama``. The LangChain path is brittle across versions — ``ChatOllama``
reads ``langchain.verbose``, which no longer exists in langchain 1.x, so a
version skew raises ``AttributeError`` deep in the call. Speaking the documented
HTTP API directly removes that volatile dependency and unifies generation with
``embed.py``, which already calls ``/api/embed`` over HTTP for the same reason.

Two non-negotiable invariants this module exists to uphold:

  * **Abstention is a hard guard, not a hope (AC3 / G4).** An empty RetrievedContext
    returns an ``Answer.abstention`` *without ever calling the LLM*. We do not trust
    the model to abstain on its own — the deterministic guard is the net that makes
    "never fabricate when there's nothing to ground on" actually hold, and it's
    testable without Ollama.

  * **Every non-abstaining Answer is grounded and cited (FR8/FR9).** The
    ``system_prompt`` (vertical-specific, from the YAML) carries the grounding /
    citation / Spanish-output rules; this module only assembles it with the context
    and Query. Citations are derived from the *context the model was given*, so a
    grounded Answer can never ship without provenance.

Zero vertical logic here: every legal/health difference lives in the
``system_prompt`` text passed in by ``engine.py`` from ``VerticalConfig``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator

from core.embed import _model_is_available  # shared model-match rule; keep one source
from core.models import (
    Answer,
    AnswerPart,
    Citation,
    CitePart,
    ModelNotPulledError,
    OllamaUnreachableError,
    Query,
    RagEngineError,
    RetrievedContext,
    TextPart,
)

# Same rationale as the Embedder preflight: long enough for a cold local server,
# short enough to fail fast when nothing is listening.
_TAGS_TIMEOUT_SECONDS = 5

# Generation is the slow path (the LLM thinks token-by-token on local hardware),
# so this is far longer than the preflight: wait out a real reply, don't give up.
_CHAT_TIMEOUT_SECONDS = 300

# Low temperature for grounding: generation should hug the provided context, not
# get creative. Exposed as a constructor arg with this default — tunable, not magic.
_DEFAULT_TEMPERATURE = 0.1

# The Abstention text (Spanish — this is end-user UI content, FR8/G5). Centralized
# so the deterministic guard and any future LLM-side abstention read identically.
ABSTENTION_TEXT = "No encuentro esto en los documentos proporcionados."

# Inline citation markers exactly as the SystemPrompt instructs the model to
# emit them: "[N]", N being the 1-based fragment number _format_block puts in
# front of every context block. The YAML prompt and this regex MUST stay in
# sync — both live on the "[N]" notation.
_MARKER_RE = re.compile(r"\[(\d+)\]")

# The exact "[N]" placeholder from the SystemPrompt instructions. The 7B model
# sometimes echoes it verbatim instead of substituting a real number — that is
# template garbage, not prose the user should read, so it is DROPPED whole
# (the same fate as an out-of-range marker) instead of being left inline.
_TEMPLATE_LITERAL = "[N]"

# A "[" followed by up to this many digits — or the "N" of the echoed template
# — could still close into something we must resolve, and is worth withholding
# while streaming. Real fragment numbers are top_k-sized (single digits), so
# anything longer stops being buffered and flushes as plain text — the cap
# exists so a pathological digit run can't buffer unboundedly.
_MARKER_PREFIX_RE = re.compile(r"\[(?:\d{0,6}|N)")


# --- inline citation markers → AnswerParts (FR9 / 3b) --------------------------


def parse_citations(text: str, num_citations: int) -> list[AnswerPart]:
    """Split LLM text with inline ``[N]`` markers into typed AnswerParts.

    ``num_citations`` is the count marker numbers are validated against —
    whatever indexing the caller's text uses. The Generator parses with the
    *fragment* count (the prompt numbers fragments 1..len(context)) and then
    remaps every n to its 1-based position in the deduped ``Answer.citations``
    (see ``_fragment_index_to_citation_index``), because a CitePart's ``n``
    must resolve positionally against the citations list the renderer holds.

    Validation is fail-fast by dropping: the 7B model echoes the context's
    [N]-numbered blocks and may emit malformed or out-of-range markers ([7]
    with 5 fragments, [0], "[12" never closed) — and sometimes the "[N]"
    template placeholder itself, verbatim. A marker with no real fragment
    behind it is an LLM error, not a citation — rendering it would show a chip
    that opens nothing — so we validate every N against the real citation
    count and drop invalid markers (and the echoed placeholder) cleanly rather
    than propagate broken cites. Anything else in brackets ("[a]", an unclosed
    "[12") is NOT marker-shaped and stays as literal text.

    One algorithm with the streaming path: this is :func:`iter_answer_parts`
    over a single fragment, plus merging of adjacent TextParts (a dropped
    marker leaves its two text neighbours split in the incremental view).
    """
    return _merge_adjacent_text(list(iter_answer_parts([text], num_citations)))


def iter_answer_parts(
    fragments: Iterable[str], num_citations: int
) -> Iterator[AnswerPart]:
    """Streaming marker parser: text fragments in, AnswerParts out.

    A ``[N]`` can arrive split across LLM tokens ("[", "2", "]"), so plain text
    is emitted as soon as it provably contains no marker, while a trailing
    prefix that could still become one ("[", "[12") is withheld until it either
    closes (→ CitePart), proves to be plain text, or the stream ends — an
    unclosed "[12" at end of stream flushes as text, exactly what the
    non-streaming regex would have left alone.
    """
    pending = ""
    for fragment in fragments:
        pending += fragment
        emitted, pending = _drain_pending(pending, num_citations, stream_open=True)
        yield from emitted
    emitted, _ = _drain_pending(pending, num_citations, stream_open=False)
    yield from emitted


def _drain_pending(
    pending: str, num_citations: int, *, stream_open: bool
) -> tuple[list[AnswerPart], str]:
    """Consume ``pending`` into parts; return what must stay buffered.

    Only a suffix that could still become a marker survives in the buffer, and
    only while the stream is open — everything else is resolved now.
    """
    parts: list[AnswerPart] = []
    while pending:
        bracket = pending.find("[")
        if bracket == -1:
            parts.append(TextPart(text=pending))
            pending = ""
            break
        if bracket > 0:
            parts.append(TextPart(text=pending[:bracket]))
            pending = pending[bracket:]

        match = _MARKER_RE.match(pending)
        if match:
            n = int(match.group(1))
            # Out-of-range N = LLM error, not a citation (see parse_citations):
            # the marker is dropped whole. In range, it resolves 1-based.
            if 1 <= n <= num_citations:
                parts.append(CitePart(n=n))
            pending = pending[match.end() :]
            continue

        if pending.startswith(_TEMPLATE_LITERAL):
            # Echoed prompt placeholder, dropped whole (see _TEMPLATE_LITERAL).
            pending = pending[len(_TEMPLATE_LITERAL) :]
            continue

        if stream_open and _MARKER_PREFIX_RE.fullmatch(pending):
            # Could still close into a marker (or the "[N]" template) — hold it
            # back for the next fragment.
            break

        # Provably not a marker (or the stream is over): the "[" was plain
        # text. Emit it and keep scanning what follows for later markers.
        parts.append(TextPart(text="["))
        pending = pending[1:]
    return parts, pending


def _merge_adjacent_text(parts: list[AnswerPart]) -> list[AnswerPart]:
    """Collapse consecutive TextParts (dropped markers leave split neighbours)."""
    merged: list[AnswerPart] = []
    for part in parts:
        if merged and isinstance(part, TextPart) and isinstance(merged[-1], TextPart):
            merged[-1] = TextPart(text=merged[-1].text + part.text)
        else:
            merged.append(part)
    return merged


def _remap_cite_indexes(
    parts: Iterable[AnswerPart], fragment_to_citation: list[int]
) -> Iterator[AnswerPart]:
    """Rewrite each CitePart's fragment number as its citation-list index.

    ``fragment_to_citation[i]`` is the 1-based citations index for fragment
    ``i+1`` (see ``Generator._fragment_index_to_citation_index``). The parser
    already guaranteed 1 <= n <= len(fragment_to_citation), so the lookup can't
    miss. Lazy on purpose: streaming callers remap part-by-part as they emit.
    """
    for part in parts:
        if isinstance(part, CitePart):
            yield CitePart(n=fragment_to_citation[part.n - 1])
        else:
            yield part


class Generator:
    """Builds a grounded prompt from RetrievedContext + Query, calls the local LLM,
    returns a cited Answer (FR7–FR9).

    ``llm_model`` and ``ollama_base_url`` come from ``VerticalConfig`` and are the
    single source of truth for which model/endpoint to use (golden rule 4 — never
    hardcoded, never read from config here). ``system_prompt`` is the vertical's
    instruction block, also from config. The adapter calls Ollama's HTTP endpoint
    directly with ``requests``; tests mock ``requests.post`` so nothing touches
    the network.
    """

    def __init__(
        self,
        llm_model: str,
        ollama_base_url: str,
        system_prompt: str,
        *,
        temperature: float = _DEFAULT_TEMPERATURE,
    ) -> None:
        self.llm_model = llm_model
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.system_prompt = system_prompt
        self.temperature = temperature

    # --- the use case --------------------------------------------------------

    def generate(self, query: Query, context: RetrievedContext) -> Answer:
        """Produce a grounded, cited Answer — or abstain when there's nothing to ground on."""
        # HARD ABSTENTION GUARD (AC3 / G4): no context ⇒ no LLM call, deterministic
        # abstention. Return early before any model interaction so an empty corpus
        # or a zero-hit retrieval can never yield an invented answer.
        if not context:
            return Answer.abstention(ABSTENTION_TEXT)

        prompt = self._build_prompt(query, context)
        text = self._invoke_llm(prompt)

        # Citations are derived from the context the model was actually given — the
        # honest set of sources consulted. The Answer invariant then forbids a
        # non-abstaining Answer with no citations, so grounding can't silently slip.
        citations = self._citations_from_context(context)
        # parts: the same text split for inline chips. ``text`` stays the raw
        # reply (markers included) so plain consumers lose nothing. Markers are
        # parsed against the FRAGMENT count and then remapped to citation
        # indexes — validating against len(citations) directly would misindex
        # (or wrongly drop) markers whenever two chunks shared (doc, page).
        fragment_to_citation = self._fragment_index_to_citation_index(
            context, citations
        )
        parts = list(
            _remap_cite_indexes(
                parse_citations(text, num_citations=len(context)),
                fragment_to_citation,
            )
        )
        return Answer(text=text, citations=citations, parts=parts)

    def generate_stream(self, query: Query, context: RetrievedContext) -> Iterator[str]:
        """Stream the grounded reply as text fragments, yielded as the LLM emits them.

        Why this exists: on local hardware (e.g. an RTX 1080) a full reply can take
        1–2 minutes to generate. Streaming does **not** make generation faster — it
        replaces a long, silent spinner with visible progress so the UI never *looks*
        hung. Only the *text* streams; the ``Citation``s do not change token-by-token,
        so callers derive them once from ``context`` (see :meth:`citations_for_context`).

        The non-streaming :meth:`generate` is kept intact as the tested fallback and
        for callers that want a whole ``Answer`` object in one call.
        """
        # HARD ABSTENTION GUARD (AC3 / G4): the exact same invariant as generate() —
        # an empty context yields the deterministic abstention sentence *whole* and
        # never calls the LLM. Yield-then-return so the caller's stream sink shows the
        # identical text the non-streaming path would return.
        if not context:
            yield ABSTENTION_TEXT
            return

        prompt = self._build_prompt(query, context)
        # Fail-fast is preserved: _invoke_llm_stream opens the connection before its
        # first yield, so an unreachable Ollama raises OllamaUnreachableError on the
        # first iteration — before any generated text reaches the caller.
        yield from self._invoke_llm_stream(prompt)

    def generate_stream_parts(
        self, query: Query, context: RetrievedContext
    ) -> Iterator[AnswerPart]:
        """Streaming twin of :meth:`generate` at AnswerPart granularity (3b).

        Wraps :meth:`generate_stream` — whose plain ``Iterator[str]`` contract
        stays untouched for text-only consumers — with the incremental marker
        parser: TextParts flow through as the LLM emits them; a CitePart is
        emitted the moment its complete ``[N]`` closes. The abstention path
        needs no special-casing: an empty context streams the abstention
        sentence (no markers) as plain text, and the zero fragment count makes
        any stray marker unresolvable anyway.
        """
        citations = self._citations_from_context(context)
        fragment_to_citation = self._fragment_index_to_citation_index(
            context, citations
        )
        yield from _remap_cite_indexes(
            iter_answer_parts(self.generate_stream(query, context), len(context)),
            fragment_to_citation,
        )

    def citations_for_context(self, context: RetrievedContext) -> list[Citation]:
        """Public seam to derive the Citations behind a context (FR9 / AC2).

        Streaming splits an Answer in two: the *text* streams from the LLM while the
        *Citations* are fixed the instant retrieval returns. The streaming caller
        renders the text with :meth:`generate_stream` and attaches sources via this
        method, so the SourcesPanel shows exactly the provenance the non-streaming
        path derives — same logic, one source of truth.
        """
        return self._citations_from_context(context)

    # --- grounded prompt assembly (FR7) --------------------------------------

    def _build_prompt(self, query: Query, context: RetrievedContext) -> str:
        """Assemble the user-side message: formatted citable context + the Query.

        The system_prompt (with the grounding/citation/Spanish rules) is sent
        separately as the system message; here we only build the human turn.
        """
        blocks = "\n\n".join(self._format_block(i, chunk) for i, chunk in enumerate(context, 1))
        # Spanish framing because the model answers in Spanish (G5); the binding
        # rules themselves live in the vertical's system_prompt, not here.
        return (
            "Contexto recuperado de los documentos:\n\n"
            f"{blocks}\n\n"
            f"Pregunta: {query.text}"
        )

    @staticmethod
    def _format_block(index: int, chunk) -> str:
        """One citable context block: provenance header + text.

        Uses the document_id and page guaranteed on every ChunkMetadata so the
        model can attribute claims to a real SourceDocument and page.
        """
        md = chunk.metadata
        return f"[{index}] [Documento: {md.document_id}, pág. {md.page}]\n{chunk.text}"

    # --- citations (FR9 / AC2) ----------------------------------------------

    @staticmethod
    def _citations_from_context(context: RetrievedContext) -> list[Citation]:
        """Derive Citations from the consulted Chunks, deduped by (document_id, page).

        MVP choice: list the *sources consulted* (every Chunk in context), not
        sentence-by-sentence attribution. The LLM synthesizes across several chunks,
        so a clean list of the sources behind the Answer is both honest and
        sufficient — and it keeps the provenance the Retriever actually returned.
        Dedup so two chunks from the same document+page collapse to one Citation,
        preserving first-seen order (which mirrors relevance order) — the FIRST
        chunk seen also contributes ``chunk_text`` (the most relevant passage),
        which exists for the source viewer only and never enters the prompt.
        """
        citations: list[Citation] = []
        seen: set[tuple[str, int]] = set()
        for chunk in context:
            key = (chunk.metadata.document_id, chunk.metadata.page)
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation.from_chunk(chunk))
        return citations

    @staticmethod
    def _fragment_index_to_citation_index(
        context: RetrievedContext, citations: list[Citation]
    ) -> list[int]:
        """Remap table: prompt fragment ``[i+1]`` → 1-based index in ``citations``.

        The prompt numbers fragments 1..len(context), one per chunk
        (``_format_block``), but ``citations`` is deduped by (document_id, page)
        — two different indexings, so a fragment number used directly against
        the citations list would misindex whenever two chunks share a page.
        Each fragment resolves through its (doc, page) key to the POSITION of
        its deduped Citation, which is exactly the ``n`` a CitePart must carry:
        the renderer looks up ``Answer.citations[n - 1]``.
        """
        position = {
            (c.document_id, c.page): index for index, c in enumerate(citations, 1)
        }
        return [
            position[(chunk.metadata.document_id, chunk.metadata.page)]
            for chunk in context
        ]

    # --- LLM call (FR7) + preflight (AC7) ------------------------------------

    def check_health(self) -> None:
        """Verify Ollama is reachable and the LLM model is pulled (fail-fast, AC7).

        Mirror of the Embedder preflight, kept as a distinct check so the two
        failure modes — server down vs. model not pulled — surface as different,
        actionable exceptions. Call once at engine startup before generating.
        """
        pulled = self._list_pulled_models()  # raises OllamaUnreachableError if down
        if not _model_is_available(self.llm_model, pulled):
            raise ModelNotPulledError(
                f"LLM model '{self.llm_model}' is not available in Ollama. "
                f"Pull it first: `ollama pull {self.llm_model}`."
            )

    def warm_up(self) -> None:
        """Force Ollama to load the LLM into VRAM before the first real Query.

        Why: the first generation of a session otherwise pays the model-load cost
        (``qwen2.5:7b`` ≈ 4.7 GB into VRAM), which reads as a hang. We send the
        smallest possible ``/api/chat`` request — a trivial message capped at a
        single predicted token (``num_predict = 1``) — purely to trigger the load;
        the reply is discarded, so no real answer is generated. ``keep_alive`` asks
        Ollama to hold the model resident afterwards, so the first user question
        finds it hot.

        This is an *optimization*, not the query path: fail-fast is still honoured
        here (a down server or missing model raises the usual actionable error), but
        the caller is expected to treat that failure as non-fatal — the same error
        surfaces loudly through :meth:`check_health` at startup, so swallowing it at
        the call site skips only the warm-up, it never hides the cause (golden rule 5).
        """
        requests = self._http()
        url = f"{self.ollama_base_url}/api/chat"
        body = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": "."}],
            "stream": False,
            # num_predict=1: emit at most one token — we want the model resident in
            # VRAM, not an actual answer.
            "options": {"num_predict": 1},
            # Hold the model loaded so the first real Query lands on a warm model.
            "keep_alive": "10m",
        }
        try:
            response = requests.post(url, json=body, timeout=_CHAT_TIMEOUT_SECONDS)
        except (requests.exceptions.RequestException, OSError) as exc:
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}' while warming up. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            lowered = detail.lower()
            if "not found" in lowered or "pull" in lowered:
                raise ModelNotPulledError(
                    f"LLM model '{self.llm_model}' is not available in Ollama "
                    f"(warm-up /api/chat → HTTP {response.status_code}: {detail}). "
                    f"Pull it first: `ollama pull {self.llm_model}`."
                )
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code}: {detail} during warm-up."
            )

    def _list_pulled_models(self) -> set[str]:
        requests = self._http()
        url = f"{self.ollama_base_url}/api/tags"
        try:
            response = requests.get(url, timeout=_TAGS_TIMEOUT_SECONDS)
        except (requests.exceptions.RequestException, OSError) as exc:
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}'. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            raise OllamaUnreachableError(
                f"Ollama at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code} for /api/tags. Verify the server and URL."
            )

        try:
            models = response.json().get("models", [])
            return {entry["name"] for entry in models}
        except (ValueError, KeyError, TypeError) as exc:
            raise OllamaUnreachableError(
                f"Unexpected /api/tags response from Ollama at "
                f"'{self.ollama_base_url}'. Verify it is really Ollama."
            ) from exc

    def _invoke_llm(self, user_prompt: str) -> str:
        """POST (system_prompt, user_prompt) to /api/chat and return the reply text.

        Direct HTTP to Ollama's stable ``/api/chat``, no SDK — same rationale as
        ``embed.py`` (see the module docstring): the ``ChatOllama`` path is
        brittle across LangChain versions, so we speak the documented HTTP API.
        """
        requests = self._http()
        url = f"{self.ollama_base_url}/api/chat"
        body = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Non-streamed: we want the whole reply in one JSON response, not a
            # token stream to reassemble.
            "stream": False,
            # Low temperature keeps generation hugging the grounding context.
            "options": {"temperature": self.temperature},
        }
        try:
            response = requests.post(url, json=body, timeout=_CHAT_TIMEOUT_SECONDS)
        except (requests.exceptions.RequestException, OSError) as exc:
            # Connection refused / DNS / timeout — the server isn't answering.
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}' while generating. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            lowered = detail.lower()
            # Ollama answers an unknown model with a "not found, try pulling it"
            # error; surface that as the actionable model error, not a generic one.
            if "not found" in lowered or "pull" in lowered:
                raise ModelNotPulledError(
                    f"LLM model '{self.llm_model}' is not available in Ollama "
                    f"(/api/chat → HTTP {response.status_code}: {detail}). "
                    f"Pull it first: `ollama pull {self.llm_model}`."
                )
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code}: {detail}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned a "
                "non-JSON response. Verify it is really Ollama."
            ) from exc

        # Ollama's non-streamed reply nests the text at message.content.
        message = payload.get("message") if isinstance(payload, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned no "
                "message content. Verify the server version and model."
            )
        return content

    def _invoke_llm_stream(self, user_prompt: str) -> Iterator[str]:
        """POST to /api/chat with ``stream=True`` and yield each content fragment.

        Ollama streams NDJSON: one JSON object per line, each carrying an incremental
        ``message.content``, until a final line with ``done: true``. We consume it with
        ``requests``' ``stream=True`` + ``iter_lines()``, parse each line, and yield the
        text pieces as they arrive. Same endpoint and same fail-fast error mapping as
        the non-streamed path — only ``stream`` and the response handling differ.
        """
        requests = self._http()
        url = f"{self.ollama_base_url}/api/chat"
        body = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Streamed: ask Ollama to emit incremental NDJSON fragments so the UI can
            # render tokens as they are produced instead of waiting for the whole reply.
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        try:
            response = requests.post(
                url, json=body, timeout=_CHAT_TIMEOUT_SECONDS, stream=True
            )
        except (requests.exceptions.RequestException, OSError) as exc:
            # Raised before any fragment is yielded — fail-fast, loud, actionable.
            raise OllamaUnreachableError(
                f"Cannot reach Ollama at '{self.ollama_base_url}' while generating. "
                "Start it with `ollama serve` and verify the base URL."
            ) from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            lowered = detail.lower()
            # Same actionable model error as the non-streamed path.
            if "not found" in lowered or "pull" in lowered:
                raise ModelNotPulledError(
                    f"LLM model '{self.llm_model}' is not available in Ollama "
                    f"(/api/chat → HTTP {response.status_code}: {detail}). "
                    f"Pull it first: `ollama pull {self.llm_model}`."
                )
            raise RagEngineError(
                f"Ollama /api/chat at '{self.ollama_base_url}' returned HTTP "
                f"{response.status_code}: {detail}."
            )

        for line in response.iter_lines():
            if not line:
                continue  # Ollama may emit keep-alive blank lines; skip them.
            try:
                payload = json.loads(line)
            except ValueError:
                # A malformed line shouldn't abort a reply that's otherwise arriving;
                # skip it rather than crash mid-stream.
                continue
            message = payload.get("message") if isinstance(payload, dict) else None
            fragment = message.get("content") if isinstance(message, dict) else None
            if fragment:
                yield fragment
            if isinstance(payload, dict) and payload.get("done"):
                break

    @staticmethod
    def _error_detail(response) -> str:
        """Best-effort human-readable reason from a non-200 Ollama response."""
        try:
            body = response.json()
        except ValueError:
            return (getattr(response, "text", "") or "").strip() or "<no body>"
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])
        return str(body)

    @staticmethod
    def _http():
        try:
            import requests
        except ImportError as exc:
            raise RagEngineError(
                "requests is required to reach Ollama. "
                "Install it with `pip install -r requirements.txt`."
            ) from exc
        return requests
