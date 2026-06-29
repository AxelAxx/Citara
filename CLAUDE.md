# CLAUDE.md

Operating guide for Claude Code in this repository. Read this, [`docs/SPEC.md`](./docs/SPEC.md),
and [`docs/UBIQUITOUS_LANGUAGE.md`](./docs/UBIQUITOUS_LANGUAGE.md) before writing code.

## What this project is

`rag-engine`: a vertical-agnostic, **local, free** RAG ("chat with your documents") engine that
ships **two demos from one codebase** — `legal` and `health` — over public Spanish documents.
Portfolio MVP, ~4 days. The whole point is reuse: **one `RagEngine`, many Verticals**.

## Golden rules (do not violate)

1. **`core/` is framework-free.** No Streamlit, no FastAPI, no web/IO framework imports in `core/`.
   Dependencies point inward (Presentation → Application → Domain). Ollama/Chroma/PyMuPDF are
   adapters injected behind interfaces, never imported into domain logic directly except in the
   designated adapter module.
2. **No vertical-specific logic in `core/`.** Anything that differs between legal and health lives
   in `config/<vertical>.yaml` (`VerticalConfig` / `SystemPrompt`). There is no `legal.py`.
   If you're about to branch on the vertical inside `core/`, stop — it belongs in config.
3. **Every `Answer` is grounded and cited.** Never produce an answer path that can return prose
   without `Citation`s, and never let the `Generator` answer beyond `RetrievedContext`. Abstention
   is the correct behaviour when context is insufficient.
4. **Same embedding model for ingest and query.** Mismatch silently destroys retrieval. Centralize
   the model name in config; never hardcode it in two places.
5. **Fail fast, loud.** Ollama unreachable, model not pulled, empty corpus → raise a clear,
   actionable error. No silent `except: pass`. No empty fallbacks that hide the cause.
6. **Use the Ubiquitous Language verbatim.** Class/function/variable names must match the glossary.
   If you need a new concept, add it to `UBIQUITOUS_LANGUAGE.md` first, then code it.
7. **Local & free only.** Never introduce a paid/cloud inference call. If you think you need one,
   it's wrong for this project.

## Code conventions

- **Language:** Python 3.11+. Code, comments, docstrings, identifiers in **English**.
  (Corpus content, `SystemPrompt`s, and end-user UI strings are in **Spanish** — that's data, not code.)
- **Typing:** type hints on every public function/method in `core/`. Prefer dataclasses / Pydantic
  models for value objects (`Chunk`, `ChunkMetadata`, `Answer`, `Citation`, `VerticalConfig`).
- **Comments:** explain **why**, not **what**. Comment edge cases, non-obvious ordering, and the
  "mismatch-breaks-retrieval" class of traps. No narration of obvious code.
- **Structure:** small, single-responsibility modules per the SPEC §6 map. Favor composition over
  inheritance. Return early; avoid deep nesting.
- **Errors:** raise specific exceptions (`OllamaUnreachableError`, `ModelNotPulledError`,
  `EmptyCorpusError`, …) over bare `Exception`. Surface the actionable fix in the message.

## Module map (build order)

| Order | File | Responsibility | SPEC |
|------:|------|----------------|------|
| 1 | `core/models.py` | value objects + types, no logic | — |
| 2 | `core/ingest.py` | `Loader` + `Chunker` + ingestion driver | FR1–FR3 |
| 3 | `core/embed.py` | `Embedder` (Ollama / BGE-M3) | FR4 |
| 4 | `core/store.py` | `VectorStore` (ChromaDB, `Collection`) | FR5 |
| 5 | `core/retrieve.py` | `Retriever` | FR6 |
| 6 | `core/generate.py` | `Generator` (prompt + Qwen2.5) | FR7–FR9 |
| 7 | `core/engine.py` | `RagEngine` wiring from `VerticalConfig` | G1, FR10 |
| 8 | `app.py` | Streamlit `App` + `SourcesPanel` | FR11 |
| 9 | `config/*.yaml` | `VerticalConfig` per Vertical | FR10 |

Build inner→outer. A module is done when its acceptance criteria (SPEC §7) hold.

## Defaults (don't rediscover these)

`chunk_size=600`, `chunk_overlap=90`, `top_k=5`.
LLM `qwen2.5:7b`. Embedder `bge-m3`. Ollama at `http://localhost:11434`.
Chroma persists to `./chroma_db`. Corpora under `data/<vertical>/`.

## Commands

```bash
# environment
uv venv && source .venv/bin/activate      # or: python -m venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt        # or: pip install -r requirements.txt

# models (one-time)
ollama pull qwen2.5:7b
ollama pull bge-m3
ollama ps                                 # verify GPU offload

# ingest a vertical (offline; idempotent)
python -m core.ingest --vertical health
python -m core.ingest --vertical legal

# run the app
streamlit run app.py

# tests
pytest -q
```

## Definition of done for any change

- Satisfies the relevant SPEC Acceptance Criteria (§7).
- No `core/` import of a UI/web framework; no vertical branching in `core/`.
- New domain terms added to `UBIQUITOUS_LANGUAGE.md`.
- `pytest -q` green (mock `Embedder`/`Generator`; no live LLM needed for unit tests).
- Errors are specific and actionable.

## Working agreement with the human

- Generate **boilerplate** (module skeletons, loaders, the Streamlit component, README, tests)
  and let the human own prompt quality and retrieval tuning — that's where the value is.
- When a task is ambiguous, re-read SPEC + glossary before asking; ask only if still ambiguous.
- Trace work back to FR/AC IDs in commit messages (e.g. `feat(retrieve): top_k search [FR6, AC6]`).
- Never widen scope into §8 future work without being asked.
