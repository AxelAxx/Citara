# API_CONTRACT.md — rag-engine HTTP frontier (FastAPI)

> The contract between the new `api/` package (Presentation) and the React front.
> `api/` is a thin adapter over the existing `RagEngine` façade. It imports `core/`
> **only** through the public seam (`RagEngine`, `core.models`, `load_vertical_config`)
> — same golden rule the Streamlit `ui/` respected. `core/` never learns the web exists.

## Design principles

- **Thin routes.** Each handler validates input, calls `RagEngine`, shapes output. Zero
  vertical logic (golden rule 2), zero Chroma/Ollama access (golden rule 1).
- **The domain models ARE the response schemas.** `Answer`, `Citation`, `CorpusStats`,
  `VerticalConfig` are already Pydantic `BaseModel` (frozen) — FastAPI serializes them to
  JSON natively. No hand-written DTOs that could drift from the domain.
- **One engine per Vertical, cached.** Mirror `app.py`'s `@st.cache_resource` with a
  process-level dict/`@lru_cache` in the API: building an engine is cheap/offline, but
  `warm_up()` + `check_health()` are not — cache the built engine per vertical.
- **Fail-fast preserved.** `RagEngineError` subtypes map to HTTP status + an actionable
  message body. No `except: pass`; the actionable error surfaces to the client.

## Base

- Prefix: `/api`
- Content: `application/json`, except `/query` which is `text/event-stream` (SSE).
- CORS: allow the Vite dev origin (`http://localhost:5173`) in dev; same-origin in the
  packaged build (front served as static files by FastAPI, or via Tauri sidecar).

---

## Routes

### `GET /api/health`
Aggregated preflight — backs the sidebar "Conectado a Ollama" badge.
Wraps `RagEngine.check_health()` for the active/default vertical.

- **200** `{ "ok": true, "llm_model": "qwen2.5:7b", "embedding_model": "bge-m3", "ollama_base_url": "http://localhost:11434", "abstention_text": "No encuentro esto en los documentos proporcionados." }`
- **503** `{ "ok": false, "error_code": "ollama_unreachable", "message": "<actionable>" }`
  - `error_code` ∈ `ollama_unreachable | model_not_pulled` (from the `RagEngineError` subtype).
  - `abstention_text` is the exact abstention literal (source of truth:
    `core.generate.ABSTENTION_TEXT`). Clients may use it for cosmetic streaming cleanup
    (hiding the phrase while tokens arrive) — NEVER to decide abstention: the `done`
    event's `is_abstention`/`suppress_citations` own that resolution.

### `GET /api/verticals`
Lists the configured verticals + their presentation config. Backs the welcome cards and
the sidebar switcher. Reads each `config/<v>.yaml` via `load_vertical_config`.

- **200**
```json
{
  "verticals": [
    {
      "id": "legal",
      "display_name": "Asistente de normativa legal",
      "domain_name": "Normativa legal",
      "domain_letter": "L",
      "domain_sublabel": "BOE",
      "domain_tagline": "BOE · Legislación laboral",
      "example_questions": ["¿Cuántos días...?", "..."]
    },
    { "id": "health", "...": "..." }
  ]
}
```
- Only presentation-safe fields are exposed. **Never** serialize `system_prompt`,
  `corpus_path`, or `collection_name` — those are internal, not the front's business.

### `GET /api/verticals/{id}/corpus`
Read-only corpus snapshot — backs the sidebar "Corpus listo · N docs · M fragmentos"
block and the corpus dialog (mock 06). Wraps `RagEngine.corpus_stats_for(config)` (the
cheap path: VectorStore only, no LLM warm-up).

- **200** — this is `CorpusStats` serialized as-is:
```json
{
  "document_count": 10,
  "chunk_count": 3407,
  "embedding_model": "bge-m3",
  "document_ids": ["BOE-A-2015-11430", "..."]
}
```
- **404** if `id` is not a known vertical. **503** wrapping `RetrievalError`/store failure.

