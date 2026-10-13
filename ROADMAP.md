# ROADMAP — Citara

> Visión de producto y decisiones futuras acordadas. Este documento es el **mapa**,
> no el backlog de trabajo activo (eso vive en `PROGRESS.md`). Nada de lo aquí
> descrito se implementa hasta que su versión arranque. Cada versión traza a los
> FR/AC/§8 de [`docs/SPEC.md`](./docs/SPEC.md) donde aplica.

> **Cierre (2026-10-13).** El proyecto queda **congelado en v0.4** como pieza de
> portfolio. V2 se resolvió de otra forma a la prevista aquí (migración a React +
> FastAPI sin tocar `core/`, en vez de modularizar Streamlit). V3, V4 y V5 **no se
> construyen**: se conservan como visión documentada, no como trabajo pendiente.

---

## V1 — MVP de portfolio (la versión de la entrevista / Walk) — **CONGELADA**

La versión que se enseña. Se congela tras la Walk: **no se toca** legal/health
como demos.

- Dos Verticales curadas y pre-ingestadas: **legal** (BOE) + **health** (GuíaSalud)
  — G1/FR10/AC4: mismo motor, cero diff en `core/` entre ambas.
- Motor completo: los 9 módulos del mapa (SPEC §6), **80 tests** verdes sin
  dependencias vivas (AC6/NFR4). Streaming token a token + warm-up del LLM +
  guardia dura de abstención (FR7–FR9, AC2/AC3).
- UI Fase 2 completa (FR11): welcome de dos pasos, chat con tema Citara, empty
  state con preguntas de ejemplo, loading card honesta, error cards accionables
  (AC7/NFR6), corpus panel read-only (FR5), conteos reales de documentos
  (welcome + sidebar), source fragment viewer lite (FR9, provenance `chunk_text`).
- AC1–AC7 validados. **AC8 (README + GIF) se enseña en persona** — el repo no se
  hace público en V1; README/licencia quedan para el camino post-Walk.

## V2 — Refactor de Presentación (primer trabajo post-V1; empieza YA tras la Walk)

Prerrequisito de todo lo demás (V3–V5 tocan la UI; sobre un `app.py` monolítico
de ~1700 líneas cada pieza nueva encarece). **Cero cambio de comportamiento:
mover, no reescribir.**

- Modularizar `app.py` en `ui/`: `theme.py`, `state.py`, `layout.py`,
  `screens/` (welcome, corpus), `components/` (sidebar, error_card, loading_card,
  sources_panel). Clean Architecture también en Presentación (NFR3: la capa de
  presentación sigue dependiendo solo de `core/`, nunca al revés).
- Separar bootstrap de UI: `app.py` delgado (composición) + `launcher.py` stub —
  el gancho del `.exe` de V5 (hoy `app.py` llama `main()` a nivel de módulo; el
  arranque del server debe poder vivir fuera de la app).
- Arreglar el bug de layout del empty-state descolocado (se corrige al extraer
  `ui/layout.py`, no antes).
- Lente BYOD en cada extracción: no cimentar el enum cerrado `Vertical` en código
  nuevo (ver V3) — la "colección activa" tenderá a ser un id `str` y los
  componentes iterarán una lista, no hardcodearán dos.

## V3 — Producto BYOD (bring your own documents)

**Visión:** el usuario final crea sus propias colecciones, sube sus PDFs, la app
los ingesta, todo local — ej.: un estudiante carga su temario de 1º de medicina
y pregunta sin internet ni tokens. Legal/health pasan a ser **colecciones de
ejemplo pre-cargadas** (onboarding: "prueba con estas o crea la tuya").

**Cambio conceptual clave:** `Vertical` (enum cerrado legal/health) →
`Collection` (entidad dinámica creada en runtime: nombre + carpeta de PDFs +
config). El motor vertical-agnóstico (G1) **ya es el cimiento**: `core/` de
retrieval/generación no se reescribe. Ojo con el choque de nombres: hoy
`Collection` en el lenguaje ubicuo es el namespace de ChromaDB — la nueva
entidad de dominio exige actualizar `UBIQUITOUS_LANGUAGE.md` antes de codificar
(regla de oro 6).

