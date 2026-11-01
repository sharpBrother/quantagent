from __future__ import annotations

from pathlib import Path

import pandas as pd

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sample_ohlcv.csv"


def load_fixture(symbol: str = "DEMO") -> pd.DataFrame:
    if not FIXTURE_PATH.exists():
        raise FileNotFoundError(f"Missing fixture at {FIXTURE_PATH}")
    df = pd.read_csv(FIXTURE_PATH, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df.attrs["symbol"] = symbol.upper()
    df.attrs["source"] = "fixture"
    return df


def fetch_ohlcv(symbol: str, lookback_days: int = 120) -> pd.DataFrame:
    """Fetch OHLCV; fall back to fixture if yfinance is unavailable or fails."""
    symbol = symbol.upper().strip()
    if symbol in {"DEMO", "FIXTURE", "SAMPLE"}:
        df = load_fixture(symbol)
        if len(df) > lookback_days:
            df = df.tail(lookback_days).reset_index(drop=True)
            df.attrs["symbol"] = symbol
            df.attrs["source"] = "fixture"
        return df
    try:
        import yfinance as yf

        # Pad calendar days so we still get ~lookback trading days
        period_days = max(lookback_days + 30, 60)
        data = yf.download(
            symbol,
            period=f"{period_days}d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if data is None or data.empty:
            raise ValueError(f"No data for {symbol}")
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [c[0] for c in data.columns]
        data = data.reset_index()
        # Normalize column names
        rename = {c: c.title() for c in data.columns}
        data = data.rename(columns=rename)
        if "Date" not in data.columns and "Datetime" in data.columns:
            data = data.rename(columns={"Datetime": "Date"})
        keep = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in data.columns]
        data = data[keep].dropna().tail(lookback_days).reset_index(drop=True)
        data.attrs["symbol"] = symbol
        data.attrs["source"] = "yfinance"
        return data
    except Exception:
        df = load_fixture(symbol)
        # Truncate fixture to lookback if possible
        if len(df) > lookback_days:
            df = df.tail(lookback_days).reset_index(drop=True)
            df.attrs["symbol"] = symbol
            df.attrs["source"] = "fixture"
        return df
