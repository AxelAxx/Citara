# 06 — Readiness end-to-end (pre-entrevista)

> Diagnóstico read-only sobre HEAD `8b38ed9` (rama `main`, working tree limpio, 2 commits
> por delante de `origin/main`: la tanda [dialogs] sin pushear). Solo ejecución y
> observación — cero fixes aplicados. Fecha: 2026-07-08.

## Tabla de estado

| # | Check | Estado | Detalle |
|---|---|---|---|
| 1a | `pytest -q` | 🟢 | **137 passed**, 0 failed, 0 skipped, 0.39s. (La expectativa "123" del checklist está desactualizada: +2 de `feat(retrieve)` 9632817, +12 de `feat(generate)` d96917c) |
| 1b | `npm run build` (tsc -b strict + vite) | 🟢 | Compila limpio; bundle 238.78 kB (72.89 kB gzip) |
| 1c | `npm run lint` (oxlint) | 🟢 | Exit 0; 5 warnings `react(only-export-components)` (fast-refresh), clase preexistente (`CorpusBlock.tsx:14`, `SourcesPanel.tsx:28` + los 2 ficheros nuevos de dialogs) |
| 2 | Integridad L5 (frase de abstención) | 🟢 | Byte-idéntica en las 6 apariciones (3+3), cero near-misses. Ver §2 |
| 3a | Ollama :11434 | 🟢 | `qwen2.5:7b` + `bge-m3` pulled; tras el warm-up ambos **100% GPU** (ctx 4096) |
| 3b | `GET /api/health` | 🟢 | `ok:true`, publica `abstention_text` coherente con core |
| 3c | Query legal answerable (a) | 🟢 | Respuesta sustantiva + 2 chips + panel |
| 3d | Query legal IRPF (b) | 🟢* | **Ya NO es prose-decline**: abstención byte-exacta — B2 CORREGIDO por el AnswerabilityGate (expectativa del checklist desactualizada, ver §3b) |
| 3e | Query legal out-of-domain (c) | 🟢 | Abstención byte-exacta, panel oculto (guard duro, n=0) |
| 3f | Query health answerable — **formulada por título** (d) | 🔴 | Abstiene reproduciblemente (2/2). Causa raíz: chunks-cabecera en la Collection health. Ver §3d — **el hallazgo real de este readiness** |
| 3g | Query health answerable — **formulada por contenido** (e) | 🟢 | Respuesta sustantiva + 1 chip + panel (pregunta sugerida del UI) |

## 1. Build / test

- `pytest -q`: **137 passed in 0.39s** (todo mockeado, sin red). Cero fallos, cero skips.
- Frontend: `tsc -b` (strict) + `vite build` → exit 0, 53 módulos, 615ms. `oxlint` → exit 0
  con los 5 warnings de fast-refresh listados arriba (estilo, no bloqueo; misma clase que ya
  emitían ficheros previos a la tanda dialogs).

## 2. Integridad de abstención (L5)

`ABSTENTION_TEXT` extraída de `core/generate.py:71`:
`"No encuentro esto en los documentos proporcionados."` (51 bytes, NFC-estable).

Comparación byte a byte + barrido de near-misses (colapso de whitespace, para cazar el
newline embebido que ya mordió en `e88ca64`/`a4740fa`):

| Fichero | Ocurrencias byte-idénticas | Near-misses |
|---|---|---|
| `config/legal.yaml` | 3 (líneas **105/133/141** — desplazadas desde ~93/121/129 por el bloque del gate añadido en d96917c) | 0 |
| `config/health.yaml` | 3 (líneas 93/112/120) | 0 |

**Idénticas explícitamente.** El invariante manual L5 está sano en este HEAD.

## 3. Smoke end-to-end

