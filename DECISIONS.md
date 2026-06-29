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
