# 00 — Resumen ejecutivo de la auditoría

> Auditoría read-only de ingeniería inversa sobre `2bd0ded`. El código es la fuente de verdad;
> SPEC/CLAUDE/glosario son la línea base para medir drift.

**Qué es Citara hoy**: un motor RAG local y gratuito (`RagEngine` único, verticales por YAML)
con dos demos en español (legal/BOE y health/GuíaSalud), servido por una SPA React sobre una
API FastAPI con SSE. El `core/` sigue limpio de frameworks y de lógica de vertical; la
Presentation original (Streamlit) quedó congelada como red de seguridad. El sistema real
supera al SPEC en su punto más difícil — citación inline verificada y abstención por estado —
y el drift que existe es mayoritariamente **documental**, no de código.

## Los cinco informes

1. [00-inventario.md](./00-inventario.md) — estructura real, manifiestos, puntos de entrada
   (sin Docker; tres procesos localhost).
2. [01-stack.md](./01-stack.md) — stack en uso vs **declarado-pero-no-cableado** (LangChain,
   SDK ollama); el caso streamlit.
3. [02-arquitectura.md](./02-arquitectura.md) — capas vivas y verificación de las golden rules
   módulo a módulo; los símbolos sin glosar.
4. [03-flujo.md](./03-flujo.md) — el caso de uso completo: relevance gate, generación en TRES
   etapas (respuesta → anchoring JSON temp 0 → AnchorVerifier), abstención real de hoy.
5. [04-diagramas.md](./04-diagramas.md) — los 5 diagramas Mermaid de presentación (arquitectura,
   secuencia SSE, dominio, ingesta, máquina de decisión citación/abstención).
6. [05-diagnostico.md](./05-diagnostico.md) — drift FR1..FR11 + §9, delta de glosario,
   limitaciones consolidadas, zonas grises, cobertura de tests.

## Los 5 puntos que destacaría en una entrevista

1. **Grounding-first de verdad**: las citations se emiten por SSE ANTES del primer token —
   derivan del retrieval, no del LLM, así que el modelo nunca decide cuáles son sus fuentes
   (`engine.py:236-237`, `query.py:47-56`). Y la regla 3 no es una convención: está tipada —
   un Answer sin citas o un chip fuera de rango no compilan (`models.py:231-259`).
2. **"The LLM proposes, the deterministic guard disposes"**: el AnchorVerifier repara o
   descarta chips por margen relativo de coseno, con umbrales calibrados por medición (n=40 +
   smoke en vivo) y un invariante limpio: la prosa jamás se modifica, solo los chips
   (`generate.py:213-306`; diagrama 5 de `04-diagramas.md`).
3. **La migración Streamlit→React/FastAPI costó cero cambios en `core/`**: la frontera limpia
   (regla 1) pagó dividendos medibles — mismo `RagEngine`, misma fachada, y el legacy quedó
   congelado sin tocar el motor. Es el argumento empírico de la arquitectura, no el teórico.
4. **Abstención por estado resuelto, no por adivinar prosa** — y honestidad con su límite: B2
   (declive en prosa del 7B ante preguntas personales fuera de corpus) está medido con método
   (baseline antes de atribuir, una variable por experimento), documentado como límite de
   capacidad del modelo. El caso legal (IRPF) lo **resuelve el `AnswerabilityGate`** (`d96917c`): gate determinista S1 (margen relativo top-1, μ=0.075), scopeado por config —ON en legal, OFF en health— que fuerza la abstención byte-exacta aguas arriba de la autoridad resolved-state (verificado en vivo, B2-AC1). El residual health applied-general sigue **tracked, no construido** por diseño (no es fallo de suficiencia; ruta Stage 1 NLI, `SPEC_B2_v2.md` §10).
5. **Sé exactamente dónde mi repo miente**: LangChain declarado y jamás importado (drift de
   decisión, SPEC §9), FR11 describe una app que ya no es la viva, 11 símbolos por glosar, y
   una trampa conocida en el legacy (`ui/layout.py:105`). Auditarse a uno mismo y anclar cada
   hallazgo a `archivo:línea` es la habilidad que este documento demuestra.
