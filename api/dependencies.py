"""Engine lifecycle: one built+warmed RagEngine per Vertical, process-cached.

Same policy the legacy Streamlit app used for its cached engine (API_CONTRACT.md
§Engine lifecycle): building an engine is cheap and offline, warm-up is not — cache the
built engine per vertical id for the process lifetime. ``lru_cache`` only caches
successful calls, so a bad id / missing YAML is retried naturally, never poisoned.
"""

from __future__ import annotations

import contextlib
from functools import cache

from core.engine import RagEngine
from core.ingest import load_vertical_config
from core.models import RagEngineError, Vertical


@cache
def get_engine(vertical_id: str) -> RagEngine:
    """Build (and cache) the RagEngine for a Vertical id.

    An unknown id raises ValueError from ``Vertical(...)`` — deliberately left
    to escape: the global handler maps it to 404 unknown_vertical.
    """
    config = load_vertical_config(Vertical(vertical_id))
    engine = RagEngine.from_vertical_config(config)
    # Best-effort warm-up ("don't fail twice"): a dead Ollama must not fail engine
    # construction — the identical actionable error surfaces loudly via
    # check_health()/the first query instead. Deliberate suppression, not a swallow.
    with contextlib.suppress(RagEngineError):
        engine.warm_up()
    return engine
