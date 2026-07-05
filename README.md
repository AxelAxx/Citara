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
**Core:** Ollama (Qwen2.5 7B) · BGE-M3 embeddings · ChromaDB · LangChain · pymupdf4llm.
**Presentation:** FastAPI (HTTP adapter over the `core/` façade) + React + Vite + Tailwind.
See [`docs/DECISIONS.md`](./docs/DECISIONS.md) for the why (incl. the Streamlit→React
migration and licensing notes) and [`docs/API_CONTRACT.md`](./docs/API_CONTRACT.md) for the
HTTP frontier.

> The original Streamlit UI (`app.py`, `ui/`) is frozen as a safety net during the
> migration and removed once the React app is complete.

## Quickstart
```bash
# 1. models (one-time)
ollama pull qwen2.5:7b
ollama pull bge-m3

# 2. python env + deps
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate
pip install -r requirements.txt

# 3. frontend deps (one-time)
cd frontend && npm install && cd ..

# 4. add PDFs to data/health/ (e.g. GuíaSalud) and/or data/legal/ (e.g. BOE)

# 5. ingest a vertical (offline CLI — not the UI)
python -m core.ingest --vertical health
```

### Run (two processes, local)
Ollama must be running (`ollama serve`). Then, in **two terminals**:
```bash
# Terminal 1 — backend API (FastAPI over core/)
uvicorn api.main:app --reload --port 8000        # http://localhost:8000  (/docs for Swagger)

# Terminal 2 — frontend (Vite dev server) — MUST run inside frontend/
cd frontend && npm run dev                       # http://localhost:5173
```
Open **http://localhost:5173**. The frontend proxies `/api` to the backend on :8000.

> `npm run dev` fails from the repo root (`ENOENT ... package.json`) — the frontend's
> `package.json` lives in `frontend/`. Always `cd frontend` first.

<details>
<summary>Legacy: run the frozen Streamlit V1</summary>

```bash
streamlit run app.py                             # V1, removed once the React app is done
```
</details>

## Docs
- [`docs/SPEC.md`](./docs/SPEC.md) — requirements, architecture, acceptance criteria.
- [`docs/UBIQUITOUS_LANGUAGE.md`](./docs/UBIQUITOUS_LANGUAGE.md) — the project's vocabulary.
- [`CLAUDE.md`](./CLAUDE.md) — working guide for Claude Code.

## Data sources (free, downloadable)
- **Health:** GuíaSalud (clinical practice guidelines), AEMPS/CIMA, WHO.
- **Legal:** BOE open data, CENDOJ jurisprudence, Tribunal Constitucional.

## License
TBD before first publish — see [`DECISIONS.md`](./DECISIONS.md). _(Add a `LICENSE` file.)_
