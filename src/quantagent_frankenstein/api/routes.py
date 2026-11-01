from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quantagent_frankenstein.agent import build_brief
from quantagent_frankenstein.analysis import run_analysis

router = APIRouter()


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    lookback_days: int = Field(120, ge=30, le=400)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/analyze")
def analyze(body: AnalyzeRequest) -> dict:
    try:
        pack = run_analysis(body.symbol, lookback_days=body.lookback_days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    brief = build_brief(pack)
    return {
        "symbol": pack.symbol,
        "signals": pack.to_dict(),
        "brief": brief.to_dict(),
        "live_ui": "https://quantagent.dpdns.org/en",
    }
