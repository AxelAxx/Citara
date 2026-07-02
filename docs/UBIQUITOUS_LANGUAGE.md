# Ubiquitous Language — rag-engine

> Single source of truth for the vocabulary of this project. Every term here is used
> **verbatim** in code (class/function/variable names), commits, docs, and conversation.
> If a concept is not in this glossary, it does not exist in the domain yet — add it here first.
>
> Convention: domain terms are written in English in code (per project rules), even though
> the document corpora and end-user UI are in Spanish.

---

## 1. Core domain (the RAG engine)

| Term | Definition | Code identifier |
|------|------------|-----------------|
| **Engine** | The vertical-agnostic RAG pipeline. Knows nothing about "legal" or "health"; it is configured by a `VerticalConfig`. The whole reason the project exists: one Engine, many verticals. | `RagEngine` |
| **Vertical** | A business domain the Engine is pointed at (e.g. `legal`, `health`). A Vertical is *data + config*, never code. Adding a Vertical must require zero changes to `core/`. | `Vertical` (enum), `VerticalConfig` |
| **Corpus** | The full set of `SourceDocument`s belonging to one Vertical. Lives under `data/<vertical>/`. | `Corpus` |
| **SourceDocument** | One original file as downloaded (a PDF from BOE, GuíaSalud, etc.) before any processing. Identified by a stable `document_id`. | `SourceDocument` |
| **document_id** | Stable, human-meaningful identifier of a `SourceDocument`, used in citations. For legal, prefer the official id (e.g. `BOE-A-2015-11430`); otherwise the slugified filename. | `document_id: str` |
| **Chunk** | A contiguous slice of a `SourceDocument`'s text, the atomic unit that gets embedded and retrieved. Carries `ChunkMetadata`. Never store a chunk without its metadata. | `Chunk` |
| **ChunkMetadata** | The provenance attached to every `Chunk`: at minimum `document_id`, `page`; optionally `section`, `vertical`, `source_path`. This is what makes **Citations** possible. | `ChunkMetadata` |
| **Embedding** | The dense vector representation of a `Chunk` (or a `Query`), produced by the `Embedder`. | `Embedding` (alias for `list[float]`) |
| **Embedder** | Component that turns text into `Embedding`s via the local embedding model (BGE-M3 through Ollama). Same model MUST be used for ingestion and query — mismatched models silently break retrieval. | `Embedder` |
| **VectorStore** | Persistent store of `Chunk`s + `Embedding`s + `ChunkMetadata` (ChromaDB). One `Collection` per Vertical. | `VectorStore` |
| **Collection** | The ChromaDB namespace holding one Vertical's vectors. Named after the Vertical (`collection_name` in config). Switching Vertical = loading a different Collection. | `Collection` |
| **Retriever** | Given a `Query`, returns the top-k most relevant `Chunk`s from the active `Collection`, optionally filtered by metadata. | `Retriever` |
| **Query** | The user's natural-language question, in Spanish. | `Query` |
| **RetrievedContext** | The ordered list of `Chunk`s the `Retriever` returns for a `Query`. The raw material the `Generator` is allowed to use — and nothing else. | `RetrievedContext` |
| **Generator** | Component that builds the grounded prompt from `RetrievedContext` + `Query`, calls the local LLM (Qwen2.5 through Ollama), and returns an `Answer`. | `Generator` |
| **Answer** | The Generator's output: the response text **plus** the list of `Citation`s it is grounded on. An Answer without citations is a bug, not a feature. | `Answer` |
| **Citation** | A reference inside/after an `Answer` pointing to the `SourceDocument` (and page) a claim came from. Derived from `ChunkMetadata`. | `Citation` |
| **Grounding** | The principle that every factual claim in an `Answer` must trace back to a `RetrievedContext` chunk. "Not grounded" ⇒ the Generator must abstain (see **Abstention**). | — |
| **Abstention** | The required behaviour when `RetrievedContext` does not support an answer: the Generator says it cannot find it in the documents instead of inventing one. The opposite of a **Hallucination**. | — |
| **Hallucination** | Any claim in an `Answer` not supported by `RetrievedContext`. The thing this architecture exists to prevent. | — |

