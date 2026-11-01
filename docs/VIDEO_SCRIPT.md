# Video script (~170 seconds) — QuantAgent Frankenstein

**Title idea:** Sewing Classic TA to an LLM Agent — Kiroween 2026 Frankenstein  
**Platform:** YouTube (public, ≤ 3 minutes)  
**Music:** none / only copyright-free beds (user choice)

## 0:00–0:15 — Problem & user
- “Retail traders bounce between charts and chatbots.”
- Show a cluttered chart vs empty chat.
- “I built QuantAgent Frankenstein for people who want automated stock analysis that is both measurable and explainable.”

## 0:15–2:00 — End-to-end demo (~105s)
1. Open https://quantagent.dpdns.org/en — quick tour of the live UI.
2. Cut to local API: `POST /api/analyze` for a symbol (AAPL or DEMO).
3. Show JSON: indicators + labels from the **classic** pipeline (RSI, MACD, Bollinger).
4. Show the **agent** brief: summary, research steps, risk bullets + disclaimer.
5. Toggle narrative: “No API key? Template mode still runs—judges can clone and pytest.”
6. Optional: one sentence on falling back when LLM fails.

## 2:00–2:40 — Kiro IDE highlights (~40s)
- Flash `.kiro/steering` (product/tech/structure).
- Show specs: requirements → design → tasks.
- Mention lint/test hooks on save.
- “The scar is intentional: TA never calls the LLM; they meet at one DTO.”

## 2:40–2:50 — Close (~10s)
- Category: Frankenstein · MIT · solo.
- CTA: repo + live URL; “Not investment advice.”
- End card: #KiroweenHackathon26

## Shot list
- Browser: live UI
- Terminal: uvicorn + curl/httpie
- Editor: `.kiro` tree + `pipeline.py` / `orchestrator.py`
