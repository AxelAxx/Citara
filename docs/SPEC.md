# SPEC — rag-engine

> Spec-driven development. This document is the contract. Code is correct when it satisfies the
> **Acceptance Criteria** (§7), not when it "feels done". Terms in `CamelCase`/`snake_case` are
> defined in [`UBIQUITOUS_LANGUAGE.md`](./UBIQUITOUS_LANGUAGE.md) and used verbatim.

## 1. Problem statement

Professionals in privacy-sensitive verticals (legal, health) need to ask natural-language
questions over their own document sets, with answers **grounded in and citing** those documents,
**without sending data to any cloud**. This project builds a single, vertical-agnostic RAG
**Engine** and ships **two demos** (legal + health) from the same codebase to prove the
architecture is reusable.

This is a **portfolio MVP**, buildable in ~4 days (two weekends), fully local and free.

## 2. Goals / Non-goals

**Goals**
- G1. One `RagEngine` powers ≥2 Verticals with **zero changes to `core/`** — only `config/<vertical>.yaml` + a `Corpus` differ.
- G2. Runs **100% locally and free** on an 8 GB-VRAM GPU (RTX 1080): local LLM + local embeddings + local vector store.
- G3. Every `Answer` is **grounded** and carries **Citations** (source document + page).
- G4. The Engine **abstains** when `RetrievedContext` is insufficient (no hallucinated answers).
- G5. Works in **Spanish** end to end (corpus, queries, answers).
- G6. Clean, modular, testable code (Clean Architecture; `core/` has no UI/IO framework deps).

**Non-goals**
- N1. Not a certified or production legal/clinical tool. Public documents only; no patient data.
- N2. No authentication, multi-tenancy, billing, or horizontal scaling in the MVP.
- N3. No fine-tuning, no agentic tool-calling, no re-ranking (explicit future work, §8).
- N4. No cloud LLM APIs. Local only.

## 3. Users & primary use case

- **Primary user:** a developer/recruiter running the demo, and (narratively) a professional in a small legal/clinical practice.
- **Core loop:** user picks a Vertical → asks a `Query` in Spanish → reads a grounded `Answer` with a `SourcesPanel` of `Citation`s.

## 4. Functional requirements

- FR1. **Ingestion (offline):** given `data/<vertical>/` of PDFs, produce a persistent ChromaDB `Collection` of `Chunk`s with `ChunkMetadata` (`document_id`, `page`, `vertical`, `source_path`, optional `section`).
- FR2. **Loading:** parse PDFs with `pymupdf4llm` (`page_chunks=True`); preserve page numbers.
- FR3. **Chunking:** `RecursiveCharacterTextSplitter`, `chunk_size=600`, `chunk_overlap=90`; metadata propagated to every `Chunk`.
- FR4. **Embedding:** BGE-M3 via Ollama; identical model for ingestion and query.
- FR5. **Storage:** one `Collection` per Vertical, named from `VerticalConfig.collection_name`; persisted under `./chroma_db`.
- FR6. **Retrieval:** top-k (`top_k=5`) similarity search over the active `Collection`, with optional metadata filtering.
- FR7. **Generation:** Qwen2.5 7B via Ollama; prompt built from `RetrievedContext` + `Query` + vertical `SystemPrompt`; output in Spanish.
- FR8. **Grounding & Abstention:** the `SystemPrompt` forbids unsupported claims; if context is insufficient, the `Answer` explicitly states it cannot find it in the documents.
- FR9. **Citations:** the `Answer` lists the `SourceDocument`(s) + page(s) used; UI renders them in the `SourcesPanel`.
- FR10. **Vertical switching:** selecting a Vertical loads its `VerticalConfig` + `Collection` with no code change.
- FR11. **App:** Streamlit chat (`st.chat_input`, history in `st.session_state`) + `SourcesPanel`; graceful loading states and error messages.

## 5. Non-functional requirements

