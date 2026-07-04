# DECISIONS.md

Architecture and licensing decisions, with rationale. Referenced by SPEC §9 and CLAUDE.md.

## Stack
- **LLM: Qwen2.5 7B Instruct (Q4_K_M) via Ollama.** Apache-2.0 (commercial-friendly) and
  more consistent multilingual behaviour than Llama 3.1 8B (whose license is *not* OSI-open
  and adds attribution/usage restrictions). Runs in ~5 GB on the 8 GB RTX 1080.
- **Embeddings: BGE-M3 via Ollama.** MIT, multilingual, 8192-token context, hybrid (dense+sparse)
  capable. MUST be the same model at ingest and query time.
- **Vector store: ChromaDB.** Persistent, native metadata (needed for Citations), LangChain-native.
  FAISS rejected for an MVP: it's a library, not a database (manual persistence, no metadata).
- **Orchestration: LangChain.** Ubiquity + ecosystem; MIT. LlamaIndex acceptable for retrieval if
  LangChain abstractions get in the way.
- **UI: Streamlit.** Fastest path to a professional chat + sources panel. Chainlit rejected
  (maintenance/security uncertainty as of late 2025); Gradio weaker on persistent chat state.
- **PDF parsing: pymupdf4llm.** Fast, clean Markdown, per-page metadata.
  ⚠️ **AGPL-3.0.** Fine for an AGPL/open-source release; for a *proprietary* distribution,
  swap for `pdfplumber` (MIT) / `pypdfium2`, or buy the Artifex commercial license.

## Licensing path (decide before first publish)
- Portfolio-first → **MIT or Apache-2.0** (max visibility).
- Keep commercialization open → **AGPL-3.0** now, sell commercial exceptions later
  (requires owning copyright / CLA). Cannot "re-close" code already shipped under a permissive license.
- Dependency license summary: Ollama MIT · ChromaDB Apache-2.0 · LangChain MIT ·
  BGE-M3 MIT · pymupdf4llm AGPL-3.0 (flagged) · Qwen2.5 Apache-2.0 · Llama 3.x not OSI-open (avoided).

## Defaults
`chunk_size=600`, `chunk_overlap=90`, `top_k=5`.

## Presentation migration: Streamlit → FastAPI + React (V2.1)

**Context.** The V1 Streamlit UI is functionally complete but hit a hard ceiling on visual
fidelity. The design mocks (11 screens, `citara.css`) assume free HTML/CSS; Streamlit wraps
every widget in framework-owned containers (`stVerticalBlock`, `st-emotion-cache-*`) with
default gaps and styles overridable only by fighting the framework selector by selector.
CSS injected after widgets render competes on specificity; grid layout is inert against
Streamlit's own `display` on buttons; the full-script rerun makes loading overlays clip the
half-built DOM. Not a `core/` or skill problem — Streamlit used outside its purpose.

**Decision.** Migrate Presentation to **FastAPI (backend adapter) + React + Vite + Tailwind**.
`core/` untouched. V1 Streamlit stays frozen as a safety net; deleted only once the new app
runs end-to-end.

**Options.**
- **FastAPI + React + Tailwind — chosen.** Total pixel control; local (uvicorn + Vite +
  Ollama + Chroma); best `.exe` path (see below); industry-standard portfolio signal.
- **Reflex (all-Python).** Rejected — core components sit on Radix with pre-applied styles;
  full control needs low-level `rx.el` (≈ writing HTML anyway). Swaps fighting
  `stVerticalBlock` for fighting Radix; immature, breaking APIs.
- **Gradio.** Rejected — heavy custom UI needs extra JS; same class of problem as Streamlit.
- **Stay on Streamlit (~85%).** Rejected — the ceiling is the reason for the migration.

**Why V2 made it cheap.** The V2 decoupling (`app.py` → `ui/` behind the `core/` façade) was
the preparation. `core/` is a clean library with a public seam (`RagEngine.answer_stream`,
`corpus_stats_for`, `check_health`, `load_vertical_config`) → exposing it over HTTP is ~5
thin routes. Domain models are already Pydantic (frozen) → FastAPI serializes them natively,
no hand-written DTOs. `RagEngineError` subtypes are already actionable → direct HTTP mapping.
`StreamedAnswer(text_stream, citations)` maps 1:1 to the SSE event order. Golden rules hold:
`api/` is Presentation, imports `core/` only through the façade, zero vertical logic.

**Trade-offs.** More initial setup than `streamlit run`; adds TS/JS to a Python stack; two
dev processes (uvicorn + Vite) vs one — solved with a run script. One week is feasible only
because `core/` is untouched. Changes the SPEC's "Streamlit / 4-day MVP" premise (conscious
product decision); V1 frozen, not discarded; SPEC/README updated as part of the migration.

Full route/schema/SSE contract: `API_CONTRACT.md`.

## Packaging: Tauri for the future commercial `.exe` (deferred, post-migration)

**Decision.** When packaging is due (after localhost dev is complete and Streamlit removed),
target **Tauri**: native shell bundling the React build, with FastAPI embedded as a
PyInstaller-frozen sidecar.

**Rationale.** OS WebView (no bundled Chromium) → ~10–15 MB `.exe` vs Electron's 120 MB+;
native installers, code signing, auto-updater; PyInstaller handles a standard ASGI server
(FastAPI) cleanly, unlike Streamlit's tornado+websockets+assets (notoriously fragile to freeze).

**Non-technical blockers before commercial distribution** (not stack issues): Qwen2.5 is
Apache-2.0 (commercial-friendly — already chosen for this reason, see Stack); BGE-M3 MIT,
ChromaDB Apache-2.0 fine; **pymupdf4llm is AGPL-3.0 — swap for pdfplumber/pypdfium2 or buy
the Artifex commercial license before a proprietary `.exe`** (already flagged under Stack);
corpus redistribution terms (BOE/GuíaSalud public but bundling a pre-ingested corpus has its
own rules); code-signing certificate (~200–400 €/yr) to avoid Windows SmartScreen. The `.exe`
does not bundle the model (multi-GB): first-run download or ship separately; Ollama manages it.

**Consequence.** All development and review happen on localhost (uvicorn + Vite). Packaging
is the final step — you cannot iterate UI inside an `.exe`. No packaging work during the
migration week; this only records the target so the stack choice is made with the endgame in mind.