Piezas nuevas (cada una es un sub-proyecto, NO ahora):

- **Gestión de colecciones** (crear/renombrar/borrar/listar) → nueva entidad de
  dominio `Collection` + su persistencia. Toca `core/`. Generaliza FR10
  ("Vertical switching" → "Collection switching").
- **Ingesta desde la UI con progreso honesto**: drag&drop para pocos PDFs,
  selección de carpeta para volúmenes grandes (temario entero) → `ingest.py`
  emite progreso (callback/stream); hoy es CLI silenciosa (FR1–FR3). Es la
  fusión de #07 (upload) + #06-ingesta y de la decisión D-05 (auto-ingesta),
  que en V1 eran icebox/§8 y en producto pasan a **core del producto**.
- **Config por colección persistida**: hoy YAML estáticos (`config/*.yaml`,
  FR10) → generados en runtime; decidir YAML vs sqlite vs metadatos de Chroma.

Invariantes que sobreviven a BYOD: grounding + abstención + citas (G3/G4,
FR8–FR9), 100% local (G2/NFR1/AC5), mismo embedder ingesta/query (FR4).

## V4 — Selección / descarga de modelos (multi-modelo)

- El usuario elige un LLM más potente y la app lo descarga vía Ollama
  `/api/pull` con progreso (patrón de #05b, la pantalla de descarga). Aviso de
  requisitos: "este modelo requiere X VRAM / esta GPU" (NFR2 deja de ser un
  fijo y pasa a ser un check por modelo).
- **SALVAGUARDA DURA (regla de oro 4 / FR4):** el **LLM es cambiable en
  caliente**; el **Embedder solo con re-ingesta forzada** de la colección —
  cambiar el embedder sin re-ingestar rompe el retrieval **en silencio**
  (mismatch ingest/query). El selector debe distinguir ambos tipos y **bloquear**
  el cambio de embedder sin re-ingesta.

## V5 — Empaquetado `.exe` (distribución Windows)

- Empaquetar con `streamlit-desktop-app` (pywebview + PyInstaller): ventana
  nativa, un comando de build. **Requisito previo (V2):** `launcher.py` arranca
  el server; la UI queda sin lógica de arranque (`if __name__` /
  `streamlit.web.cli` fuera de la app).
- **Ollama + modelos NO caben en el `.exe`**: son dependencia externa del
  usuario. El primer arranque detecta si faltan y los resuelve/guía — las
  pantallas #05a (error accionable, ya construida: AC7/NFR6) + #05b (descarga,
  V4) **SON la solución de UX** a esto.
- Corpus: decidir si el `.exe` trae `chroma_db` pre-ingestado o ingesta en el
  primer arranque (conecta con la ingesta-desde-UI de V3).

## Deuda / licencia para "vendible"

- **PyMuPDF es AGPL contagioso** (ya flagged en SPEC §9 / NFR7 / D-06): para
  vender propietario, sustituir por `pdfplumber`/`pypdfium2` o comprar licencia
  Artifex. Anotado, no urgente — V1 publica AGPL-3.0 y no hay conflicto.
- Deuda ya registrada en `PROGRESS.md`:
  - `core/generate.py`: un corte de conexión a mitad de streaming escapa como
    excepción cruda de `requests` (`iter_lines`); envolver en `RagEngineError`.
  - Source fragment viewer (#09-lite): muestra artefactos de extracción
    (cabeceras markdown, `<sup>`); limpiar en #09-full o en ingesta.

---

## Trazabilidad rápida SPEC ↔ versiones

| Versión | SPEC |
|---------|------|
| V1 | G1–G6, FR1–FR11, AC1–AC7 (AC8 en persona) |
| V2 | NFR3 (Clean Architecture en Presentación); habilita V3–V5 |
| V3 | Generaliza FR10; promueve D-05 y §8 (ingesta UI) a producto; conserva FR4/FR8/FR9/NFR1 |
| V4 | FR4 (salvaguarda embedder), FR7 (LLM configurable), NFR2 (check VRAM por modelo) |
| V5 | Distribución (fuera del alcance del SPEC v1; §8 "Docker packaging" es el pariente); apoya en AC7/#05b |
