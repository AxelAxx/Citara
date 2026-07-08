# 05 — Diagnóstico: la verdad del estado del código

> Auditoría read-only sobre `2bd0ded` (el código no cambió desde entonces; los commits
> posteriores son solo `docs/audit/`). Sin adornos: qué dice la documentación, qué hace el
> código, y dónde divergen. Todo anclado a `archivo:línea`.

## 1. Drift código vs docs — FR1..FR11 + SPEC §9

| Req | SPEC dice | Estado real | Evidencia |
|---|---|---|---|
| FR1 | Ingesta offline → Collection persistente con ChunkMetadata | **VIGENTE** | `core/ingest.py` completo; metadata obligatoria en el tipo (`models.py:54-68`); persistencia `./chroma_db` (`store.py:51`) |
| FR2 | pymupdf4llm, `page_chunks=True`, páginas preservadas | **VIGENTE** | `ingest.py:152,166`; páginas 1-based por enumeración propia (no confía en metadata del PDF) |
| FR3 | RecursiveCharacterTextSplitter 600/90 | **VIGENTE con matiz** | `ingest.py:169-210`; el matiz: 600/90 se miden en **tokens** vía `length_function` tiktoken (`:96-109`) — más estricto que el SPEC, no menos |
| FR4 | BGE-M3 vía Ollama, mismo modelo ingest/query | **VIGENTE en el QUÉ, cambiado en el CÓMO** | Modelo centralizado en `VerticalConfig.embedding_model` (`models.py:312`); pero el transporte es HTTP crudo, no SDK ni LangChain → ver fila §9 |
| FR5 | Una Collection por Vertical, `./chroma_db` | **VIGENTE** | `store.py:305` (PersistentClient), `engine.py:151` (collection_name desde config) |
| FR6 | top-k `top_k=5`, filtrado por metadata opcional | **CAMBIADO + AMPLIADO** | Default 5 sigue en `models.py:316`, pero ambos YAML recalibran a **6** (`legal.yaml:18`, `health.yaml:19`). Y existe un **relevance gate** que el SPEC nunca especificó (`retrieve.py:111-118`, umbral por vertical `legal.yaml:27`/`health.yaml:29`) — glosado a posteriori (`UBIQUITOUS_LANGUAGE.md:53`), pero FR6 no se actualizó |
| FR7 | Qwen2.5 7B, prompt de contexto+query+system prompt, español | **VIGENTE + ampliado** | `generate.py:648-684`; ampliaciones no spec'd: streaming (`:477-521`), títulos humanos por `document_titles` (`:665-684`) |
| FR8 | Grounding/abstención **vía SystemPrompt** | **SUPERADO** | Hoy la abstención NO depende del prompt: guard duro determinista sin LLM (`generate.py:455-456,493-495`), strip simétrico (`:354-387`) y autoridad resolved-state en el done (`api/routes/query.py:107`). El SPEC describe la v1 (solo prompt); el código implementa tres mecanismos de estado |
| FR9 | El Answer lista SourceDocument+página; UI los pinta en SourcesPanel | **AMPLIADO fuerte** | Lo spec'd se cumple (`_citations_from_context`, `generate.py:701-722`) y encima: citación inline en 3 etapas + AnchorVerifier (`:213-306,583-596`), `parts` tipados (`models.py:147-183`), split citadas/consultadas en el front (`SourcesPanel.tsx:28-44`). Nada de esto está en el SPEC |
| FR10 | Cambiar de Vertical = cargar otro VerticalConfig, cero código | **VIGENTE** | `api/dependencies.py:18-34` (un engine cacheado por id); AC4 verificable por `git diff` de `core/` |
| FR11 | **App Streamlit** (`st.chat_input`, session_state) | **ABANDONADO (congelado)** | La Presentation viva es React+FastAPI; `app.py`+`ui/` quedan como red de seguridad sin mantenimiento (`requirements.txt:16`). El SPEC §6 aún dibuja "Presentation: app.py (Streamlit)" y el §8 lista "FastAPI + custom frontend" como *future work* — **ya construido sin actualizar el SPEC** |
| **§9** | **"Orchestration: LangChain"** | **DRIFT DE DECISIÓN DE DISEÑO** | Ver desglose abajo |

