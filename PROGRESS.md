# PROGRESS — Citara

> Bitácora de seguimiento del proyecto. Estado real, decisiones, problemas resueltos
> y siguientes pasos. Se actualiza al cerrar cada hito. Alimenta luego `DECISIONS.md`
> y el `README.md`.

Última actualización: 2026-07-01

---

## Estado global

| Capa | Módulo | Estado | Tests |
|------|--------|--------|-------|
| Dominio | `core/models.py` | ✅ Hecho | — |
| Dominio | `core/ingest.py` | ✅ Hecho (+ persistencia cableada) | 11 |
| Dominio | `core/embed.py` | ✅ Hecho (HTTP directo a `/api/embed` + batching) | 12 |
| Dominio | `core/store.py` | ✅ Hecho | 13 |
| Dominio | `core/retrieve.py` | ✅ Hecho | 8 |
| Dominio | `core/generate.py` | ✅ Hecho (HTTP directo a `/api/chat`) | 12 |
| Aplicación | `core/engine.py` | ✅ Hecho | 7 |
| Presentación | `app.py` | ✅ Hecho (validado en vivo end-to-end) | n/a (UI) |
| Config | `config/health.yaml` | ✅ Hecho (validado en vivo sobre corpus real) | — |
| Config | `config/legal.yaml` | ✅ Hecho (corpus BOE; carga OK) | — |

**Tests totales: 69 verdes.** Suite sin dependencias vivas (mocks de Ollama/Chroma).

**Repo:** GitHub `AxelAxx/Citara` — privado hasta fijar licencia.

---

## Hito actual

**Motor validado end-to-end sobre corpus health real.** Ingesta idempotente
confirmada en vivo (AC1 ✅); Qwen responde en español citando guías reales
(AC2 ✅) y se abstiene ante preguntas fuera de corpus (AC3 ✅), todo por HTTP
directo contra Ollama (`/api/embed` + `/api/chat`, sin LangChain en la inferencia).
Vertical `legal` (BOE) ya integrada (G1 demostrable). Foco actual: pulido de UX
(streaming, warm-up, `top_k`) y preparación de la publicación.

---

## Mejoras de sesión — UX y calidad de recuperación (2026-07-01)

- **`top_k` afinado a 6** en ambos `config/*.yaml` (antes 8; el default del código
  sigue en 5, el override vive en config por golden rule 2). Equilibrio
  recall/precisión: con 8 se colaban chunks de documentos vecinos poco relevantes
  que degradaban respuestas centrales. **Verificado en vivo:** "tratamiento de
  primera línea para hipertensión" salía limpia con `top_k=6` pero confusa con 8
  (chunks de ictus colándose). Solo query-time, sin re-ingesta.
- **Streaming de respuestas (token a token).** Nuevo
  `RagEngine.answer_stream(query) -> StreamedAnswer` (orquestación en la capa de
  Aplicación: `retrieve` + `Generator.generate_stream`, con las citas derivadas del
  context por separado). La UI consume `st.write_stream` **por interfaz pública**,
  sin tocar internos del engine; `generate()` no-streaming queda intacto como
  fallback. Elimina la sensación de cuelgue en la lenta RTX 1080: el usuario ve la
  respuesta generarse en vez de mirar un spinner 1–2 min. Guardia de abstención
  preservada (context vacío cede la frase de abstención sin llamar al LLM).
- **Warm-up del LLM al arrancar.** `RagEngine.warm_up()` (público, delega en
  `Generator.warm_up()`) hace un `POST /api/chat` mínimo (`num_predict: 1` +
  `keep_alive: "10m"`) que fuerza la carga de Qwen (4.7 GB) en VRAM **sin generar
  respuesta real**. Se dispara dentro del `@st.cache_resource` → una sola vez por
  vertical, mientras el usuario lee la UI. Best-effort: si Ollama está caído no
  bloquea el arranque (el error accionable sigue surgiendo por `check_health`). La
  primera pregunta ya no paga el arranque en frío. Red de seguridad: spinner honesto
  "Generando la respuesta…" y, en la primera pregunta de la sesión, "Preparando el
  modelo…".

---

## Entorno verificado

- **Python:** 3.14.6 (venv `uv`). Nota: más nuevo que el 3.11+ del SPEC; funciona, pero documentar/fijar para reproducibilidad.
- **Ollama:** 0.30.11. Servidor sano (verificado por `curl` a `/api/embed`).
- **Modelos:** `qwen2.5:7b` (4.7 GB) y `bge-m3` (1.2 GB) descargados. Cargan en GPU (RTX 1080, Pascal, 8 GB VRAM).
- **Git:** 2.54.0.
- **Corpus health:** 10 PDFs de GuíaSalud en `data/health/` (~36 MB, nombres kebab-case → `document_id` legibles). Temas: diabetes, hipertensión, asma, EPOC, depresión, ansiedad, embarazo/parto, cribado cáncer colorrectal, ictus, insuficiencia cardíaca.

