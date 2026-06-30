# PROGRESS — Citara

> Bitácora de seguimiento del proyecto. Estado real, decisiones, problemas resueltos
> y siguientes pasos. Se actualiza al cerrar cada hito. Alimenta luego `DECISIONS.md`
> y el `README.md`.

Última actualización: 2026-06-30

---

## Estado global

| Capa | Módulo | Estado | Tests |
|------|--------|--------|-------|
| Dominio | `core/models.py` | ✅ Hecho | — |
| Dominio | `core/ingest.py` | ✅ Hecho (+ persistencia cableada) | 11 |
| Dominio | `core/embed.py` | ✅ Hecho (HTTP directo a `/api/embed`) | — |
| Dominio | `core/store.py` | ✅ Hecho | 13 |
| Dominio | `core/retrieve.py` | ✅ Hecho | 8 |
| Dominio | `core/generate.py` | ✅ Hecho (⚠️ aún usa `ChatOllama`, ver riesgos) | — |
| Aplicación | `core/engine.py` | ✅ Hecho | — |
| Presentación | `app.py` | ✅ Hecho (sin validar en vivo) | n/a (UI) |
| Config | `config/health.yaml` | ✅ Hecho (prompt revisado) | — |
| Config | `config/legal.yaml` | ⬜ Pendiente | — |

**Tests totales: 60 verdes.** Suite sin dependencias vivas (mocks de Ollama/Chroma).

**Repo:** GitHub `AxelAxx/Citara` — privado hasta fijar licencia.

---

## Hito actual

Primera ejecución real end-to-end. Embedding contra Ollama **verificado en vivo**
(`embed_query` devuelve vector de 1024 dims, idéntico al de `curl`). Siguiente:
ingesta real del corpus health → `streamlit run app.py`.

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
  - **Diagnóstico:** aislé el servidor con `curl`/`Invoke-RestMethod` a `/api/embed` → **funcionaba** (vector 1024 dims en 2s). Luego el SDK `ollama` vía `langchain-ollama` → fallaba. Conclusión: el problema es la capa cliente (SDK bleeding-edge vs servidor estable), no Ollama ni mi código. El pipeline parseaba y troceaba bien; reventaba solo en la llamada del SDK.
  - **Intentos descartados:** bajar `langchain-ollama` (no bastó, el culpable era el SDK `ollama` de debajo). Evité seguir bajando versiones a ciegas.
  - **Solución:** reimplementar `OllamaEmbedder` para hablar **directamente** a `POST /api/embed` con `requests`, eliminando el SDK del camino de embedding. El puerto `Embedder` no cambió; solo la implementación del adapter. Más robusto (no acoplado a versiones del SDK) y verificado en vivo.
  - **Narrativa de entrevista:** "aislé con curl que el servidor funcionaba, deduje que era la capa cliente, y reimplementé el adapter contra el endpoint HTTP estable en vez de pelear con versiones."
- **B-04 — Confusión de terminales / venv.** Varios fallos por correr `python` sin el venv activado (caía al stub de Microsoft Store). Regla: confirmar `(Citara)` en el prompt antes de cualquier comando `python`.

---

## Riesgos abiertos / a vigilar

- **`generate.py` usa `ChatOllama`** de langchain-ollama. Cuando se generen respuestas con Qwen, puede saltar **el mismo `/tokenize`** que el embedding (B-03). Receta lista: reimplementar el `Generator` contra `/api/chat` por HTTP directo si pasa.
- **Posible código muerto en `embed.py`** tras el merge del fix B-03 (restos del adapter langchain en `_embed`). Verificar y limpiar.
- **Rendimiento en Pascal:** la RTX 1080 va más lenta que GPUs modernas; usable para chat, no de vértigo.
- **Versiones flotantes** en `requirements.txt`: fijar con `==` antes de publicar.

---

## Siguientes pasos (orden)

1. ⏳ **Ingesta real** `python -m core.ingest --vertical health` → confirmar `N vectors persisted` y `chroma_db/` creado.
2. **Commit** del fix de embed (`fix(embed): call Ollama /api/embed over HTTP directly [FR4]`).
3. **Validar AC1**: segunda ingesta → mismo nº de chunks, sin duplicar (idempotencia real).
4. **`streamlit run app.py`** → primera respuesta en vivo. Validar AC2 (respuesta + citas) y AC3 (abstención).
   - Tener listas preguntas de prueba: 2-3 dentro del corpus + 1 fuera (para la abstención).
   - Si Qwen peta con `/tokenize` → aplicar receta de `/api/chat` directo.
5. **Iterar el `system_prompt`** de health con preguntas reales (aquí está el valor del proyecto).
6. **`config/legal.yaml`** + corpus legal → demostrar G1 (mismo motor, 2 verticales, cero diff en `core/`).
7. **Auto-ingesta en la UI** (D-05): botón / auto-detección con loading.
8. **Pulido final:** UI sobre Streamlit, mascota (icono), README + GIF de demo, `DECISIONS.md`, licencia AGPL, fijar versiones, repo público.

---

## Criterios de aceptación — checklist

- [ ] AC1 — ingesta persiste + idempotente (pendiente de validar en vivo)
- [ ] AC2 — respuesta con ≥1 cita correcta (doc + página)
- [ ] AC3 — abstención ante pregunta fuera de corpus
- [ ] AC4 — cambio de vertical sin diff en `core/` (requiere legal.yaml)
- [ ] AC5 — modo avión: sin llamadas externas
- [x] AC6 — pytest verde (Chunker, Citation, Retriever con mocks) — **60 tests**
- [x] AC7 — errores accionables (Ollama down / modelo sin pull / corpus vacío) — verificado en vivo
- [ ] AC8 — README reproducible + GIF + diagrama
