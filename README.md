# rag-engine

Local, free, vertical-agnostic **RAG** ("chat with your documents"). One engine, two demos:
**legal** and **health**, over public Spanish documents. Answers are **grounded** and **cited**,
and the whole thing runs **offline** on a single 8 GB GPU.

> Portfolio MVP. Not a certified legal/clinical tool. Public documents only — no patient data.

## Why it's interesting
Same `core/` engine serves multiple verticals by swapping only `config/<vertical>.yaml` and the
document corpus — no domain logic changes. Demonstrates Clean Architecture, RAG with citations,
abstention (no hallucinated answers), and a fully local/private stack.

## Stack
Ollama (Qwen2.5 7B) · BGE-M3 embeddings · ChromaDB · LangChain · Streamlit · pymupdf4llm.
See [`DECISIONS.md`](./DECISIONS.md) for the why (and licensing notes).

## Quickstart
```bash
# 1. models (one-time)
ollama pull qwen2.5:7b
ollama pull bge-m3

# 2. env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. add PDFs to data/health/ (e.g. GuíaSalud) and/or data/legal/ (e.g. BOE)

# 4. ingest a vertical
python -m core.ingest --vertical health

# 5. run
streamlit run app.py
```

## Docs
- [`docs/SPEC.md`](./docs/SPEC.md) — requirements, architecture, acceptance criteria.
- [`docs/UBIQUITOUS_LANGUAGE.md`](./docs/UBIQUITOUS_LANGUAGE.md) — the project's vocabulary.
- [`CLAUDE.md`](./CLAUDE.md) — working guide for Claude Code.

## Data sources (free, downloadable)
- **Health:** GuíaSalud (clinical practice guidelines), AEMPS/CIMA, WHO.
- **Legal:** BOE open data, CENDOJ jurisprudence, Tribunal Constitucional.

## License
TBD before first publish — see [`DECISIONS.md`](./DECISIONS.md). _(Add a `LICENSE` file.)_
