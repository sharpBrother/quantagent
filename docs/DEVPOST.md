# Devpost submission draft — QuantAgent Frankenstein

## Project name
QuantAgent Frankenstein

## Tagline
Classic technical analysis stitched to an LLM research agent for automated stock-market briefs.

## Category
**Frankenstein** (only one category)

## Inspiration
Retail traders juggle charting tools and chatbots. One side is measurable but mute; the other is fluent but ungrounded. Frankenstein was the right shelf: sew a deterministic TA engine to a modern agent that explains, plans research, and names risks.

## What it does
- Computes SMA/EMA/RSI/MACD/Bollinger and discrete signal labels.
- Builds an AnalysisBrief (summary, research steps, risks) via LLM or offline template mode.
- Serves `/api/analyze` for UIs; production face: https://quantagent.dpdns.org/en
- Ships with `.kiro` steering, specs, and save hooks for Kiro IDE.

## How I built it
Python 3.11+, pandas for indicators, FastAPI for the scar, optional OpenAI-compatible client for the brain. Spec-driven layout under `.kiro/specs/market-analysis/` before feature code. Pytest covers indicator bounds and API smoke tests.

## Challenges
Keeping the two halves honest: no LLM inside the TA path; graceful template fallback when keys or networks fail; clear “not investment advice” framing.

## Accomplishments
Runnable local API + fixture data, MIT license, hackathon docs pack, Frankenstein metaphor reflected in module boundaries.

## What I learned
A typed signal pack is a better “scar” than a megaprompt. Kiro-style requirements→design→tasks reduce accidental vibe coupling.

## What's next
Richer multi-timeframe packs, better evals on brief quality, and tighter wiring from this open backend into the live QuantAgent UI.

## Built with
Python, FastAPI, pandas, yfinance, Kiro IDE (steering / specs / hooks), optional OpenAI API

## Try it
- Live: https://quantagent.dpdns.org/en  
- Local run: see README

## Links (user fills at submit time)
- GitHub repo: _(publish separately)_
- Demo video: _(YouTube ≤3 min)_
- Blog / social: X drafts in `docs/BLOG_DRAFT.md` and `docs/SOCIAL_DRAFT.md`

## Additional awards (honest)
- Blog + Social Blitz: drafts ready; user posts on X during the submission window
- Student / Startup / Ghost of Past / Kiro Crew App: **not claimed** (solo, not student, no 2025 entry, no Crew)
