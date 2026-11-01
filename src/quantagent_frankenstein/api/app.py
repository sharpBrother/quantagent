from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quantagent_frankenstein.api.routes import router

app = FastAPI(
    title="QuantAgent Frankenstein",
    description=(
        "Classic technical analysis stitched with an LLM research agent "
        "(Kiroween 2026 — Frankenstein). Live UI: https://quantagent.dpdns.org/en"
    ),
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "QuantAgent Frankenstein",
        "docs": "/docs",
        "live_ui": "https://quantagent.dpdns.org/en",
        "category": "Frankenstein",
        "event": "Kiroween 2026",
    }
