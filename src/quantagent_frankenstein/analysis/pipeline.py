from __future__ import annotations

from .fetcher import fetch_ohlcv
from .indicators import latest_snapshot
from .models import SignalPack
from .signals import label_signals


def run_analysis(symbol: str, lookback_days: int = 120) -> SignalPack:
    df = fetch_ohlcv(symbol, lookback_days=lookback_days)
    if df.empty or len(df) < 30:
        raise ValueError(f"Insufficient bars for {symbol}")
    indicators = latest_snapshot(df)
    labels = label_signals(indicators)
    as_of = str(df["Date"].iloc[-1])
    return SignalPack(
        symbol=df.attrs.get("symbol", symbol.upper()),
        as_of=as_of,
        indicators=indicators,
        labels=labels,
        bar_count=len(df),
        source=df.attrs.get("source", "unknown"),
    )
