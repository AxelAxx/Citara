# 04 — Diagramas de presentación

> Auditoría read-only sobre `2bd0ded`. Cinco diagramas Mermaid autoexplicativos, anclados al
> código. Sin ER clásico: no hay BD relacional — la persistencia es ChromaDB (vectores +
> metadata plana).

## 1. Arquitectura de alto nivel (versión canónica)

```mermaid
---
title: Citara — arquitectura viva (dependencias hacia dentro)
---
flowchart LR
  subgraph Frontend["frontend/ (React 19 + Vite)"]
    UI["Chat.tsx / Welcome.tsx"]
    HOOKS["hooks: useChat, useVerticals,<br/>useEngineReady, useHealth"]
    CLIENT["api/client.ts<br/>(cliente tipado + SSE a mano)"]
    UI --> HOOKS --> CLIENT
  end

  subgraph API["api/ (FastAPI)"]
    ROUTES["routes: health, verticals, query"]
    DEPS["dependencies.py<br/>get_engine lru_cache por vertical"]
    ERRORS["errors.py<br/>RagEngineError a HTTP"]
    ROUTES --> DEPS
  end

  subgraph CORE["core/ (framework-free)"]
    ENGINE["engine.py: RagEngine<br/>(composition root)"]
    RETR["retrieve.py: Retriever<br/>+ relevance gate"]
    GEN["generate.py: Generator<br/>3 etapas + AnchorVerifier"]
    STORE["store.py: VectorStore<br/>(adapter Chroma)"]
    EMB["embed.py: OllamaEmbedder<br/>(adapter HTTP)"]
    MODELS["models.py: value objects<br/>pydantic frozen"]
    ENGINE --> RETR --> STORE
    ENGINE --> GEN
    RETR --> EMB
    GEN --> EMB
  end

  CONFIG[("config/*.yaml<br/>VerticalConfig")]
  OLLAMA[("Ollama :11434<br/>qwen2.5:7b + bge-m3")]
  CHROMA[("./chroma_db<br/>1 Collection por vertical")]

  CLIENT -- "HTTP + SSE :8000" --> ROUTES
  DEPS --> ENGINE
  CONFIG --> ENGINE
  EMB -- "POST /api/embed" --> OLLAMA
  GEN -- "POST /api/chat" --> OLLAMA
  STORE --> CHROMA

  subgraph LEGACY["LEGACY — CONGELADO (red de seguridad de la migración)"]
    STREAMLIT["app.py + ui/ (Streamlit)<br/>NO recibe mantenimiento"]
  end
```

Tres capas vivas con dependencias apuntando hacia dentro: React consume la API por HTTP+SSE, la
API resuelve un `RagEngine` cacheado por vertical (`api/dependencies.py:18`) y `core/` aísla los
adapters concretos en módulos designados (`store.py:318`, `embed.py`, `generate.py`). El bloque
Streamlit está deliberadamente sin flechas: congelado, no participa del flujo vivo
(`requirements.txt:16`).

## 2. Secuencia del caso de uso principal (grounding-first)

```mermaid
---
title: Query a respuesta con citas — orden SSE real
---
sequenceDiagram
  participant U as Usuario
  participant FE as React (useChat)
  participant API as FastAPI /query (SSE)
  participant RET as Retriever
  participant GEN as Generator
  participant OLL as Ollama

  U->>FE: escribe la Query
  FE->>API: POST /api/verticals/{id}/query {query}
  API->>RET: retrieve(query, top_k, threshold)
  RET->>OLL: POST /api/embed (bge-m3)
  RET->>RET: Chroma top-k + relevance gate
  RET-->>API: RetrievedContext (0..k chunks)
  rect rgb(230, 240, 255)
    Note over API,FE: GROUNDING-FIRST: las citations se emiten ANTES<br/>de generar — derivan del retrieval, no del LLM
    API-->>FE: event citations
  end
  API->>GEN: generate_stream_parts (ETAPA 1)
  GEN->>OLL: POST /api/chat stream (qwen2.5:7b)
  loop cada fragmento
    API-->>FE: event token {text}
  end
  Note over FE: silencio > 700ms: fase "anchoring"<br/>(Verificando fuentes...)
  API->>GEN: resolve_parts(full_text)
  GEN->>GEN: strip simetrico de abstencion + split de frases
  GEN->>OLL: POST /api/chat format json temp 0 (ETAPA 2 anchoring)
  GEN->>OLL: POST /api/embed por frase anclada (ETAPA 3 AnchorVerifier)
  GEN-->>API: (final_text, parts verificados)
  rect rgb(230, 255, 235)
    Note over API,FE: el done NO lleva campo de texto:<br/>el cliente reensambla desde los parts
    API-->>FE: event done {is_abstention, suppress_citations, parts}
  end
  FE->>FE: renderParts: TextParts + CiteChips
  FE->>U: respuesta con chips inline + SourcesPanel
```

