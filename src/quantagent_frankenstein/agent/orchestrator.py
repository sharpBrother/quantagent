from __future__ import annotations

import json
import os
from typing import Any

from quantagent_frankenstein.analysis.models import AnalysisBrief, DISCLAIMER, SignalPack
from quantagent_frankenstein.agent.prompts import SYSTEM_PROMPT, user_prompt


def template_brief(pack: SignalPack) -> AnalysisBrief:
    ind = pack.indicators
    labels = pack.labels
    close = ind.get("Close")
    rsi = ind.get("RSI14")
    summary = (
        f"{pack.symbol} as of {pack.as_of}: trend={labels.get('trend')}, "
        f"momentum={labels.get('momentum')}, volatility={labels.get('volatility')}. "
        f"Close≈{close:.2f}" if isinstance(close, float) else f"{pack.symbol}: signals computed."
    )
    if isinstance(rsi, float):
        summary += f", RSI14≈{rsi:.1f}."
    else:
        summary += "."

    research_steps = [
        "Confirm higher-timeframe trend vs the daily SMA20 bias.",
        "Cross-check volume on the last break of SMA20 / Bollinger mid.",
        "Scan catalysts (earnings, macro prints) that could invalidate the TA setup.",
        "Define invalidation level (e.g. close back inside prior range) before acting.",
    ]
    risks = [
        f"Volatility regime labeled '{labels.get('volatility')}' — stops may need widening or tightening.",
        "Indicator signals lag price; sudden gaps can invalidate the setup without warning.",
        "Template/LLM briefs are not personalized advice and may omit fundamental shocks.",
    ]
    if labels.get("momentum") in {"overbought", "oversold"}:
        risks.append(
            f"Momentum labeled {labels.get('momentum')}; mean-reversion and trend-continuation both remain possible."
        )

    return AnalysisBrief(
        summary=summary,
        research_steps=research_steps,
        risks=risks[:4],
        disclaimer=DISCLAIMER,
        mode="template",
        extras={"labels": labels},
    )


def _try_llm_brief(pack: SignalPack) -> AnalysisBrief | None:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    # Optional dependency path — keep import local so default installs stay light.
    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key)
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        content = (
            SYSTEM_PROMPT
            + "\n\n"
            + user_prompt(pack.to_dict())
            + "\nRespond as compact JSON with keys summary, research_steps, risks."
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0.2,
        )
        text = resp.choices[0].message.content or ""
        data: dict[str, Any]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return AnalysisBrief(
                summary=text[:500],
                research_steps=["Review the free-form model reply above and validate against the chart."],
                risks=[
                    "Model returned non-JSON; treat narrative cautiously.",
                    "No structured risk list from the model.",
                ],
                disclaimer=DISCLAIMER,
                mode="llm",
            )
        return AnalysisBrief(
            summary=str(data.get("summary", "")),
            research_steps=[str(x) for x in data.get("research_steps", [])] or ["Validate TA vs news."],
            risks=[str(x) for x in data.get("risks", [])] or ["Model omitted risks; add your own."],
            disclaimer=DISCLAIMER,
            mode="llm",
        )
    except Exception:
        return None


def build_brief(pack: SignalPack) -> AnalysisBrief:
    llm = _try_llm_brief(pack)
    if llm is not None:
        return llm
    brief = template_brief(pack)
    if os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY"):
        brief.mode = "template_fallback"
    return brief
