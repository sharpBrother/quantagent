# Requirements — Market Analysis (Frankenstein stitch)

Feature: stitch classic technical analysis with an LLM research agent.

## Ubiquitous language
- **Symbol**: ticker string (e.g. `AAPL`)
- **OHLCV**: open/high/low/close/volume bars
- **SignalPack**: structured indicator values + discrete signal labels
- **AnalysisBrief**: narrative summary, research next-steps, risk bullets

## Functional requirements (EARS)

### R1 — Data ingest
WHEN a user requests analysis for a valid symbol and lookback window, THE System SHALL produce an OHLCV series covering that window or return a clear error if data is unavailable.

### R2 — Indicator computation
WHEN an OHLCV series is available, THE System SHALL compute at least SMA(20), EMA(12), RSI(14), MACD(12,26,9), and Bollinger Bands(20,2).

### R3 — Signal labeling
WHEN indicators are computed, THE System SHALL emit discrete signal labels for trend, momentum, and volatility regimes (e.g. bullish/neutral/bearish or high/normal/low) without using an LLM.

### R4 — Agent brief
WHEN a SignalPack is available, THE System SHALL produce an AnalysisBrief containing (a) a short plain-language summary, (b) ordered research next-steps, and (c) at least two risk callouts.

### R5 — Offline / no-key mode
WHEN no LLM API key is configured, THE System SHALL still return a template AnalysisBrief derived deterministically from the SignalPack so demos and tests remain runnable.

### R6 — HTTP API
WHEN a client POSTs `/api/analyze` with `{ "symbol": "...", "lookback_days": N }`, THE System SHALL return JSON including `symbol`, `signals`, and `brief`.

### R7 — Health
WHEN a client GETs `/health`, THE System SHALL return `{ "status": "ok" }`.

## Non-functional
- NFR1: Indicator math MUST be unit-tested with fixture bars (no live network required in CI).
- NFR2: Responses MUST include a disclaimer that output is not investment advice.
- NFR3: THE System SHALL NOT store user API keys in the repository.

## Properties suitable for property-based tests (PBT)
- P1: For any OHLCV length ≥ 30, RSI values are within [0, 100].
- P2: Bollinger upper ≥ middle ≥ lower for every overlapping window.
- P3: Template brief always contains ≥ 2 risk bullets when SignalPack is non-empty.