### La fila que más importa: §9 "Orchestration: LangChain"

- `langchain>=0.3`, `langchain-community>=0.3`, `langchain-ollama>=0.2` y el SDK `ollama>=0.3`
  están **declarados** (`requirements.txt:2-4,9`) y **jamás importados** — grep de imports sobre
  `core/`, `api/`, `ui/`, `app.py`: el único paquete de esa familia en uso es
  `langchain_text_splitters` (`ingest.py:200-210`).
- Ollama se habla por **HTTP crudo con `requests`**: `POST /api/embed` (`embed.py:194`),
  `POST /api/chat` (`generate.py:723,787`), `GET /api/tags` como preflight (`embed.py:132`).
- El comentario de `requirements.txt:4` ("OllamaEmbeddings adapter (Embedder port,
  core/embed.py)") es **falso hoy**: `embed.py:8-14` documenta por qué se abandonó el SDK
  (proxy a un runner interno con puerto efímero que rechaza conexión) a favor del endpoint
  HTTP estable.
- **Clasificación: drift de DECISIÓN, no de descuido técnico.** La decisión real (transporte
  HTTP directo, orquestación propia) está tomada, razonada y documentada en los docstrings de
  los adapters — pero ni SPEC §9 ni el manifiesto se corrigieron. El repo *declara* LangChain
  y *ejecuta* otra cosa. Arreglo barato: 4 líneas fuera de `requirements.txt` (con re-test) +
  1 línea en SPEC §9.

## 2. Delta del lenguaje ubicuo

**Símbolos reales sin glosar** (11 entradas, detalladas con anclas en
`02-arquitectura.md` §"Símbolos NO presentes"): `StreamedAnswer` (`engine.py:44-88`, el
concepto central del caso de uso vivo), `QueryHit` (`store.py:76-93`), `ABSTENTION_TEXT`
(`generate.py:71`), `strip_abstention_phrase` (`:354`), `LoadedPage`/`IngestedChunk`/
`IngestionResult` (`ingest.py:112,216,225`), `MessagePhase` (`useChat.ts:12`),
`hideTrailingAbstention`, `hadCandidates`, `EnginePreload`/`VerticalCorpus`,
`VerticalView`/`QueryRequest` (`api/schemas.py:16,22`), `Chunk.embedding` transiente
(`models.py:83-88`). El glosario dice "si un concepto no está aquí, no existe en el dominio"
(`UBIQUITOUS_LANGUAGE.md:5`) — regla incumplida por el propio flujo principal.

**Drift de entradas existentes**:

- **App** (`UBIQUITOUS_LANGUAGE.md:70`): sigue definida como "The Streamlit presentation
  layer" con identificador `app.py` — desactualizada tras la migración a React+FastAPI.
- **top_k** (`:52`): glosa el default **5**; ambos YAML operan con **6** (el default 5 de
  `models.py:316` sigue siendo cierto como *default*, pero la glosa sugiere el valor operativo).

## 3. Limitaciones conocidas — consolidadas (antes dispersas por puntero)

