---
inclusion: always
---

# Structure — QuantAgent Frankenstein

```
.
├── .kiro/
│   ├── steering/          # always-on product/tech/structure
│   ├── specs/market-analysis/
│   └── hooks/             # lint-on-save, test-on-save
├── src/quantagent_frankenstein/
│   ├── analysis/          # classic TA pipeline
│   ├── agent/             # LLM orchestration layer
│   └── api/               # FastAPI app
├── tests/
├── docs/                  # hackathon write-ups & drafts
├── LICENSE
├── README.md
└── requirements.txt
```

## Module boundaries
- `analysis` never calls the LLM.
- `agent` consumes structured `SignalPack` from analysis; it does not recompute indicators.
- `api` is a thin HTTP façade over both.

## Frankenstein metaphor in code
Two “corpses” joined at `api.routes`: classic quant body + agent brain share one JSON contract (`AnalysisBrief`).
