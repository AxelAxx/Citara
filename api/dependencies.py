"""Engine lifecycle: one built+warmed RagEngine per Vertical, process-cached.

Mirror of app.py's ``@st.cache_resource _load_engine`` (API_CONTRACT.md §Engine
lifecycle): building an engine is cheap and offline, warm-up is not — cache the
built engine per vertical id for the process lifetime. ``lru_cache`` only caches
successful calls, so a bad id / missing YAML is retried naturally, never poisoned.
"""

from __future__ import annotations

from functools import lru_cache

from core.engine import RagEngine
from core.ingest import load_vertical_config
from core.models import RagEngineError, Vertical


@lru_cache(maxsize=None)
def get_engine(vertical_id: str) -> RagEngine:
    """Build (and cache) the RagEngine for a Vertical id.

    An unknown id raises ValueError from ``Vertical(...)`` — deliberately left
    to escape: the global handler maps it to 404 unknown_vertical.
    """
    config = load_vertical_config(Vertical(vertical_id))
    engine = RagEngine.from_vertical_config(config)
    # Best-effort warm-up (same "don't fail twice" as _load_engine): a dead
    # Ollama must not fail engine construction — the identical actionable error
    # surfaces loudly via check_health()/the first query instead.
    try:
        engine.warm_up()
    except RagEngineError:
        pass
    return engine
