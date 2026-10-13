# Citara frontend

React 19 + TypeScript + Vite + Tailwind single-page app for Citara. It is a thin client over
the FastAPI backend: it never touches Ollama or ChromaDB and never decides what counts as an
abstention. The wire contract is [`../docs/API_CONTRACT.md`](../docs/API_CONTRACT.md).

## Commands (run inside `frontend/`)

```bash
npm install        # one-time
npm run dev        # Vite dev server at http://localhost:5173, proxies /api to :8000
npm run build      # tsc -b (strict) + vite build into dist/
npm run lint       # oxlint
```

The backend must be running on port 8000 (`uvicorn api.main:app --port 8000` from the repo
root) and Ollama on 11434.

## Layout

```
src/api/client.ts        typed API client + hand-rolled SSE reader (citations → token* → done)
src/hooks/useChat.ts     message state machine: thinking → writing → anchoring → done | error
src/hooks/               useVerticals, useEngineReady (splash / warm-up), useHealth (Ollama badge)
src/screens/Welcome      vertical picker
src/screens/Chat         chat screen: header, empty state, messages, composer, sources panel
src/components/chat      Message (text runs + CiteChip), SourcesPanel, AbstentionNote, ...
src/components/Sidebar   domain switcher, corpus block, conversation list
src/components           Splash, ConfirmDialog + DialogProvider, BrandMark, PrivacyPill
src/theme/accent.ts      per-vertical accent colour
src/version.ts           UI release label shown in the welcome pill and sidebar footer
```

Rendering rule for answers: tokens are rendered verbatim while streaming; on the `done`
event the raw text is replaced by the typed `parts` (text interleaved with citation chips),
and `is_abstention` from that event, never the prose, decides whether the sources panel is
shown.
