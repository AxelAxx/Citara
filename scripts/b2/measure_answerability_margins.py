"""B2 measurement harness: S1 (top-1 margin) over the labeled answerability set.

Eval tooling for SPEC_B2 §9 — NOT core/ and NOT the gate itself. It runs every
labeled Query (docs/b2/b2_answerability_set.yaml) against the LIVE corpus through
the production composition root and records the margin signals that will calibrate
``mu``. No threshold reaches a commit without this table (SPEC_B2 §9).

Read-only by construction: query embedding + Chroma search + relevance gate,
via ``Retriever.retrieve`` exactly as production wires it. The Generator/LLM is
never touched (zero generation), and nothing is written outside
``docs/b2/measurements/``.

Run from anywhere (the script pins the repo root as cwd):

    python scripts/b2/measure_answerability_margins.py

Prerequisites (execution, not repo): Ollama serving BGE-M3, and BOTH verticals
already ingested. A missing prerequisite fails loudly BEFORE any query is
measured — never a silent half-vertical measurement.
"""

from __future__ import annotations

import csv
import os
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

# The script lives in scripts/b2/; core imports and the cwd-relative resources
# (config/*.yaml, ./chroma_db) both resolve from the repo root, so pin it once
# instead of depending on where the caller happened to stand.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
os.chdir(_REPO_ROOT)

from core.engine import RagEngine  # noqa: E402
from core.ingest import load_vertical_config  # noqa: E402
from core.models import (  # noqa: E402
    EmptyCorpusError,
    Query,
    RagEngineError,
    Vertical,
    VerticalConfig,
)

_SET_PATH = Path("docs/b2/b2_answerability_set.yaml")
_OUT_DIR = Path("docs/b2/measurements")

# The calibration anchors named in the set itself: same phenomenology, opposite
# label. Shown query-to-query (never aggregated) — if a pair does not separate
# by margin, that is the visible signal that S1-only is not enough there.
_ANCHOR_PAIRS: list[tuple[str, str, str]] = [
    ("legal", "legal-b2-001", "legal-bridge-001"),
    ("health", "health-b2-001", "health-plain-001"),
]

# Sweep grids in the NATIVE unit (Chroma L2², lower = closer; margins are
# differences/ratios of those distances — no unit transformation anywhere).
# Bounds chosen to bracket the plausible margin range of unit-norm BGE-M3
# distances (observed d ∈ ~[0.6, 1.1]); a mu beyond them is not a candidate.
_SWEEP_RELATIVE = [round(0.02 * i, 2) for i in range(0, 21)]  # 0.00 .. 0.40
_SWEEP_ADDITIVE = [round(0.02 * i, 2) for i in range(0, 16)]  # 0.00 .. 0.30


class MeasurementStatus(str, Enum):
    """Why a query does or does not enter the mu sweep."""

    MEASURED = "measured"  # n_chunks >= 2: full margin signals
    HARD_ABSTAIN = "hard-abstain (sin gate)"  # n_chunks == 0: the hard guard already abstains
    NO_TAIL = "no-tail"  # n_chunks == 1: margin undefined, reported apart


@dataclass(frozen=True)
class LabeledQuery:
    """One row of the labeled set — schema per docs/b2/b2_answerability_set.yaml."""

    id: str
    vertical: Vertical
    query: str
    label: str  # answerable | not_answerable
    category: str
    first_person: bool


@dataclass(frozen=True)
class MarginMeasurement:
    """The S1 signals for one labeled query (None where undefined by status)."""

    case: LabeledQuery
    status: MeasurementStatus
    n_chunks: int
    all_distances: list[float]
    d_top1: float | None = None
    d_rank2: float | None = None
    tail_mean: float | None = None
    tail_median: float | None = None
    margin_additive_mean: float | None = None
    margin_additive_median: float | None = None
    margin_relative: float | None = None


