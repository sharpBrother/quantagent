from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    return out.fillna(100.0).where(avg_loss != 0, 100.0)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(series, fast) - ema(series, slow)
    signal_line = ema(line, signal)
    hist = line - signal_line
    return line, signal_line, hist


def bollinger(
    series: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    out = df.copy()
    out["SMA20"] = sma(close, 20)
    out["EMA12"] = ema(close, 12)
    out["RSI14"] = rsi(close, 14)
    macd_line, macd_signal, macd_hist = macd(close)
    out["MACD"] = macd_line
    out["MACD_SIGNAL"] = macd_signal
    out["MACD_HIST"] = macd_hist
    bb_u, bb_m, bb_l = bollinger(close)
    out["BB_UPPER"] = bb_u
    out["BB_MID"] = bb_m
    out["BB_LOWER"] = bb_l
    return out


def latest_snapshot(df: pd.DataFrame) -> dict[str, float | None]:
    enriched = compute_all(df)
    last = enriched.iloc[-1]
    keys = [
        "Close",
        "SMA20",
        "EMA12",
        "RSI14",
        "MACD",
        "MACD_SIGNAL",
        "MACD_HIST",
        "BB_UPPER",
        "BB_MID",
        "BB_LOWER",
    ]
    snap: dict[str, float | None] = {}
    for k in keys:
        val = last[k]
        snap[k] = None if pd.isna(val) else float(val)
    return snap