### Versiones de paquetes fijadas tras resolver el blocker de Ollama
- `langchain-ollama == 0.2.3` (bajado desde 1.1.0)
- `langchain-core == 0.3.86` (arrastrado por el downgrade)
- `ollama == 0.6.2` (el SDK; **ya no se usa para embedding**, ver decisión D-04)
- Resto de langchain (`langchain 1.3.11`, `text-splitters 1.1.2`) en 1.x — convive, tests verdes.

> ⚠️ Fijar estas versiones con `==` en `requirements.txt` antes de publicar. Un clon con versiones flotantes reproduce los blockers de abajo.

---

## Decisiones clave (resumen; el rationale completo va a DECISIONS.md)

- **D-01 — Persistencia en el driver, no en `RagEngine`.** El bucle embed→upsert vive en `core/ingest.py::persist()` con `Embedder` y `VectorStore` inyectados. Ingesta (offline/batch) y query (online/cacheada) son ciclos de vida distintos; meter `index()` en `RagEngine` los acoplaría.
- **D-02 — Citas solo en el `SourcesPanel`.** Derivadas de `ChunkMetadata` vía `Citation.from_metadata`, nunca inline en el texto del LLM. Más fiable (no depende de que el LLM cite bien).
- **D-03 — Abstención por guardia dura + prompt.** Context vacío → cortocircuito determinista en código (testeable sin LLM, cubre AC3). Frase **unificada** código↔YAML: `"No encuentro esto en los documentos proporcionados."`
- **D-04 — Embedding por HTTP directo a `/api/embed`, sin el SDK `ollama`.** Ver blocker B-03.
- **D-05 — Auto-ingesta desde la UI (pendiente de montar).** La app embebe **solo si la Collection está vacía** (o vía botón), con loading honesto. Nunca en cada arranque (ChromaDB persiste justamente para no re-embeber). Se monta DESPUÉS de validar la ingesta cruda por terminal.
- **D-06 — Licencia: AGPL-3.0 (decidida, pendiente de aplicar).** Open source real para portfolio + puerta abierta a comercializar. PyMuPDF es AGPL contagioso → sin conflicto al publicar AGPL. Fijar antes de hacer el repo público.

---

## Blockers resueltos (historial — material para entrevista)

- **B-01 — `core/models.py` "fantasma" con dataclasses.** Claude Code generó una primera versión divergente del diseño. Resuelto reescribiendo al spec + `extra="forbid"` en todos los value objects para que la deriva silenciosa de campos falle ruidosa.
- **B-02 — La ingesta no persistía.** El CLI producía `IngestedChunk` pero nunca embebía ni hacía upsert (cableado diferido y olvidado). Resuelto con `persist()` inyectado (D-01). Cierra AC1 de verdad.
- **B-03 — `/tokenize` connection refused en embedding.** ⭐ El bueno.
  - **Síntoma:** `python -m core.ingest` petaba en `embed_documents` con `Post http://127.0.0.1:<puerto-efímero>/tokenize: connection refused`.
  - **Diagnóstico (corregido):** la primera hipótesis fue "capa cliente": aislé el servidor con `curl`/`Invoke-RestMethod` a `/api/embed` → **funcionaba** (vector 1024 dims en 2s), y el SDK `ollama` vía `langchain-ollama` fallaba, así que migré a HTTP directo. Pero seguía petando. La **causa raíz real era el VOLUMEN del batch**: la ingesta llamaba `embed_documents` con los **4462 chunks del corpus en una sola petición**, y Ollama, ante un batch masivo, arranca un runner de tokenización interno (`/tokenize` en puerto efímero) que se cae bajo esa carga. No era el SDK: era mandar todo de golpe.
  - **Aislamiento de la causa:** 1-2 textos por `/api/embed` funcionan; un único texto de 2000 tokens funciona; **solo** falla el batch entero desde el código. Eso descartó el modelo, el contenido y el endpoint, y señaló al tamaño de la petición.
  - **Solución:** trocear `embed_documents` en **lotes pequeños (`_EMBED_BATCH_SIZE = 16`)**, un `POST /api/embed` por lote, concatenando los vectores en orden global. Quedó además el HTTP directo (en vez del SDK), que es robusto frente a versiones; pero **el fix que destrabó la ingesta fue el batching**, no el cambio de cliente. El puerto `Embedder` no cambió.
  - **Narrativa de entrevista:** "el primer diagnóstico (culpar al SDK) era incompleto; bisecté por tamaño de petición —1 texto ok, 2000 tokens ok, 4462 de golpe no— y vi que el verdadero detonante era el volumen saturando el runner de tokenización. Lo resolví troceando en lotes, no peleando con versiones. Lección: confirmar la causa raíz por bisección antes de dar por cerrado el diagnóstico."
