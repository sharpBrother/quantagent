# Sewing a Chart Engine to a Research Agent: QuantAgent Frankenstein

This post was written as part of the Kiroween 2026 hackathon.

## The odd couple

Classic technical analysis is stubbornly useful: moving averages, RSI, MACD, and Bollinger Bands give you **repeatable**, testable signals. LLM agents are stubbornly useful in a different way: they turn structured facts into a research plan and risk list a human can argue with.

Most tools pick one side. **Frankenstein** is the category for sewing both onto the same body.

## What I built

**QuantAgent Frankenstein** is a Python package that:

1. Pulls OHLCV (live via yfinance, or a fixture for offline demos).
2. Computes a small TA suite and labels trend / momentum / volatility **without** an LLM.
3. Hands a `SignalPack` to an agent layer that returns an `AnalysisBrief` (summary, next research steps, risks).
4. Exposes the stitch over FastAPI so a UI—and the live site at [quantagent.dpdns.org](https://quantagent.dpdns.org/en)—can call one endpoint.

If no LLM key is present, a deterministic template brief still runs. That keeps pytest green and lets judges reproduce the core loop.

## Why the scar matters

The API boundary is the scar. Analysis never imports the agent; the agent never recomputes indicators. That sounds obvious until you have watched “AI trading bots” blur math and vibes into one untestable blob. Kiro IDE steering and specs pushed me to write that contract first (EARS requirements, then design DTOs, then tasks).

## Kiro IDE, briefly

- Always-on steering for product, tech, and structure.
- Specs under `.kiro/specs/market-analysis/`.
- Save hooks for Ruff and pytest on `*.py`.

I am not claiming a Crew workflow or a fictional week of IDE transcripts—just a repo shaped so Kiro’s spec-driven loop is the default.

## Try it

- Live UI: https://quantagent.dpdns.org/en  
- Local: `pip install -e ".[dev]" && uvicorn quantagent_frankenstein.api.app:app --port 8080`

Not investment advice—educational automation for a Halloween-season hackathon.

— Charlie Chen · #KiroweenHackathon26
