# How Kiro IDE is used on QuantAgent Frankenstein

This write-up describes the **intended and repository-level Kiro IDE setup** for the Kiroween 2026 Frankenstein entry. It does not invent past chat transcripts or claim features that were not configured in-repo.

## Products used

- **Kiro IDE** (primary): steering, specs, and save hooks drive the Python Frankenstein stitch.
- Not used in this entry: Kiro CLI, Kiro Web, Kiro Crew (no Crew bonus claimed).

## Custom agent / steering

Always-on steering files live under `.kiro/steering/`:

| File | Purpose |
|------|---------|
| `product.md` | Who the user is, Frankenstein stitch, non-goals, compliance disclaimer |
| `tech.md` | Python/FastAPI/pandas stack, env-only secrets, testability |
| `structure.md` | Package boundaries so TA never calls the LLM directly |

`inclusion: always` keeps these constraints in context while editing analysis, agent, and API code.

## Hooks — what they automate

| Hook | Trigger | Action |
|------|---------|--------|
| `lint-on-save.json` | PostFileSave on `*.py` | `ruff check` (with autofix attempt) |
| `test-on-save.json` | PostFileSave on `*.py` | `python -m pytest -q tests/` |

These catch RSI/Bollinger regressions and API contract breaks before a commit.

## Specs vs vibe coding

Feature work followed `.kiro/specs/market-analysis/`:

1. **requirements.md** — EARS statements (WHEN/THE System SHALL) plus PBT-friendly properties.
2. **design.md** — DTO contract (`SignalPack` / `AnalysisBrief`) and the Frankenstein join at the API.
3. **tasks.md** — ordered implementation checklist; user-only publish/submit items left open.

That differs from pure vibe coding: the scar between classic TA and the LLM agent was designed as an explicit JSON boundary *before* routes were written, so either side can be swapped or tested alone.

## MCP / powers / PBT

- No project-specific MCP servers are required to run the demo.
- Property-style checks encoded as pytest: RSI ∈ [0,100], Bollinger ordering, template brief ≥ 2 risks.
- Powers: not claimed for this entry.

## What changed in the workflow

Steering + hooks make the “two corpses” metaphor enforceable in code review: analysis stays deterministic; the agent only consumes structured signals; FastAPI remains a thin scar. That is the Kiro-shaped part of Frankenstein—not a fake log of IDE sessions.