- **B-04 — Confusión de terminales / venv.** Varios fallos por correr `python` sin el venv activado (caía al stub de Microsoft Store). Regla: confirmar `(Citara)` en el prompt antes de cualquier comando `python`.
- **B-05 — `AttributeError: module 'langchain' has no attribute 'verbose'` en generación.**
  - **Síntoma:** al generar con Qwen, `ChatOllama` reventaba con `AttributeError` sobre `langchain.verbose`.
  - **Diagnóstico:** efecto colateral del downgrade del embedding (B-03). Al bajar `langchain-core` a 0.3.x quedó **descompasado** con `langchain 1.3.11`; `ChatOllama` lee `langchain.verbose`, que **ya no existe en langchain 1.x**. Choque de versiones de LangChain, no un fallo de Ollama.
  - **Solución:** eliminar `ChatOllama` y hablar `POST /api/chat` por HTTP directo con `requests` (coherente con B-03 en `embed.py`). **`core/` ya NO depende de LangChain para inferencia** — solo de `langchain-text-splitters` para el `Chunker`. Menos superficie de versiones volátiles.

---

## Riesgos abiertos / a vigilar

- ✅ ~~**`generate.py` usa `ChatOllama`**~~ **RESUELTO (B-05).** `Generator` reimplementado contra `/api/chat` por HTTP directo; LangChain fuera del camino de inferencia.
- ✅ ~~**Posible código muerto en `embed.py`**~~ **RESUELTO.** El adapter quedó limpio tras los fixes B-03 (HTTP directo + batching); sin restos del cliente langchain.
- ✅ ~~**Streaming de respuestas (mejora futura)**~~ **HECHO (2026-07-01).** `answer_stream` + `st.write_stream` token a token, y warm-up del LLM al arrancar (ver *Mejoras de sesión*). La lentitud de la RTX 1080 (Pascal) sigue siendo real, pero ya no se percibe como cuelgue y la primera pregunta no paga el arranque en frío.
- **Versiones flotantes** en `requirements.txt`: fijar con `==` antes de publicar.

---

## Siguientes pasos (orden)

1. ✅ **Ingesta real** `python -m core.ingest --vertical health` → vectores persistidos, `chroma_db/` creado.
2. ✅ **Commit** del fix de embed (HTTP directo `/api/embed` + batching).
3. ✅ **AC1 validado**: segunda ingesta idempotente (mismo nº de chunks, sin duplicar).
4. ✅ **`streamlit run app.py`** → respuesta en vivo. AC2 (respuesta + citas) y AC3 (abstención) validados.
5. ⏳ **Iterar el `system_prompt`** de health con preguntas reales (aquí está el valor del proyecto).
6. ✅ **`config/legal.yaml`** + corpus legal (BOE) integrado → G1 demostrable (mismo motor, 2 verticales, cero diff en `core/`). Falta validar el switch en vivo para cerrar AC4.
7. **Auto-ingesta en la UI** (D-05): botón / auto-detección con loading.
8. **Pulido final (UX + publicación):**
   - **Splash screen** de arranque: esconder el warm-up del LLM tras la marca/logo, para que el precalentado ocurra bajo una pantalla de bienvenida en vez de percibirse como espera.
   - **Diseño de UI** (hecho con Claude Design; **pendiente de implementar** en Streamlit) + mascota/icono.
   - **README** reproducible + **GIF** de demo + diagrama.
   - **`DECISIONS.md`**: volcar D-01…D-06 con el rationale completo.
   - **Licencia AGPL-3.0** (D-06) y **fijar versiones** con `==` en `requirements.txt`.
   - **Repo público** (GitHub `AxelAxx/Citara`), tras aplicar licencia y fijar versiones.

---

## Deuda técnica (no bloqueante)

- **core/generate.py**: streaming mid-flight connection drop escapes as raw requests
  exception (`iter_lines`); wrap in `RagEngineError`. Deferred — core/ work, not UI.
  (Descubierto verificando #05a: con tokens ya fluyendo, un corte de Ollama saldría
  como traceback crudo en vez de la error card.)
- **source fragment viewer (#09-lite)**: shows raw extraction artifacts (markdown
  headers, `<sup>` tags); clean for display in #09-full or at ingest, not the lite
  viewer.

---

## Criterios de aceptación — checklist

- [x] AC1 — ingesta persiste + idempotente — **validado en vivo sobre corpus health real**
- [x] AC2 — respuesta con ≥1 cita correcta (doc + página) — **validado en vivo (Qwen cita guías reales en español)**
- [x] AC3 — abstención ante pregunta fuera de corpus — **validado en vivo**
- [ ] AC4 — cambio de vertical sin diff en `core/` — legal.yaml integrado; **pendiente validar el switch en vivo**
- [x] AC5 — modo avión: sin llamadas externas — **validado en vivo (2026-07-01)**
- [x] AC6 — pytest verde (Chunker, Citation, Retriever con mocks) — **69 tests**
- [x] AC7 — errores accionables (Ollama down / modelo sin pull / corpus vacío) — verificado en vivo
- [ ] AC8 — README reproducible + GIF + diagrama