| ID | Descripción | Ancla | Impacto |
|---|---|---|---|
| **B2** | Preguntas en 1ª persona fuera de corpus (p.ej. "¿cuánto IRPF me toca pagar?"): el gate pasa por proximidad temática, el 7B responde con un decline en prosa ("Lo siento...") en vez de `ABSTENTION_TEXT`, a veces hasta con 1-3 chips técnicamente anclados → `is_abstention=false`, panel visible. Preexistente al bridge, no arreglable por prompt (3 arquitecturas probadas, 3/3 fallo idéntico). Fix candidato (prose-decline guard reutilizando el AnchorVerifier) descrito y **no construido** | `docs/KNOWN_LIMITATION_B2_first_person_out_of_corpus.md`; `DECISIONS_merged.md:125` | El anti-caso de la regla de oro 3 en un nicho estrecho (requiere las 3 condiciones a la vez). Límite de capacidad del 7B, no de la arquitectura; aceptado para el MVP |
| **L2** | Latencia de chips en modo `structured`: la pasada 2 es una segunda llamada LLM sobre el texto completo — los chips llegan con el `done` unos segundos DESPUÉS del último token | `api/routes/query.py:91-94`; `generate.py:513-514` | UX, mitigado: el front detecta el silencio y muestra "Verificando fuentes…" (`useChat.ts:22-31`); trade-off aceptado y documentado |
| **L3** | `pymupdf4llm` es AGPL-3.0 | `requirements.txt:10`; `DECISIONS_merged.md:21` | Bloquea el camino comercial sin sustituir el Loader; flaggeado desde el día 1, decisión pendiente antes del primer publish |
| **L4** | Legacy Streamlit congelado pero VIVO en el manifiesto: arrastra runtime pesado en cada install y conserva semántica vieja (ver §5) | `requirements.txt:14`; `ui/layout.py:96-105` | Riesgo de deriva si alguien lo reactiva; decisión pendiente: `requirements-legacy.txt` o retirada |
| **L5** | La frase de abstención vive copiada N veces: constante en core (`generate.py:71`) + 3 apariciones verbatim por YAML (`legal.yaml:93,121,129`; `health.yaml:93,112,120`). Sincronización manual — **ya mordió**: los dos últimos fixes de config (`e88ca64`, `a4740fa`) fueron exactamente esto (newline embebido rompía la igualdad byte-exacta) | `generate.py:71` vs `config/*.yaml` | La autoridad de abstención compara byte-exacto (`query.py:107`): un desajuste silencioso degrada abstenciones a respuestas normales. El front SÍ tiene fuente única (`/api/health` publica `abstention_text`, `health.py:48`); los YAML no |
| **L6** | Engine cacheado a vida del proceso (`@lru_cache`): editar un YAML exige reiniciar uvicorn | `api/dependencies.py:18` | Menor; deliberado (warm-up caro) y documentado en el docstring |
| **L7** | `CorpusStats` sin timestamp de ingesta | `models.py:283-285` | Ninguno; honestidad deliberada (Chroma no lo guarda de forma fiable; inventarlo sería mentir) |

## 4. Golden rules: violaciones y zonas grises

### El regex de ids BOE (`ingest.py:57`) — ¿provenance genérica o vertical filtrándose en core/?

`_OFFICIAL_ID_RE = re.compile(r"[A-Z]{2,}-[A-Z]-\d{4}-\d+")` con fallback a slug
(`derive_document_id`, `ingest.py:60-70`), autodocumentado como "generic provenance logic,
not vertical branching" (`:54-56`).

**Veredicto: zona gris defendible, no violación — pero con un sesgo que hay que admitir.**

- *Por qué NO es branching de vertical*: dispara por la **forma del filename**, jamás consulta
  el `Vertical`; un PDF del corpus health cuyo nombre llevara un id con ese patrón lo usaría
  igual; health simplemente nunca lo activa (sus guías caen al slug). No hay `if vertical ==`
  — es un default, no una rama.
- *La parte honesta*: el patrón está **modelado sobre el formato BOE** (`XXX-A-YYYY-NNNN`).
  Es conocimiento del dominio legal español embebido en `core/`, aunque esté expresado de
  forma agnóstica.