### `POST /api/verticals/{id}/query`  → **SSE stream**
The core use case. Wraps `RagEngine.answer_stream(query)`, which returns a
`StreamedAnswer(part_stream: Iterator[AnswerPart], citations: list[Citation])` —
`text_stream` is its derived plain-text view, which is what the token events consume.

**Request body**
```json
{ "query": "¿Cuántos días de vacaciones...?" }
```

**Response:** `text/event-stream`. The engine gives citations up front (fixed the instant
retrieval returns) and streams text after — so the SSE event order mirrors that exactly:

1. `event: citations` — sent **first**, once, before any token. Lets the front reserve the
   sources panel / abstention slot before text arrives (the same ordering `app.py`'s
   `label_slot` relied on).
   ```
   event: citations
   data: {"citations": [{"document_id":"BOE-A-2015-11430","page":12,"section":"Art. 38","chunk_text":"..."}], "is_abstention": false}
   ```
   - `is_abstention` here reflects ONLY the hard path (`citations == []`). It is an early
     hint, NOT the final decision — the authoritative resolution arrives in `done` (soft
     abstention is only detectable after the full text is known).
2. `event: token` — repeated, one per text fragment from `text_stream`. Plain CLEAN prose
   for the typewriter effect: the model no longer emits `[N]` markers (citation redesign —
   citations are anchored after the fact, not written inline). The client renders tokens
   verbatim; chips wait for `done`.
   ```
   event: token
   data: {"text": "Según"}
   ```
3. `event: done` — once, authoritative resolution + the typed `parts` view of the final text.
   ```
   event: done
   data: {"is_abstention": false, "suppress_citations": false, "parts": [
     {"kind": "text", "text": "Según el artículo 38 del Estatuto, el periodo será de treinta días naturales."},
     {"kind": "cite", "n": 1}
   ]}
   ```
   - `parts` come from the **structured anchoring pass** (`Generator.parts_for_text`, via
     the `StreamedAnswer.resolve_parts` seam) — NOT from parsing markers: core segments
     the clean text into sentences and a second constrained-JSON LLM call anchors each
     supported sentence to its fragment, validated deterministically. `n` is the **1-based
     index into the `citations` event's list** (core already remapped fragment numbers
     through the dedup) — the client resolves `n → citations[n-1]` positionally and never
     parses anything itself.
   - **`inline_citation_mode`** (per-vertical config, `structured | off`) governs what
     `parts` contain. `structured`: TextParts interleaved with anchored CiteParts; the
     anchor pass runs at close over the full text, so `done` arrives a few seconds AFTER
     the last `token` (the user is already reading the complete answer — accepted
     trade-off). `off`: a single `TextPart`, no chips, no second LLM call, `done` is
     immediate. The api never decides the mode; core does.
   - Client flow (enfoque B): render `token` text incrementally while streaming; on `done`,
     replace the raw text with the render of `parts` (CiteChips in place).
   - On abstention, `parts` is a single `TextPart` with the abstention text and NO
     `CitePart`s — never an empty list — consistent with `suppress_citations` (a cite chip
     under a suppressed sources panel would point at nothing renderable). The anchor pass
     is skipped entirely on abstention.
   The server accumulates the full text during the stream and resolves abstention at close
   with the SAME criterion the Streamlit `layout` used
   (`not citations or full_text.strip().startswith(ABSTENTION_TEXT)`). The client renders
   tokens as they arrive, then on `done`: if `is_abstention` → show the abstention pill and
   DISCARD the sources panel (even if the `citations` event carried noise citations);
   otherwise render the sources normally. `suppress_citations == is_abstention`.

   **AnswerPart types** (mirror of `core.models`, discriminated on `kind`):
   - `TextPart` — `{"kind": "text", "text": str}`: a run of plain answer text.
   - `CitePart` — `{"kind": "cite", "n": int}`: an inline citation marker; `n` indexes the
     `citations` list 1-based. Invalid/out-of-range markers (and the echoed `[N]` template
     literal) were already dropped by core and never reach the wire.
