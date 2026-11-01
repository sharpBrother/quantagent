# QuantAgent Frankenstein

**Kiroween 2026 — Category: Frankenstein**

Stitch a **retro technical-analysis pipeline** (SMA/EMA/RSI/MACD/Bollinger + rule-based signals) with a **modern LLM research agent** that explains the setup, plans next research steps, and surfaces risks.

> Not investment advice. Educational / hackathon demo only.

## Live demo UI

https://quantagent.dpdns.org/en

This repository is the open Python “body + brain” package that powers automated market analysis toward that UI. Judges can also run the API locally without any LLM key (template brief mode).

## Why Frankenstein

| Corpse | Role |
|--------|------|
| Classic quant TA | Deterministic indicators & discrete labels — testable, no LLM |
| LLM agent | Narrative brief, research plan, risk bullets |
| Scar (API) | Shared `SignalPack` → `AnalysisBrief` JSON contract |

Two ideas that usually live in different apps are sewn into one request.

## Quick start (local)

```bash
cd kiroween-quantagent-frankenstein
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
uvicorn quantagent_frankenstein.api.app:app --reload --port 8080
```

Then:

- Health: `GET http://127.0.0.1:8080/health`
- Analyze: `POST http://127.0.0.1:8080/api/analyze` with `{"symbol":"AAPL","lookback_days":120}`
- OpenAPI: http://127.0.0.1:8080/docs

Without network or yfinance failures, the fetcher falls back to `tests/fixtures/sample_ohlcv.csv`.

Optional LLM mode: set `OPENAI_API_KEY` (or `LLM_API_KEY`) and optionally `LLM_MODEL`.

## Kiro IDE

This repo is structured for **Kiro IDE**:

- `.kiro/steering/` — always-on product / tech / structure context
- `.kiro/specs/market-analysis/` — requirements (EARS) → design → tasks
- `.kiro/hooks/` — ruff + pytest on Python save

**Do not** add `.kiro` to `.gitignore` (hackathon rule).

## License

MIT — see [LICENSE](./LICENSE).

## Event notes

- Solo entry by Charlie Chen
- Submission window (official): 2026-10-30 09:00 PT → 2026-12-04 14:00 PT
- All project packaging for this hackathon framed as new work after 2026-10-30