def _load_labeled_set(path: Path) -> list[LabeledQuery]:
    import yaml

    if not path.exists():
        raise RagEngineError(
            f"Labeled set not found at '{path}'. Expected the SPEC_B2 §9 artifact "
            "(docs/b2/b2_answerability_set.yaml)."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_queries = data.get("queries")
    if not raw_queries:
        raise RagEngineError(f"'{path}' has no 'queries' list — nothing to measure.")

    cases: list[LabeledQuery] = []
    for raw in raw_queries:
        missing = [
            key
            for key in ("id", "vertical", "query", "label", "category", "first_person")
            if key not in raw
        ]
        if missing:
            raise RagEngineError(
                f"Labeled query {raw.get('id', '<no id>')!r} is missing required "
                f"fields {missing}. Fix the set before measuring — a half-labeled "
                "row would silently skew the calibration."
            )
        if raw["label"] not in ("answerable", "not_answerable"):
            raise RagEngineError(
                f"Query {raw['id']!r} has unknown label {raw['label']!r}; "
                "expected 'answerable' or 'not_answerable'."
            )
        cases.append(
            LabeledQuery(
                id=raw["id"],
                vertical=Vertical(raw["vertical"]),  # unknown vertical fails here, loudly
                query=raw["query"],
                label=raw["label"],
                category=raw["category"],
                first_person=bool(raw["first_person"]),
            )
        )
    return cases


def _build_engines(
    verticals: list[Vertical],
) -> dict[Vertical, tuple[RagEngine, VerticalConfig]]:
    """Preflight + build one production-wired engine per vertical, BEFORE measuring.

    All verticals are checked up front so a dead Ollama or an un-ingested
    collection aborts the whole run — never a silent half-vertical measurement.

    Private-attribute note: RagEngine exposes no public retrieve/embedder seam
    (its public surface is the LLM use case). Rebuilding adapters by hand here
    would be exactly the wiring drift this harness must not introduce (rule 4),
    and adding a public accessor to core/ is gate-design scope, not measurement
    scope — so this eval tool reaches for ``_embedder``/``_retriever``, confined
    to this file.
    """
    engines: dict[Vertical, tuple[RagEngine, VerticalConfig]] = {}
    for vertical in verticals:
        config = load_vertical_config(vertical)
        engine = RagEngine.from_vertical_config(config)
        engine._embedder.check_health()  # Ollama reachable + bge-m3 pulled, or actionable error
        stats = engine.corpus_stats()  # collection exists and is readable, or RetrievalError
        if stats.chunk_count == 0:
            raise EmptyCorpusError(
                f"Collection '{config.collection_name}' ({vertical.value}) is empty. "
                f"Ingest it first: `python -m core.ingest --vertical {vertical.value}` "
                "— measuring against half a corpus would produce a useless table."
            )
        engines[vertical] = (engine, config)
    return engines


def _measure(case: LabeledQuery, engine: RagEngine, config: VerticalConfig) -> MarginMeasurement:
    context = engine._retriever.retrieve(
        Query(text=case.query),
        top_k=config.top_k,
        relevance_threshold=config.relevance_threshold,
    )
    distances: list[float] = []
    for chunk in context:
        if chunk.distance is None:
            # Cannot happen through the relevance gate (distance-less hits are
            # dropped there); if it does, the propagation contract broke — stop.
            raise RagEngineError(
                f"Query {case.id!r}: retrieved Chunk without a distance. The "
                "transient-distance propagation (Chunk.distance) is broken; "
                "fix core/retrieve.py before trusting any measurement."
            )
        distances.append(chunk.distance)

    if len(distances) == 0:
        return MarginMeasurement(
            case=case, status=MeasurementStatus.HARD_ABSTAIN, n_chunks=0, all_distances=[]
        )
    if len(distances) == 1:
        return MarginMeasurement(
            case=case,
            status=MeasurementStatus.NO_TAIL,
            n_chunks=1,
            all_distances=distances,
            d_top1=distances[0],
        )

    d_top1 = distances[0]  # nearest-first order is the Retriever's contract
    tail = distances[1:]
    tail_mean = statistics.mean(tail)
    tail_median = statistics.median(tail)
    if tail_mean == 0.0:
        # L2² distances under the relevance gate are strictly positive; a zero
        # tail mean means corrupted data, not a measurable margin.
        raise RagEngineError(
            f"Query {case.id!r}: tail_mean is 0.0 — distances look corrupt; "
            "refusing to divide (margin_relative undefined)."
        )
    return MarginMeasurement(
        case=case,
        status=MeasurementStatus.MEASURED,
        n_chunks=len(distances),
        all_distances=distances,
        d_top1=d_top1,
        d_rank2=distances[1],
        tail_mean=tail_mean,
        tail_median=tail_median,
        margin_additive_mean=tail_mean - d_top1,
        margin_additive_median=tail_median - d_top1,
        margin_relative=(tail_mean - d_top1) / tail_mean,
    )


# --- aggregation helpers -------------------------------------------------------


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (numpy 'linear'); values need not be sorted."""
    if not values:
        raise RagEngineError("percentile of an empty group — caller must guard")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = int(pos)
    frac = pos - lower
    if lower + 1 == len(ordered):
        return ordered[lower]
    return ordered[lower] + (ordered[lower + 1] - ordered[lower]) * frac


def _five_numbers(values: list[float]) -> str:
    return " / ".join(
        f"{v:+.4f}"
        for v in (
            min(values),
            _percentile(values, 0.25),
            statistics.median(values),
            _percentile(values, 0.75),
            max(values),
        )
    )


def _sweep_rows(
    measured: list[MarginMeasurement], margins: dict[str, float], grid: list[float]
) -> list[str]:
    """One markdown row per mu: gate=INSUFFICIENT iff margin < mu (S1-only).

    recall  = flagged not_answerable / all not_answerable (in the sweep set)
    precision = answerable among passed / all passed (margin >= mu)
    """
    rows = []
    total_not_answerable = sum(1 for m in measured if m.case.label == "not_answerable")
    for mu in grid:
        flagged = [m for m in measured if margins[m.case.id] < mu]
        passed = [m for m in measured if margins[m.case.id] >= mu]
        caught = sum(1 for m in flagged if m.case.label == "not_answerable")
        false_abstains = [m.case.id for m in flagged if m.case.label == "answerable"]
        recall = caught / total_not_answerable if total_not_answerable else float("nan")
        if passed:
            precision = sum(1 for m in passed if m.case.label == "answerable") / len(passed)
            precision_cell = f"{precision:.2f}"
        else:
            precision_cell = "—"  # nothing passes: precision undefined, not 0
        fa_cell = ", ".join(false_abstains) if false_abstains else "—"
        rows.append(f"| {mu:.2f} | {len(flagged)} | {recall:.2f} | {precision_cell} | {fa_cell} |")
    return rows


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=_REPO_ROOT,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


# --- main ------------------------------------------------------------------------


def main() -> int:
    cases = _load_labeled_set(_SET_PATH)
    verticals = sorted({case.vertical for case in cases}, key=lambda v: v.value)
    engines = _build_engines(verticals)  # fail-fast preflight for ALL verticals first

    results: list[MarginMeasurement] = []
    for case in cases:
        engine, config = engines[case.vertical]
        result = _measure(case, engine, config)
        results.append(result)
        print(f"  {case.id:<18} {result.status.value:<24} n={result.n_chunks}")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%SZ")
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = _OUT_DIR / f"b2_margins_{stamp}.csv"
    md_path = _OUT_DIR / f"b2_margins_{stamp}.md"

    # --- artifact A: per-query CSV ------------------------------------------------
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "vertical",
                "label",
                "category",
                "first_person",
                "n_chunks",
                "d_top1",
                "d_rank2",
                "tail_mean",
                "tail_median",
                "margin_additive_mean",
                "margin_additive_median",
                "margin_relative",
                # extra inspection columns (beyond the spec'd ones, appended last)
                "status",
                "all_distances",
            ]
        )
        for m in results:
            writer.writerow(
                [
                    m.case.id,
                    m.case.vertical.value,
                    m.case.label,
                    m.case.category,
                    m.case.first_person,
                    m.n_chunks,
                    _fmt(m.d_top1),
                    _fmt(m.d_rank2),
                    _fmt(m.tail_mean),
                    _fmt(m.tail_median),
                    _fmt(m.margin_additive_mean),
                    _fmt(m.margin_additive_median),
                    _fmt(m.margin_relative),
                    m.status.value,
                    ";".join(f"{d:.6f}" for d in m.all_distances),
                ]
            )

    # --- artifact B: markdown summary ----------------------------------------------
    lines: list[str] = []
    lines.append("# B2 — S1 top-1 margin measurement (labeled set over the live corpus)")
    lines.append("")
    lines.append(f"- date (UTC): {datetime.now(UTC).isoformat(timespec='seconds')}")
    lines.append(f"- HEAD: `{_git_head()}`")
    lines.append(f"- set: `{_SET_PATH}` ({len(cases)} queries)")
    lines.append(
        "- unit: Chroma L2² distance (lower = closer), native — the same unit "
        "`relevance_threshold` compares; no transformation applied"
    )
    for vertical in verticals:
        engine, config = engines[vertical]
        stats = engine.corpus_stats()
        lines.append(
            f"- {vertical.value}: embedding_model=`{config.embedding_model}`, "
            f"top_k={config.top_k}, relevance_threshold={config.relevance_threshold}, "
            f"collection=`{config.collection_name}` "
            f"({stats.document_count} docs / {stats.chunk_count} chunks)"
        )
    lines.append("")

    measured = [m for m in results if m.status is MeasurementStatus.MEASURED]
    edge = [m for m in results if m.status is not MeasurementStatus.MEASURED]

    lines.append("## Separación por vertical × label (solo queries medidas, n_chunks ≥ 2)")
    lines.append("")
    lines.append(
        "| vertical | label | n | margin_relative (min/p25/med/p75/max) "
        "| margin_additive_mean (min/p25/med/p75/max) |"
    )
    lines.append("|---|---|---|---|---|")
    for vertical in verticals:
        for label in ("answerable", "not_answerable"):
            group = [m for m in measured if m.case.vertical is vertical and m.case.label == label]
            if not group:
                lines.append(f"| {vertical.value} | {label} | 0 | — | — |")
                continue
            rel = [m.margin_relative for m in group]
            add = [m.margin_additive_mean for m in group]
            lines.append(
                f"| {vertical.value} | {label} | {len(group)} "
                f"| {_five_numbers(rel)} | {_five_numbers(add)} |"
            )
    lines.append("")

    lines.append("## Márgenes por query (orden ascendente de margin_relative)")
    lines.append("")
    for vertical in verticals:
        lines.append(f"### {vertical.value}")
        lines.append("")
        lines.append("| id | label | category | n | margin_relative | margin_additive_mean |")
        lines.append("|---|---|---|---|---|---|")
        group = sorted(
            (m for m in measured if m.case.vertical is vertical),
            key=lambda m: m.margin_relative,
        )
        for m in group:
            lines.append(
                f"| {m.case.id} | {m.case.label} | {m.case.category} | {m.n_chunks} "
                f"| {m.margin_relative:+.4f} | {m.margin_additive_mean:+.4f} |"
            )
        lines.append("")

    lines.append("## Sweep de mu (S1-only: INSUFFICIENT si margin < mu)")
    lines.append("")
    lines.append(
        "recall = not_answerable capturadas / not_answerable medibles; "
        "precision = answerable entre las que pasan / total que pasan. "
        "Referencia SPEC_B2 AC3: recall ≥ ~0.9 sin hundir precision. "
        "Las hard-abstain (n=0) NO están en el sweep: el guard duro ya las abstiene."
    )
    lines.append("")
    for vertical in verticals:
        vertical_measured = [m for m in measured if m.case.vertical is vertical]
        for name, margin_of, grid in (
            (
                "relativa",
                {m.case.id: m.margin_relative for m in vertical_measured},
                _SWEEP_RELATIVE,
            ),
            (
                "aditiva-media",
                {m.case.id: m.margin_additive_mean for m in vertical_measured},
                _SWEEP_ADDITIVE,
            ),
        ):
            lines.append(f"### {vertical.value} — formulación {name}")
            lines.append("")
            lines.append("| mu | flagged | recall abst. | precision answ. | falsos abstains |")
            lines.append("|---|---|---|---|---|")
            lines.extend(_sweep_rows(vertical_measured, margin_of, grid))
            lines.append("")

    lines.append("## Pares ancla (query a query, sin agregar)")
    lines.append("")
    by_id = {m.case.id: m for m in results}
    for vertical_name, abstain_id, answer_id in _ANCHOR_PAIRS:
        lines.append(f"### {vertical_name}: {abstain_id} (abstain) vs {answer_id} (answer)")
        lines.append("")
        lines.append(
            "| id | label esperado | n | margin_relative | margin_additive_mean | status |"
        )
        lines.append("|---|---|---|---|---|---|")
        for qid, expected in ((abstain_id, "abstain"), (answer_id, "answer")):
            m = by_id.get(qid)
            if m is None:
                raise RagEngineError(
                    f"Anchor query {qid!r} not present in the labeled set — the "
                    "anchor pairs section would silently lie; fix the set or the ids."
                )
            rel = f"{m.margin_relative:+.4f}" if m.margin_relative is not None else "—"
            add = f"{m.margin_additive_mean:+.4f}" if m.margin_additive_mean is not None else "—"
            lines.append(
                f"| {qid} | {expected} | {m.n_chunks} | {rel} | {add} | {m.status.value} |"
            )
        abstain_m, answer_m = by_id[abstain_id], by_id[answer_id]
        if (
            abstain_m.margin_relative is not None
            and answer_m.margin_relative is not None
            and abstain_m.margin_relative >= answer_m.margin_relative
        ):
            # The honest annotation SPEC_B2 asks for: a non-separating anchor
            # pair is the measured trigger that S1-only is not enough here.
            lines.append("")
            lines.append(
                f"**NO SEPARA por margen**: {abstain_id} (abstain) tiene margin_relative "
                f"≥ que {answer_id} (answer). Señal de que S1-only no basta en "
                f"{vertical_name}; S2 (key-term coverage) es necesaria ahí."
            )
        lines.append("")

    lines.append("## Casos borde excluidos del sweep")
    lines.append("")
    if edge:
        lines.append("| id | label | status | n_chunks | d_top1 |")
        lines.append("|---|---|---|---|---|")
        for m in edge:
            lines.append(
                f"| {m.case.id} | {m.case.label} | {m.status.value} | {m.n_chunks} "
                f"| {_fmt(m.d_top1) or '—'} |"
            )
    else:
        lines.append("Ninguno: todas las queries devolvieron n_chunks ≥ 2.")
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nCSV:     {csv_path}")
    print(f"Resumen: {md_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RagEngineError as exc:
        # Actionable domain errors reach the operator verbatim; anything else is
        # a real bug and should traceback loudly.
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