---

## 2. Ingestion pipeline

| Term | Definition | Code identifier |
|------|------------|-----------------|
| **Ingestion** | The offline process that turns a `Corpus` of `SourceDocument`s into a populated `Collection`. Runs as a script, not at query time. | `ingest` |
| **Loader** | Reads a `SourceDocument` from disk and extracts text + page structure (via `pymupdf4llm`, `page_chunks=True`). | `DocumentLoader` |
| **Chunker** | Splits loaded text into `Chunk`s (`RecursiveCharacterTextSplitter`, ~600 tokens, ~15% overlap) and propagates `ChunkMetadata`. | `Chunker` |
| **chunk_size** | Target size of a `Chunk` in tokens. Project default: **600**. | `chunk_size: int` |
| **chunk_overlap** | Tokens shared between adjacent `Chunk`s. Project default: **90** (~15%). | `chunk_overlap: int` |
| **top_k** | Number of `Chunk`s the `Retriever` returns per `Query`. Project default: **5**. | `top_k: int` |

---

## 3. Configuration & presentation

| Term | Definition | Code identifier |
|------|------------|-----------------|
| **VerticalConfig** | The declarative description of a Vertical: `corpus_path`, `collection_name`, `system_prompt`, display name/branding. Lives in `config/<vertical>.yaml`. The ONLY thing that changes between verticals. | `VerticalConfig` |
| **SystemPrompt** | The instruction block given to the LLM that enforces Grounding, Abstention, citation format, and Spanish output. Vertical-specific (legal vs clinical tone) but same *rules*. | `system_prompt` |
| **App** | The Streamlit presentation layer. Reads a `VerticalConfig`, instantiates a `RagEngine`, renders the chat + sources panel. Contains no domain logic. | `app.py` |
| **example_questions** | Optional per-Vertical list of suggested Queries the App offers on the empty chat state. Pure `VerticalConfig` data — clicking one submits it through the exact same path as a typed Query. | `example_questions: list[str]` |
| **domain_name** | Optional short Vertical name shown on the welcome domain card and the "Comenzar" CTA (e.g. "Normativa legal"). Empty ⇒ the App falls back to `display_name`. Pure `VerticalConfig` presentation data. | `domain_name: str` |
| **domain_letter** | Optional single-letter chip identifying a Vertical on its domain card (e.g. "L", "S"). Declared in config, never derived in code — deriving from the enum value would give health an "H", not "S". | `domain_letter: str` |
| **domain_sublabel** | Optional source label under a domain card's name (e.g. "BOE", "GuíaSalud"). Never carries a document count — real counts are runtime corpus data, not static config. | `domain_sublabel: str` |
| **domain_tagline** | Optional source line next to the chat header's tag-pill (e.g. "BOE · Legislación laboral"). Empty ⇒ the header omits it. Pure `VerticalConfig` presentation data. | `domain_tagline: str` |
| **SourcesPanel** | The UI element listing the `Citation`s behind the current `Answer`. | — |

---

## 4. Boundaries & rules of speech

- **"Document" is ambiguous — do not use it bare.** Say `SourceDocument` (the file) or `Chunk` (the slice). Reserve "document" only for the literal ChromaDB API.
- **"Index" is a verb here, not a noun.** We *ingest* a Corpus; we do not "build an index". The noun is `Collection`.
- **Legal/Health are Verticals, never modules.** There is no `legal.py`. There is `config/legal.yaml`.
- **The Engine never knows the Vertical's meaning.** If you find legal- or health-specific logic leaking into `core/`, it is a design violation — push it into `VerticalConfig`/`SystemPrompt`.
- **A demo is not a product.** This is a portfolio MVP over *public* documents (guidelines, official bulletins). It is never described as fit for real clinical or legal decisions.