- *Defensa para la entrevista*: "es un **domain-informed default**, no lógica de vertical: el
  mecanismo (id oficial si el filename lo trae, slug si no) es genérico y está centralizado en
  la única fuente de verdad del `document_id`. La alternativa purista — un `id_patterns` en
  `VerticalConfig` — es la evolución correcta **cuando llegue un tercer vertical con otro
  esquema de ids**; para un MVP de 2 verticales sería configuración especulativa. Sé
  exactamente dónde está la costura y qué la haría necesaria."

### `except RagEngineError: pass` en el warm-up (`api/dependencies.py:30-33`)

Tensión literal con la regla 5 ("No silent `except: pass`"). Atenuantes: es específico
(`RagEngineError`, no `Exception`), documentado ("don't fail twice"), y el error re-aflora
idéntico y accionable en `check_health()` / la primera query. Gris aceptable; un `logger.warning`
lo sacaría del gris del todo.

### Lo que SÍ se cumple (verificado en `02-arquitectura.md`)

Regla 1 (core sin frameworks): grep limpio. Regla 2 (cero branching de vertical): cero
`if vertical ==` en `core/`. Regla 3: tipada e inescapable (`models.py:231-259`) — su hueco
residual es semántico, no de código (B2: un chip técnicamente válido sobre una frase que no
responde). Regla 4: por construcción (`models.py:299-302`). Regla 7: cero llamadas cloud.

## 5. Código muerto, parches y deuda visible