4. `event: error` — if generation fails mid-stream (Ollama drops). Carries the actionable
   message; the front clears the loading state and shows the error card.
   ```
   event: error
   data: {"error_code":"ollama_unreachable","message":"<actionable>"}
   ```

**Why SSE, not WebSocket:** the stream is one-directional (server → client), HTTP-native,
trivial to proxy, and matches `answer_stream`'s pull model. FastAPI `StreamingResponse`
wraps the generator directly. (Mid-stream cancellation — user hits stop — is a v2 concern;
for the MVP the client just drops the connection.)

#### Hard vs soft abstention (why `done` is authoritative)

- **Hard abstention:** retrieval returned empty context → `citations == []` → the engine
  yields the abstention sentence whole, no LLM call. Detectable in the `citations` event.
  Rare with a real ingested corpus.
- **Soft abstention:** vector search ALWAYS returns top-k neighbours, so with a populated
  corpus retrieval is practically never empty — the hard guard rarely fires. Instead the
  LLM declines in prose with `ABSTENTION_TEXT` while carrying noise citations. This is the
  common case and is ONLY detectable after the full text is known.

The resolution lives server-side in the `api/` SSE adapter (mirroring where it lived in the
Streamlit `layout` — Presentation, not Domain). `core/` is untouched; `api/` reuses
`core.generate.ABSTENTION_TEXT` (single source of truth). The client never replicates
domain heuristics — it consumes the resolved `done` decision.

### `GET /api/verticals/{id}/sources/{document_id}?page={n}`  *(v2 — source viewer, mock 09)*
Returns the `chunk_text` provenance for the source viewer drawer. Deferred: the honest
viewer uses `Citation.chunk_text` already carried in the `citations` SSE event, so the
front can render the cited passage **without** an extra round-trip for the MVP. This route
is only needed if we later want the full document page render (PyMuPDF → image), which is
out of scope now.

---

## Error mapping (`RagEngineError` → HTTP)

| Domain error              | HTTP | `error_code`          |
|---------------------------|------|-----------------------|
| `OllamaUnreachableError`  | 503  | `ollama_unreachable`  |
| `ModelNotPulledError`     | 503  | `model_not_pulled`    |
| `EmptyCorpusError`        | 409  | `empty_corpus`        |
| `RetrievalError`          | 503  | `retrieval_failed`    |
| unknown vertical id       | 404  | `unknown_vertical`    |
| `RagEngineError` (base)   | 500  | `engine_error`        |

Body shape is uniform: `{ "error_code": "...", "message": "<the exception's actionable text>" }`.
The exception messages in `core/models.py` are already written to be actionable (NFR6) —
pass them straight through, do not rewrite them in the API.

---

## Engine lifecycle in the API (mirrors `app.py._load_engine`)

```python
# api/dependencies.py — one built+warmed engine per vertical, process-cached.
@lru_cache(maxsize=None)
def get_engine(vertical_id: str) -> RagEngine:
    config = load_vertical_config(Vertical(vertical_id))   # ValueError → 404 unknown_vertical
    engine = RagEngine.from_vertical_config(config)         # cheap, offline
    engine.warm_up()                                        # best-effort (best-effort in core)
    return engine
```

- `check_health()` is called by `/api/health` and defensively before the first query, not
  on every request (same "one check_health per rerun" discipline as `app.py`).
- `warm_up()` failure is non-fatal (as in core): the actionable error still surfaces via
  `check_health()`.
- The `/query` route calls `get_engine(id).answer_stream(body.query)` and adapts the
  `StreamedAnswer` to the SSE event sequence above.

## What the API deliberately does NOT do

- No auth (local single-user app; add later if the commercial `.exe` needs it).
- No conversation persistence (history lives client-side, as it did in session_state).
- No ingest endpoint (ingest stays offline/CLI per SPEC §8; the `.exe`/BYOD story is V3+).
- No vertical branching. Everything vertical-specific comes from `VerticalConfig`.
