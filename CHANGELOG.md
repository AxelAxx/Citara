# Changelog

All notable changes to Citara. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project is **frozen at v0.4** (2026-10-13) as a portfolio showcase; no further features are planned.

## [0.4.0] - 2026-10-13

Closure release. The engine answers over the two pre-ingested corpora (legal/BOE, health/GuíaSalud)
and nothing else; everything below was already live in `main` and is consolidated here.

### Added
- React 19 + Vite presentation (`frontend/`) over a FastAPI + SSE adapter (`api/`), migrated from
  Streamlit with zero changes in `core/`.
- Inline citation chips: a second constrained-JSON anchoring pass plus a deterministic
  `AnchorVerifier` (relative cosine margin) that repairs or drops chips without touching the prose.
- Resolved-state abstention: `is_abstention` is decided from the final structured answer, never by
  pattern-matching the model's text.
- Per-vertical relevance gate and `AnswerabilityGate` (margin calibrated on a labeled set, `docs/b2/`).
- Human document titles in the context header; cited vs consulted split in the sources panel.
- Generalized `ConfirmDialog` + `DialogProvider`; backend errors surfaced as recoverable dialogs.
- Reverse-engineering audit of the repository (`docs/audit/`) with an end-to-end readiness report.
- Project closure: rewritten README with real screenshots and demo GIF, AGPL-3.0 license,
  `CHANGELOG.md`, GitHub Actions CI (ruff + pytest + frontend typecheck/lint/build), pinned and
  trimmed dependency files, ruff configuration in `pyproject.toml`.

### Changed
- `docs/DECISIONS_merged.md` renamed to `docs/DECISIONS.md` (the name every other doc linked).
- Frontend helpers (`formatThousands`, `splitCitations`, dialog palette/icons, `useDialog`) moved
  out of component files so every module is Fast-Refresh clean (zero oxlint warnings).
- Stale references to the Streamlit presentation removed from `api/` docstrings.

### Known limitations (documented, not fixed)
- Header-only chunks in the health corpus can win retrieval for title-phrased questions
  (`docs/audit/06-readiness.md`).
- First-person out-of-corpus questions on health still produce a prose decline
  (`docs/KNOWN_LIMITATION_B2_first_person_out_of_corpus.md`).

## [0.3.0] and earlier

Streamlit MVP: `RagEngine` with the nine core modules, two verticals from one codebase,
idempotent ingestion, streaming answers, LLM warm-up, hard abstention guard, 69→137 mocked tests.
History lives in `PROGRESS.md` and the git log.

[0.4.0]: https://github.com/AxelAxx/Citara/releases/tag/v0.4.0
