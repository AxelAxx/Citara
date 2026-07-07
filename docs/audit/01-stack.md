# 01 — Stack tecnológico REAL en uso

> Auditoría read-only sobre `2bd0ded`. Cada pieza: qué es, para qué se usa AQUÍ, y dónde se ve.
> Se distingue explícitamente lo **cableado** de lo que está **solo declarado** en dependencias.

## Backend / RAG (Python 3.11+, sin `pyproject.toml` — solo `requirements.txt`)

| Pieza | Qué es | Uso real aquí | Evidencia |
|---|---|---|---|
| **ChromaDB** (`chromadb>=0.5`) | Vector store embebido con persistencia local | Una `Collection` por vertical (`legal_boe` / `health_gpc`), persistida en `./chroma_db` vía `PersistentClient`. Upsert idempotente por chunk_id determinista; el query devuelve `include=["embeddings", ...]` para que el AnchorVerifier no re-embeba | `core/store.py:318` (import lazy), `:305` (PersistentClient), `:143` (upsert), `:191-196` (include) |
| **Ollama (servidor)** | Runtime local de modelos (LLM + embeddings) | `qwen2.5:7b` (generación + anchoring) y `bge-m3` (embeddings), ambos vía **HTTP crudo con `requests`** — NO por SDK: `POST /api/embed` (embed), `POST /api/chat` (generate, streamed NDJSON y no-streamed), `GET /api/tags` (preflight) | `core/embed.py:194` (/api/embed), `core/generate.py:723,787` (/api/chat), `embed.py:132` (/api/tags) |
| **requests** | Cliente HTTP | El ÚNICO transporte hacia Ollama (import lazy en los dos adapters) | `core/embed.py:251`, `core/generate.py:999` |
| **pymupdf4llm** (⚠ AGPL-3.0) | Extractor PDF→markdown | Loader de ingesta: `to_markdown(path, page_chunks=True)`, páginas 1-based | `core/ingest.py:152,166`; riesgo de licencia flaggeado en `requirements.txt:10` y `docs/DECISIONS_merged.md` |
| **langchain-text-splitters** | Splitter de texto | El Chunker: `RecursiveCharacterTextSplitter` con `length_function` de tokens inyectada | `core/ingest.py:200-210` |
| **tiktoken** | Tokenizador BPE | Medir chunk_size/overlap en TOKENS (no caracteres): `cl100k_base` como proxy de longitud | `core/ingest.py:96-109` |
| **pyyaml** | Parser YAML | Cargar `VerticalConfig` desde `config/<vertical>.yaml` — un único lector | `core/ingest.py:354-383` (`load_vertical_config`) |
| **FastAPI** (`>=0.115`) | Framework API | 4 rutas finas sobre core; CORS restringido a `http://localhost:5173`; handlers de excepción globales que mapean `RagEngineError`→HTTP | `api/main.py`, `api/errors.py:24-38` (tabla de mapeo) |
| **sse-starlette** | SSE para Starlette | `EventSourceResponse` del endpoint de query (streaming de eventos con nombre) | `api/routes/query.py:9,32` |
| **uvicorn[standard]** | Servidor ASGI | Arranque documentado: `uvicorn api.main:app --port 8000` | `api/main.py:3-5` (docstring) |
| **pydantic** (transitiva de FastAPI) | Modelos/validación | TODOS los value objects del dominio (frozen, `extra="forbid"`) + invariantes tipadas (Answer grounded, CitePart en rango) | `core/models.py:24,225-253` |
| **pytest** | Tests | 123 tests, todo mockeado (requests.post/get monkeypatcheados, Embedder stub, StreamedAnswer fake) — cero red | `tests/*` (9 ficheros) |

### Declarado pero NO cableado (deuda de manifiesto)

Verificado por grep de imports en `core/`, `api/`, `app.py`, `ui/`:

- **`langchain>=0.3`** y **`langchain-community>=0.3`**: **ningún import en todo el repo**. Solo se usa el paquete separado `langchain_text_splitters`.
- **`langchain-ollama>=0.2`**: ningún import; el comentario de `requirements.txt:4` ("OllamaEmbeddings adapter") está **desactualizado** — `core/embed.py:8-14` documenta explícitamente por qué se abandonó el SDK (proxy a un runner interno con puerto efímero que rechaza conexión) a favor del endpoint HTTP estable.
- **`ollama>=0.3`** (SDK Python): ningún import; mismo motivo.
- Consecuencia: 4 dependencias eliminables del manifiesto (con re-test); las razones están documentadas en docstrings de `embed.py`/`generate.py:8-14` pero el manifiesto no se actualizó.

### Caso especial: `streamlit>=1.40`

Dependencia **viva solo por el legacy congelado** (`app.py:20` + 11 imports bajo `ui/`). La app real (React+FastAPI) no lo usa en ningún punto: `api/` y `core/` no lo importan (verificado). Arrastra runtime pesado (tornado, websockets, watchdog…) en cada instalación de `requirements.txt` aunque el flujo actual nunca lo ejecute. `requirements.txt:14-16` ya lo etiqueta como "safety net" de la migración. Decisión pendiente: mover a un `requirements-legacy.txt` o retirar `ui/`+`app.py` cuando la migración se dé por definitiva.

### Dev-only

- **playwright** (`requirements-dev.txt:6`) — verificación de UI con browser real; no es dependencia runtime.

## Frontend (`frontend/`)

| Pieza | Versión | Uso real | Evidencia |
|---|---|---|---|
| **React** | ^19.2 | SPA de 2 pantallas (Welcome → Chat) + splash; estado con hooks planos, sin router ni state-manager (flujo modelado como unión discriminada `View`) | `src/App.tsx:15-18` |
| **TypeScript** | ~6.0 | Estricto; tipos del contrato API espejados 1:1 a mano | `src/api/client.ts:15-89` |
| **Vite** | ^8.1 | Dev server (5173) + build (`tsc -b && vite build`); proxy dev `/api`→8000 opcional | `vite.config.ts`, `package.json:8` |
| **Tailwind CSS** | ^3.4 | Tokens verbatim del hand-off de diseño (`export/citara.css`); el acento es CSS var swapeada por vertical en runtime (`setAccent`) | `tailwind.config.ts:27-30`, `src/theme/accent.ts:46-53` |
| **oxlint** | ^1.71 | Linter (script `lint`) | `package.json:10` |
| **SSE a mano** | — | Sin `EventSource` (es GET-only): `fetch` + `body.getReader()` + parser de frames propio, para poder POSTear el body y leer eventos con nombre | `src/api/client.ts:148-226` |

Runtime del bundle: **solo react/react-dom** — cero librerías de UI, fetch nativo, CSS por Tailwind.

## Infra / operación

- **Sin Docker** (ni Dockerfile ni compose — verificado por glob). Tres procesos localhost: Ollama :11434, uvicorn :8000, Vite :5173.
- **Persistencia**: `./chroma_db` en disco (`core/store.py:51`); ingesta offline por CLI (`python -m core.ingest --vertical <v>`, `core/ingest.py:386-430`) con preflight fail-fast de Ollama ANTES de embeber (`:416`).
- **Modelos**: nombres centralizados en `VerticalConfig` (regla de oro 4); defaults `bge-m3`/`qwen2.5:7b` como fallback del loader (`core/ingest.py:350-351,381-382`).