- NFR1. **Locality/privacy:** no network calls to third-party inference services at any point.
- NFR2. **Hardware:** runs on 8 GB VRAM; 7–8B model at Q4_K_M.
- NFR3. **Architecture:** `core/` depends on no UI/web framework; presentation depends on `core/`, never the reverse. Dependencies point inward.
- NFR4. **Testability:** `Chunker`, `Retriever` contract, and Citation extraction are unit-testable without a live LLM (mock the `Embedder`/`Generator`).
- NFR5. **Typing:** strongly typed public interfaces (type hints on all `core/` boundaries).
- NFR6. **Error handling:** fail fast and loud (e.g. Ollama unreachable, model not pulled, empty corpus) — no silent failures.
- NFR7. **Licensing hygiene:** dependency licenses tracked in `DECISIONS.md`; the chosen project license is set before first publish.

## 6. Architecture (Clean Architecture, dependencies point inward)

```
Presentation        app.py  (Streamlit, SourcesPanel)          ── depends on ──┐
                                                                                ▼
Application         RagEngine  (orchestrates the use case)      ── depends on ──┐
                                                                                ▼
Domain / core       Loader · Chunker · Embedder · VectorStore · Retriever · Generator
                    + value objects: SourceDocument, Chunk, ChunkMetadata,
                      RetrievedContext, Answer, Citation, VerticalConfig
                                                                                ▲
Infrastructure      Ollama client, ChromaDB client, pymupdf4llm  ── implements ┘
                    (concrete adapters behind the domain interfaces)
```

Module map (see `UBIQUITOUS_LANGUAGE.md` for each name):

```
core/ingest.py    Loader + Chunker + ingestion driver        (FR1–FR3)
core/embed.py     Embedder (Ollama / BGE-M3)                  (FR4)
core/store.py     VectorStore (ChromaDB, Collection mgmt)     (FR5)
core/retrieve.py  Retriever                                   (FR6)
core/generate.py  Generator (prompt + Ollama / Qwen2.5)       (FR7–FR9)
core/engine.py    RagEngine (wires the above from a VerticalConfig)
core/models.py    value objects + types (no logic)
config/*.yaml     VerticalConfig per Vertical                 (FR10)
app.py            Streamlit App                               (FR11)
```

**Inversion rule:** `core/` defines interfaces; Ollama/Chroma/PyMuPDF are details injected in. Swapping ChromaDB for Qdrant, or Streamlit for FastAPI, must not touch domain logic.

## 7. Acceptance criteria (definition of done)

- AC1. `python -m core.ingest --vertical health` ingests `data/health/` into a persistent `Collection` and reports counts; re-running is idempotent (no duplicate chunks).
- AC2. With the health Vertical, asking a question answerable by the corpus returns an `Answer` whose `SourcesPanel` lists ≥1 correct `SourceDocument` + page.
- AC3. Asking something **not** in the corpus triggers **Abstention** (explicit "not found in the documents"), not a fabricated answer. (Grounding test.)
- AC4. Switching to the legal Vertical works by changing only the selected `VerticalConfig` — **no diff in `core/`** (verifiable by `git diff`).
- AC5. Pulling the GPU plug on the network (airplane mode) does not change behaviour: no external inference calls (NFR1).
- AC6. `pytest` passes: `Chunker` produces correct sizes/overlap/metadata; `Citation` extraction maps `ChunkMetadata`→`Citation`; `Retriever` returns `top_k`; all with mocked `Embedder`/`Generator`.
- AC7. Missing dependency conditions (Ollama down, model not pulled, empty corpus) raise clear, actionable errors (NFR6).
- AC8. `README.md` lets a stranger reproduce the demo: prerequisites, `ollama pull` commands, ingest, run; includes a demo GIF and the architecture diagram.

## 8. Out-of-scope / future work (named, not built)

Hybrid retrieval (BGE-M3 sparse+dense), re-ranking, RAG evaluation harness (golden Q/A set with retrieval-precision metrics), FastAPI + custom frontend for commercialization, open-core split, Docker packaging. Tracked so they are deliberate choices, not omissions.

## 9. Key decisions (summary; full rationale in `DECISIONS.md`)

- LLM: **Qwen2.5 7B Instruct (Q4_K_M)** — Apache-2.0, multilingual consistency.
- Embeddings: **BGE-M3** — MIT, multilingual, hybrid-capable.
- Vector store: **ChromaDB** — persistent, native metadata, LangChain-native.
- Orchestration: **LangChain**. UI: **Streamlit**. Parsing: **pymupdf4llm** (AGPL — flagged for commercial path).
- Defaults: `chunk_size=600`, `chunk_overlap=90`, `top_k=5`.
