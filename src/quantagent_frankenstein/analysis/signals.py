from __future__ import annotations


def label_signals(indicators: dict[str, float | None]) -> dict[str, str]:
    close = indicators.get("Close")
    sma20 = indicators.get("SMA20")
    rsi14 = indicators.get("RSI14")
    macd_hist = indicators.get("MACD_HIST")
    bb_u = indicators.get("BB_UPPER")
    bb_l = indicators.get("BB_LOWER")

    # Trend: price vs SMA20
    if close is None or sma20 is None:
        trend = "neutral"
    elif close > sma20 * 1.01:
        trend = "bullish"
    elif close < sma20 * 0.99:
        trend = "bearish"
    else:
        trend = "neutral"

    # Momentum: RSI + MACD hist
    if rsi14 is None:
        momentum = "neutral"
    elif rsi14 >= 70:
        momentum = "overbought"
    elif rsi14 <= 30:
        momentum = "oversold"
    elif macd_hist is not None and macd_hist > 0:
        momentum = "bullish"
    elif macd_hist is not None and macd_hist < 0:
        momentum = "bearish"
    else:
        momentum = "neutral"

    # Volatility: band width relative to mid
    bb_m = indicators.get("BB_MID")
    if bb_u is None or bb_l is None or bb_m is None or bb_m == 0:
        volatility = "normal"
    else:
        width = (bb_u - bb_l) / abs(bb_m)
        if width >= 0.08:
            volatility = "high"
        elif width <= 0.03:
            volatility = "low"
        else:
            volatility = "normal"

    return {"trend": trend, "momentum": momentum, "volatility": volatility}
