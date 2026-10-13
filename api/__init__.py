"""Citara HTTP Presentation layer: a thin FastAPI adapter over the RagEngine façade.

Successor of the frozen Streamlit ``ui/`` (kept as legacy, unmaintained). Imports
core/ ONLY through the public seam — ``RagEngine``,
``core.models``, ``load_vertical_config``, ``Vertical`` — per docs/API_CONTRACT.md.
Zero vertical logic, zero direct Chroma/Ollama access (golden rules 1 and 2).
"""