El orden SSE es estricto: `citations → token* → done | error` (`api/routes/query.py:35-124`).
Las citations se conocen en cuanto retrieval retorna (`engine.py:236-237`) — el LLM no puede
inventar fuentes porque nunca decide cuáles son. El `done` transporta solo parts tipados
(`query.py:109-124`); unir sus TextParts reproduce el texto final byte a byte.

## 3. Value objects del dominio (classDiagram)

```mermaid
---
title: core/models.py + los dos agregados sin glosar
---
classDiagram
  class Chunk {
    +text: str
    +metadata: ChunkMetadata
    +embedding: Embedding | None
  }
  class ChunkMetadata {
    +document_id: str
    +page: int
    +section: str | None
    +vertical: Vertical | None
    +source_path: Path | None
  }
  class Citation {
    +document_id: str
    +page: int
    +section: str | None
    +chunk_text: str
    +from_chunk(chunk)$ Citation
  }
  class Answer {
    +text: str
    +citations: List~Citation~
    +is_abstention: bool
    +parts: List~AnswerPart~
    +abstention(text)$ Answer
  }
  class TextPart {
    +kind = "text"
    +text: str
  }
  class CitePart {
    +kind = "cite"
    +n: int
  }
  class AnswerPart {
    <<union discriminada>>
  }
  class RetrievedContext {
    <<alias de tipo>>
    list~Chunk~
  }
  class CiteAnchor {
    +sentence_index: int
    +chunk_index: int
  }
  class VerticalConfig {
    +vertical: Vertical
    +collection_name: str
    +system_prompt: str
    +embedding_model: str
    +llm_model: str
    +top_k: int = 5
    +relevance_threshold: float
    +inline_citation_mode: structured|off
    +anchor_repair_margin: float = 0.05
    +anchor_support_floor: float = 0.50
    +document_titles: dict
  }
  class StreamedAnswer {
    <<NO GLOSADO>>
    +part_stream: Iterator~AnswerPart~
    +citations: List~Citation~
    +resolve_parts(full_text) tuple
    +text_stream: Iterator~str~
  }
  class QueryHit {
    <<NO GLOSADO>>
    +id: str
    +text: str
    +metadata: dict
    +distance: float | None
    +embedding: Embedding | None
  }

  Chunk *-- ChunkMetadata
  RetrievedContext o-- Chunk : 0..k ordenados
  Answer o-- Citation
  Answer o-- AnswerPart
  AnswerPart <|-- TextPart
  AnswerPart <|-- CitePart
  Citation ..> Chunk : from_chunk
  StreamedAnswer o-- Citation
  StreamedAnswer ..> AnswerPart : part_stream
  QueryHit ..> Chunk : rebuild en retrieve.py

  note for Answer "Invariantes TIPADAS models.py 231-259:<br/>no-abstencion exige >= 1 Citation;<br/>CitePart.n siempre en rango 1..len(citations)"
  note for StreamedAnswer "engine.py 44-88 - concepto central<br/>del caso de uso vivo, ausente<br/>de UBIQUITOUS_LANGUAGE.md"
  note for QueryHit "store.py 76-93 - frontera cruda<br/>del VectorStore, sin glosar"
```