Tres procesos: Ollama :11434 (pre-existente), `uvicorn api.main:app --port 8000` (levantado
y bajado por este diagnóstico), y las queries directas contra la API (opción "directamente
contra la API" del checklist; el bundle de Vite ya quedó validado en 1b).

### (a) legal answerable — "¿Cuántos días de vacaciones tengo?" → 🟢

`is_abstention=false`, `suppress_citations=false`, **2 CiteParts**, 4 citations. Texto: art. 38
(convenio/contrato, mínimo 30 días naturales). Control de retrieval: top-1 = chunk de contenido
real del art. 38 (1911 chars), `BOE-A-2015-11430` p.39.

### (b) legal IRPF personal — "¿Cuánto IRPF me toca pagar este año?" → 🟢 con expectativa desactualizada

**El checklist espera el comportamiento de ANTES del fix B2.** Desde `d96917c`
(`feat(generate): deterministic AnswerabilityGate...`, ya en `origin/main`) este caso está
corregido: el 7B aún streamea el prose-decline (235 tokens observados), pero el gate lo
sobreescribe en resolución. Observado: `is_abstention=true`, `suppress_citations=true`,
**0 CiteParts**, texto final byte-exacto = `ABSTENTION_TEXT`, panel oculto. Contrato:
`docs/b2/SPEC_B2_v2.md` §4-5; μ=0.075 medido (`docs/b2/measurements/`). No es un bug ni una
regresión: es el fix funcionando; la nota "esperado HOY: prose-decline" del checklist quedó
obsoleta.

### (c) legal out-of-domain — "¿Quién ganó el Mundial de fútbol de 2022?" → 🟢

Retrieval devuelve 0 chunks bajo el umbral → guard duro (`core/generate.py:493-495`):
abstención byte-exacta, `suppress_citations=true`, panel oculto, 1 token (la frase entera,
sin generación real).

### (d) health answerable formulada POR TÍTULO → 🔴 el hallazgo principal

Query: *"¿Qué recomienda la guía de práctica clínica sobre el manejo de la diabetes tipo 2?"*
(= `health-plain-002` del set etiquetado, label `answerable`).

Observado, **reproducible 2/2**: `is_abstention=true`, `suppress_citations=true`, 0 CiteParts,
abstención byte-exacta — con **6 citations recuperadas** del documento correcto.

**Causa raíz (medida, no especulada)** — el retrieval devuelve el documento correcto pero
fragmentos sin contenido:

```
[1] diabetes-tipo-2 p.22  len=51  :: GUÍA DE PRÁCTICA CLÍNICA SOBRE DIABETES TIPO 2   25
[2] diabetes-tipo-2 p.18  len=51  :: GUÍA DE PRÁCTICA CLÍNICA SOBRE DIABETES TIPO 2   21
[3] diabetes-tipo-2 p.1   len=397 :: # Guía de Práctica Clínica sobre Diabetes tipo 2  ... NOTA ...
[4] diabetes-tipo-2 p.85  len=51  :: GUÍA DE PRÁCTICA CLÍNICA SOBRE DIABETES TIPO 2   95
[5] diabetes-tipo-2 p.11  len=51  :: GUÍA DE PRÁCTICA CLÍNICA SOBRE DIABETES TIPO 2   13
[6] diabetes-tipo-2 p.95  len=52  :: GUÍA DE PRÁCTICA CLÍNICA SOBRE DIABETES TIPO 2   105
```

5 de 6 chunks son **la cabecera corrida de página + número (51-52 chars)**: páginas cuyo texto
extraído es solo el running header. El embedding de esos mini-chunks es prácticamente el título
de la guía, y una query que contiene literalmente "guía de práctica clínica ... diabetes tipo 2"
es su vecino más próximo — ganan el top-k y desplazan al contenido real. El 7B, ante 6
fragmentos sin recomendación alguna, **abstiene honestamente** (regla de oro 3 funcionando: el
defecto NO es la abstención, es la calidad del retrieval en health).

Anclas del mecanismo (sin proponer fix, como pide el modo):
- `core/ingest.py:124-166` (`DocumentLoader`): salta páginas EN BLANCO, pero una página
  cabecera-solo no está en blanco (~51 chars) → entra al pipeline.
- `core/ingest.py:169-210` (`Chunker`): no existe longitud mínima de chunk — el fragmento de
  51 chars se embebe y persiste como cualquier otro.
- Colaterales a re-examinar cuando se aborde: la medición S1 de health
  (`docs/b2/measurements/b2_margins_20260708-105727Z.csv`, fila `health-plain-002`,
  `d_top1=0.612766`) probablemente midió distancias contra estos chunks-cabecera — otra razón
  candidata de por qué S1 no separó en health.

**Hallazgo secundario relacionado** (mismo smoke): las queries del set etiquetado que asumen
fichas técnicas AEMPS no encuentran ese contenido en el corpus real —
*"dosis habitual de paracetamol"* recupera 6 chunks de dosificación de **otros** fármacos
(pregabalina/ceftazidima/asma/reboxetina; ninguno de paracetamol) y *"efectos secundarios del
omeprazol"* recupera n=1. Los rationales de `docs/b2/b2_answerability_set.yaml:167-171` y
`:206-217` ("General posology exists in the AEMPS ficha tecnica") describen contenido que el
corpus GPC ingerido no parece contener → las labels `answerable` de `health-plain-001/003`
son dudosas PARA ESTE CORPUS. Defecto de set/corpus, no del motor.

### (e) health answerable formulada POR CONTENIDO → 🟢

Query: *"¿Qué valores de glucemia se utilizan para diagnosticar la diabetes tipo 2?"* (una de
las `example_questions` del UI, `config/health.yaml:70`). Observado: respuesta sustantiva
correcta (glucemia basal >126 mg/dl; TTOG 2h >200 mg/dl), `is_abstention=false`, **1 CitePart**,
panel visible. Las 4 preguntas sugeridas de health (`health.yaml:68-72`) están formuladas por
contenido clínico, no por título — **esquivan la trampa de las cabeceras**.

## 4. Lectura para la entrevista (hallazgos, sin fixes)

1. **Legal está sólido de punta a punta**: answerable con chips, B2 corregido con abstención
   determinista, out-of-domain con guard duro. Demo segura.
2. **Health responde bien por las preguntas sugeridas del UI** (formuladas por contenido) —
   pero **abstiene en preguntas formuladas "según la guía..."** por la contaminación de
   chunks-cabecera en la Collection (`data/health/` + pipeline de ingesta sin longitud mínima).
   Riesgo de demo: una pregunta libre del entrevistador con la palabra "guía" en ella.
3. Dos expectativas del checklist estaban desactualizadas respecto al árbol: la suite es de
   **137** tests (no 123) y B2 **ya no** produce prose-decline (gate d96917c). Ambas son
   mejoras, no regresiones.
4. El working tree lleva 2 commits [dialogs] locales sin pushear (`fa041bb`, `8b38ed9`) con su
   verificación en vivo aún pendiente.