- **La trampa del legacy — `ui/layout.py:96-105`**: `_is_abstention_text` conserva la regla de
  abstención ANTIGUA (`text.strip().startswith(ABSTENTION_TEXT)`) que la API viva reemplazó
  explícitamente por autoridad resolved-state (`query.py:96-107` la documenta como "the old
  startswith"). Quien lea el legacy aprende la semántica equivocada; quien lo reactive obtiene
  un comportamiento de abstención distinto al de producción. Es el argumento más fuerte para
  retirar (o al menos rotular) `ui/`+`app.py`.
- **TODOs fósiles**: `ingest.py:347` ("a dedicated config loader will own YAML parsing" —
  módulo 9 nunca construido: `load_vertical_config` sigue viviendo en el módulo de ingesta y
  **la API viva lo importa de ahí**, `dependencies.py:14`); `ui/components/sources_panel.py:75`
  y `ui/theme.py:202` (TODOs sobre marcadores `[n]` inline — un plan REEMPLAZADO por el
  enfoque parts/anchoring del camino vivo; segunda trampa para el lector del legacy).
- **Dependencias fantasma**: `langchain`, `langchain-community`, `langchain-ollama`, `ollama`
  — 4 paquetes eliminables con re-test (§1, fila §9). Más `streamlit>=1.40` arrastrado solo
  por el congelador.
- **Comentario mentiroso**: `requirements.txt:4` (detallado en §1).
- **Sin `pyproject.toml`**: solo `requirements.txt` — funcional, pero fuera del estándar
  actual de empaquetado.

## 6. Cobertura de tests: ¿123 tests para qué motor?

Distribución real (grep `def test_`): generate 39, store 18, engine 15, ingest 13, retrieve 12,
embed 12, anchor_verifier 7, api_query 5, api_health 2. **Veredicto: el camino nuevo SÍ está
cubierto a nivel unitario — el hueco está en la integración HTTP/streaming real y en el
frontend, que tiene CERO tests.**

**Cubierto (camino nuevo):**

- Relevance gate: 4 tests dedicados (`test_retrieve.py:178-220`) + round-trip de metadata.
- Strip simétrico: 7 tests (`test_generate.py:353-407`), incluida la abstención pura.
- Etapa 2 (anchoring): validación JSON fail-safe, interleaving con dedup remap, degradación a
  sin-chips, modo `off`, `format:"json"` + temp 0 (`test_generate.py:440-548`).
- Etapa 3 (AnchorVerifier): 7 tests — repair/keep/floor/sibling y las degradaciones aditivas
  (`test_anchor_verifier.py`).
- Contrato SSE a nivel de eventos: orden `citations→token*→done`, resolved-state (leading
  abstención con contenido ≠ abstención; soft-decline puro = abstención), forma del done
  (`test_api_query.py`, 5 tests).
- Seam de streaming del engine: `StreamedAnswer`, citations fijas, delegación de
  `resolve_parts` (`test_engine.py:250-361`).

**NO cubierto (concreto):**

- **Frontend: cero tests.** `frontend/package.json` no tiene script `test` ni framework alguno
  (solo oxlint). Sin red de seguridad: el parser SSE a mano (`dispatchFrame`,
  `client.ts:208-235`), la máquina de estados de `useChat` (watchdog 700ms, abort al cambiar
  vertical), `splitCitations`, `hideTrailingAbstention`, `renderParts`. Playwright está
  declarado (`requirements-dev.txt:6`) pero no hay specs e2e en el repo.
- **El evento `error` mid-stream** (`query.py:65-76`): ningún test lanza un `RagEngineError`
  a mitad de iteración del stream. El mapeo `http_error_for` en ese camino está sin ejercitar.
- **La ruta HTTP real del query**: los 5 tests llaman `_stream_events` directamente (decisión
  documentada, `test_api_query.py:3-7`); el handler `query()` — retrieval eager pre-SSE y
  errores pre-stream como JSON (`query.py:23-32`) — no se ejercita por TestClient. Solo
  `/api/health` tiene test HTTP de verdad.
- **`routes/verticals.py`: sin fichero de test** — la proyección `VerticalView` (que oculta
  `system_prompt`/`corpus_path`) no está pinneada.
- **El cableado etapa 3 dentro de `_resolve_parts`** (`generate.py:588-596`): `verify_anchors`
  solo se testea en aislamiento; los tests structured usan Generators sin embedder (donde la
  verificación degrada a no-op por diseño). **Una regresión que borrara la llamada de
  `:588` pasaría los 123 tests.** Es el pin de integración que falta.
- `main()` del CLI de ingesta y el orden del preflight (`ingest.py:386-430`): sin test.
- Legacy `ui/`+`app.py`: cero tests (coherente con "congelado", pero dicho).

## 7. Zonas "parche sobre idea anterior" (estratigrafía visible)

1. **Tres generaciones de autoridad de abstención conviven en el árbol**: startswith de prosa
   (legacy, `ui/layout.py:105`), citations-vacías provisional (evento `citations`,
   `query.py:52`), resolved-state autoritativa (`query.py:107`). Las dos vivas están
   correctamente jerarquizadas (provisional → autoritativa); la muerta es la trampa de §5.
2. **`load_vertical_config` en el módulo de ingesta**: herencia del build order (módulo 2
   necesitaba YAML antes de que existiera un módulo config); hoy la API de producción importa
   config… desde `core.ingest` (`dependencies.py:14`). El TODO de `ingest.py:347` lo confiesa.
3. **Streaming añadido sobre `generate()`**: el camino no-streaming se conserva como "tested
   fallback" (`generate.py:486-487`) — dos caminos paralelos con la misma lógica de negocio.
   Mitigado: la resolución final es única (`parts_for_text` / `_resolve_parts`,
   "THE single final-resolution site", `:560`).
4. **Huellas del enfoque de marcadores `[N]`**: reemplazado por clean-prose + anchoring, pero
   el glosario aún defiende `CitePart` contra "the echoed literal [N] template placeholder"
   (`UBIQUITOUS_LANGUAGE.md:36`) y los TODOs del legacy (`sources_panel.py:75`) siguen
   planeando los marcadores inline que ya nunca llegarán por esa vía.
5. **SPEC como foto de la v1**: §6 (mapa con Streamlit), §8 (FastAPI+frontend como futuro ya
   ejecutado) y §9 (LangChain) describen el proyecto de antes de la migración. El código ganó;
   el contrato no se re-firmó.
