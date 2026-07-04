"""Citara API composition: FastAPI app, CORS, routers, error handlers.

Run from the repo root (config loading resolves config/<v>.yaml against the CWD):

    uvicorn api.main:app --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import register_exception_handlers
from api.routes import health, query, verticals

app = FastAPI(title="Citara API", version="0.1.0")

# Vite dev origin only — the packaged build serves the front same-origin
# (API_CONTRACT.md §Base), so no wildcard is ever needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(health.router)
app.include_router(verticals.router)
app.include_router(query.router)