`RetrievedContext` es un alias de tipo (`list[Chunk]`, `models.py:102`) — no una clase; se
representa con su estereotipo para dejarlo explícito. Los dos
estereotipos `NO GLOSADO` marcan la deuda de glosario detectada en `02-arquitectura.md`;
`Chunk.embedding` es transiente (poblado solo en retrieval, para el AnchorVerifier,
`models.py:83-89`).

## 4. Ingesta offline

```mermaid
---
title: Pipeline de ingesta (python -m core.ingest --vertical v)
---
flowchart LR
  PDF["data/vertical/*.pdf<br/>10 BOE + 10 GuiaSalud"] --> LOAD["DocumentLoader<br/>pymupdf4llm page_chunks=True<br/>paginas 1-based"]
  LOAD --> CHUNK["Chunker<br/>RecursiveCharacterTextSplitter<br/>600 TOKENS / 90 overlap (tiktoken)"]
  CHUNK --> IDS["make_chunk_id<br/>sha1(document_id, pagina, indice)"]
  IDS --> EMB["OllamaEmbedder.embed_documents<br/>bge-m3, en lotes pequenos"]
  EMB --> UP["VectorStore.upsert<br/>IDEMPOTENTE - re-ingestar sobreescribe"]
  UP --> COLL[("Collection por vertical<br/>legal_boe / health_gpc<br/>./chroma_db")]
```

Offline y separado del query path (`ingest.py:386-430`). Los ids deterministas (`:78-87`) hacen
la re-ingesta idempotente (AC1); la longitud se mide en tokens vía `length_function` inyectada
(`:169-210`) — sin ella, 600 significaría caracteres y degradaría retrieval en silencio. El
preflight de Ollama corre ANTES de embeber (`:416`): nunca una Collection corrupta a medias.

## 5. Máquina de decisión: citación / abstención

```mermaid
---
title: De la Query al done — quién decide chips y abstención
---
stateDiagram-v2
  [*] --> RelevanceGate : Query embebida + top-k Chroma

  RelevanceGate --> AbstencionDura : 0 chunks bajo el umbral<br/>(1.05 legal / 0.90 health)
  RelevanceGate --> Etapa1_Respuesta : >= 1 chunk pasa

  AbstencionDura --> Done : SIN llamar al LLM<br/>is_abstention=true, un TextPart

  Etapa1_Respuesta --> StripSimetrico : prosa limpia del 7B<br/>(temp 0.1, sin marcadores)

  StripSimetrico --> AbstencionPura : la frase ES toda la respuesta<br/>(guard: nunca se vacia)
  StripSimetrico --> Etapa2_Anchoring : quedan bordes limpios<br/>DESDE AQUI LA PROSA ES INTOCABLE

  AbstencionPura --> Done : 0 chips + resolved == frase<br/>is_abstention=true

  Etapa2_Anchoring --> Etapa3_Verifier : anclas JSON validadas<br/>(rango 1..N, dedup)
  Etapa2_Anchoring --> Done : pase fallido o 0 anclas<br/>respuesta SIN chips (aditivo)

  state Etapa3_Verifier {
    [*] --> Puntuar : coseno frase-citation<br/>(chunks agrupados por dedup)
    Puntuar --> Discard : cos_max < 0.50<br/>(nada respalda: chip fuera)
    Puntuar --> Repair : margen al argmax > 0.05<br/>(remapea al chunk correcto)
    Puntuar --> Keep : empate <= 0.05<br/>(ambiguedad legitima)
    Discard --> [*]
    Repair --> [*]
    Keep --> [*]
  }

  Etapa3_Verifier --> Ensamblado : anclas verificadas
  Ensamblado --> Done : TextParts + CiteParts<br/>is_abstention = 0 chips AND resolved == frase
  Done --> [*]
```

El invariante central: **a partir del strip, la prosa nunca se modifica** — anchoring y
verificador solo deciden QUÉ chips existen y a qué citation apuntan (`_parts_from_anchors`
reproduce el texto byte a byte, `generate.py:309-352`). La abstención se decide por ESTADO
resuelto, nunca por matching de prosa cruda (`query.py:86-107`); el verificador es "the LLM
proposes, the deterministic guard disposes" (`verify_anchors`, `generate.py:213-306`, umbrales
calibrados en `config/*.yaml` y registrados en `DECISIONS.md`).
