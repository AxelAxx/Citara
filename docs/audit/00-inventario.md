# Fase 0 — Inventario del repositorio (estado real)

> Auditoría read-only sobre el árbol `2bd0ded` (HEAD = origin/main, working tree limpio salvo
> esta carpeta `docs/audit/`). El código es la única fuente de verdad; SPEC/CLAUDE/glosario
> son la línea base de intención para medir drift.

## Estructura (sin node_modules/.venv/chroma_db/dist/caches)

| Directorio | Qué es (verificado) |
|---|---|
| `core/` | El motor RAG puro (7 módulos): `models.py`, `ingest.py`, `embed.py`, `store.py`, `retrieve.py`, `generate.py`, `engine.py`. Sin imports de UI/web. |
| `api/` | Capa FastAPI: `main.py` (app + CORS), `routes/` (`health.py`, `verticals.py`, `query.py`), `dependencies.py` (lru_cache de engines), `errors.py`, `schemas.py`. |
| `frontend/` | React 19 + Vite 8 + Tailwind 3.4 + TypeScript ~6 (strict). `src/`: `api/client.ts` (cliente tipado + SSE), `hooks/` (4), `components/` (~20), `screens/` (Welcome, Chat), `theme/accent.ts`. |
| `ui/` + `app.py` | **Streamlit CONGELADO** (red de seguridad de la migración). Sigue en requirements. |
| `config/` | `legal.yaml` / `health.yaml`: la única sede de diferencias entre verticales (VerticalConfig). |
| `data/` | Corpus reales: 10 PDFs BOE (legal) + 10 guías GuíaSalud (health). |
| `tests/` | 9 ficheros pytest (123 tests, todo mockeado — sin Ollama vivo). |
| `docs/` | `SPEC.md`, `API_CONTRACT.md`, `UBIQUITOUS_LANGUAGE.md`, `DECISIONS.md`, `KNOWN_LIMITATION_B2_*.md`. |
| `export/` | Mocks HTML/CSS del diseño (hand-off), fuente de los tokens de Tailwind. |
| Raíz | `CLAUDE.md`, `README.md`, `PROGRESS.md`, `ROADMAP.md`, `requirements*.txt`. |

## Manifiestos de dependencias

**Backend (`requirements.txt`)** — sin `pyproject.toml`: langchain/-community/-ollama/-text-splitters (≥0.3/0.2), `requests`, `tiktoken`, `chromadb≥0.5`, `ollama≥0.3`, `pymupdf4llm` (⚠ AGPL-3.0, flaggeado para uso comercial), `pyyaml`, `streamlit≥1.40` (legacy), `fastapi≥0.115` + `uvicorn[standard]` + `sse-starlette≥2.1`, `pytest`. Dev aparte (`requirements-dev.txt`): `playwright`.

**Frontend (`frontend/package.json`)** — runtime mínimo: `react`/`react-dom` ^19.2. Dev: `vite ^8.1`, `typescript ~6.0`, `tailwindcss ^3.4`, `oxlint`, `@vitejs/plugin-react`. Scripts: `dev`, `build` (`tsc -b && vite build`), `lint`, `preview`.

**`vite.config.ts`**: proxy dev `/api` → `http://localhost:8000` (el cliente usa por defecto URL directa vía `VITE_API_URL ?? 'http://localhost:8000/api'`). **`tailwind.config.ts`**: tokens verbatim de `export/citara.css`; el acento es CSS var swapeada por vertical en runtime.

**Docker: NO existe** — ni `Dockerfile` ni `docker-compose` en el repo (verificado por glob). Todo corre en localhost: Ollama (11434) + uvicorn (8000) + Vite (5173).

## Puntos de entrada reales

| Entrada | Comando | Evidencia |
|---|---|---|
| API | `uvicorn api.main:app --port 8000` | `api/main.py` (docstring lo documenta; CORS solo origen 5173) |
| Rutas | `GET /api/health`, `GET /api/verticals`, `GET /api/verticals/{id}/corpus`, `POST /api/verticals/{id}/query` (SSE) | `api/routes/{health,verticals,query}.py` |
| Frontend | `npm run dev` (Vite, 5173) | `frontend/package.json`, `src/main.tsx` |
| Ingesta | `python -m core.ingest --vertical <legal\|health>` | `core/ingest.py:386-429` (`main()` + argparse + `__main__`) |
| Legacy | `streamlit run app.py` | `app.py` + `ui/` (congelado) |
