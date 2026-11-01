from pathlib import Path

import pandas as pd

from quantagent_frankenstein.analysis.indicators import bollinger, compute_all, rsi
from quantagent_frankenstein.analysis.signals import label_signals
from quantagent_frankenstein.agent.orchestrator import template_brief
from quantagent_frankenstein.analysis.pipeline import run_analysis


FIXTURE = Path(__file__).parent / "fixtures" / "sample_ohlcv.csv"


def test_rsi_bounds():
    df = pd.read_csv(FIXTURE, parse_dates=["Date"])
    values = rsi(df["Close"], 14).dropna()
    assert (values >= 0).all() and (values <= 100).all()


def test_bollinger_order():
    df = pd.read_csv(FIXTURE, parse_dates=["Date"])
    upper, mid, lower = bollinger(df["Close"])
    valid = upper.notna() & mid.notna() & lower.notna()
    assert (upper[valid] >= mid[valid]).all()
    assert (mid[valid] >= lower[valid]).all()


def test_compute_all_columns():
    df = pd.read_csv(FIXTURE, parse_dates=["Date"])
    out = compute_all(df)
    for col in ["SMA20", "EMA12", "RSI14", "MACD", "BB_UPPER"]:
        assert col in out.columns


def test_label_signals_keys():
    labels = label_signals({"Close": 110.0, "SMA20": 100.0, "RSI14": 65.0, "MACD_HIST": 0.5, "BB_UPPER": 112.0, "BB_MID": 100.0, "BB_LOWER": 88.0})
    assert set(labels) == {"trend", "momentum", "volatility"}
    assert labels["trend"] == "bullish"


def test_pipeline_and_template_brief():
    pack = run_analysis("DEMO", lookback_days=90)
    brief = template_brief(pack)
    assert len(brief.risks) >= 2
    assert "Not investment advice" in brief.disclaimer
    assert brief.mode == "template"
