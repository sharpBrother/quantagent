# Design — Market Analysis

## Architecture
```
Client / QuantAgent UI
        │
        ▼
   FastAPI (api)
        │
   ┌────┴────┐
   ▼         ▼
analysis   agent
 (TA)    (LLM or template)
   │         │
   └────┬────┘
        ▼
  AnalysisBrief JSON
```

## Frankenstein join
Two independent subsystems share one DTO:

```python
@dataclass
class SignalPack:
    symbol: str
    as_of: str
    indicators: dict[str, float | None]
    labels: dict[str, str]  # trend, momentum, volatility

@dataclass
class AnalysisBrief:
    summary: str
    research_steps: list[str]
    risks: list[str]
    disclaimer: str
    mode: str  # "llm" | "template"
```

## analysis package
1. `fetcher.py` — load OHLCV (yfinance live or CSV/fixture).
2. `indicators.py` — pure functions over pandas DataFrames.
3. `signals.py` — map indicator snapshot → labels with fixed thresholds.
4. `pipeline.py` — `run_analysis(symbol, lookback_days) -> SignalPack`.

## agent package
1. `prompts.py` — system/user prompt templates (for LLM mode).
2. `orchestrator.py` — if `OPENAI_API_KEY` (or compatible) present, call LLM; else `template_brief(signal_pack)`.
3. Template mode encodes indicator values into a readable stub so judges can run without keys.

## api package
- `app.py` — FastAPI instance, CORS open for local demo.
- `routes.py` — `/health`, `/api/analyze`.
- Optional: serve a tiny static index pointing to the live UI URL.

## Error handling
- Unknown symbol / empty data → HTTP 404 with `{ "error": "..." }`.
- LLM failure → fall back to template mode and set `brief.mode = "template_fallback"`.

## Security & compliance
- No order placement endpoints.
- Always attach disclaimer string.
- Env-only secrets.

## Deployment story
- Local: `uvicorn quantagent_frankenstein.api.app:app --reload`
- Demo for judges: https://quantagent.dpdns.org/en (production UI that this backend stitches toward)
