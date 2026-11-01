---
inclusion: always
---

# Tech — QuantAgent Frankenstein

## Stack
- **Language:** Python 3.11+
- **API:** FastAPI + Uvicorn
- **Data:** `yfinance` for public OHLCV (local/demo); production may use other feeds behind the live UI
- **TA:** pure-Python / pandas calculations (no proprietary black boxes)
- **Agent layer:** pluggable LLM client interface (env-based API key); local demo can run in “template mode” without a key
- **Tests:** pytest
- **Lint:** ruff (via save hook)

## Constraints
- Prefer small, readable modules over frameworks.
- Deterministic TA must remain testable without network when fixtures are provided.
- Secrets only via environment variables; never commit keys.
- All new project code framed as post-2026-10-30 Kiroween work.

## Kiro IDE usage (intended)
- Steering files keep product/tech/structure context always-on.
- Specs under `.kiro/specs/market-analysis/` drive requirements → design → tasks before feature code.
- Hooks lint and test on save for `*.py`.
