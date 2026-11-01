---
inclusion: always
---

# Product — QuantAgent Frankenstein (Kiroween 2026)

## One-liner
Stitch a **classic technical-analysis pipeline** (indicators + signals) with a **modern LLM research agent** that explains the chart, plans next research steps, and surfaces risks—so retail traders get automated market analysis without staring at raw candles alone.

## Who it is for
Solo or small retail traders who want a repeatable “scan → signal → plain-language brief → risk callouts” loop, not another black-box tip bot.

## Problem
Manual stock analysis is slow and fragmented: indicators live in one tool, news/context in another, and writing a coherent brief is still human work. Automation usually means either pure quant signals with no explanation, or chatbots with no grounded TA.

## Frankenstein stitch
- **Body (retro):** deterministic TA engine — OHLCV fetch, SMA/EMA/RSI/MACD/Bollinger, rule-based signal labels.
- **Brain (modern):** LLM agent orchestration — turns signal packs into research plans, narrative briefs, and explicit risk bullets.
- **Face:** existing QuantAgent web UI at https://quantagent.dpdns.org/en (production surface for demos).

## Non-goals
- Not investment advice; outputs are educational analysis drafts.
- Not high-frequency trading or order routing.
- Not fabricating historical Kiro usage logs—this repo is set up so Kiro IDE (steering, specs, hooks) can drive the work going forward.

## Success for the hackathon
A public GitHub repo with `.kiro/` at the root, MIT license, runnable Python backend, working app URL, under-3-minute demo video, and Kiro usage write-up describing how IDE specs/steering/hooks shaped the build.
