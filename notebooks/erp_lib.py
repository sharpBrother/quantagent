"""研究线 erp-rate-anchor 的公共计算：分位、仓位规则、绩效与样本外统计。

函数从 `notebooks/2026-11-23-erp-rate-anchor.py` 原样搬出，行为由那次运行的输出约束
（run ``05cf3475b6354fa8be2c4d3f7bab942f``）：抽出后新旧结果必须逐字节一致。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm

# 年化用的交易日数，与原脚本一致
TRADING_DAYS = 244


def asof_lookup(series: pd.Series, cutoffs: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    pos = series.index.searchsorted(cutoffs, side="right") - 1
    vals = np.where(pos >= 0, series.to_numpy()[np.clip(pos, 0, None)], np.nan)
    obs = np.where(pos >= 0, series.index.to_numpy()[np.clip(pos, 0, None)], np.datetime64("NaT", "ns"))
    return vals, obs


def rolling_percentile(s: pd.Series, years: int) -> pd.Series:
    """信号日及之前 ``years`` 年内全部有效日值中 ``<= 当日值`` 的比例；不满窗口不出信号。"""
    valid = s.dropna()
    window = pd.Timedelta(days=365 * years + years // 4)
    if valid.empty:
        return pd.Series(np.nan, index=s.index)
    first = valid.index[0]
    x = valid.to_numpy()
    idx = valid.index
    lo = idx.searchsorted(idx - window, side="right")
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if idx[i] - first < window:
            continue
        w = x[lo[i] : i + 1]
        out[i] = np.mean(w <= x[i])
    return pd.Series(out, index=idx).reindex(s.index)


def cash_accrual(r_cn: pd.Series) -> pd.Series:
    """第 t 日现金收益：上一交易日的 10Y 收益率按两交易日间的自然日数计息。"""
    days = r_cn.index.to_series().diff().dt.days
    return r_cn.shift(1) / 100.0 * days / 365.0


def ratchet(
    signal: pd.Series,
    ret: pd.Series,
    *,
    lag: int,
    cash: pd.Series | None = None,
    band: float = 0.10,
    band_tol: float = 1e-9,
    return_target: bool = False,
) -> pd.DataFrame:
    """``lag=1``：T 日信号 T+1 收盘成交；``lag=0``：T 日收盘成交（敏感性对照）。

    ``band``/``band_tol`` 原是脚本里的 ``BAND``/``BAND_TOL`` 常量，默认值即原值。
    ``return_target=True`` 时额外输出 ``target`` 列（成交日看到的目标），默认关闭，
    既有调用的输出与加参数前完全一致。
    """
    dates = signal.index
    target = signal.shift(lag)  # 成交日看到的目标
    cash = pd.Series(0.0, index=dates) if cash is None else cash.reindex(dates)
    w = np.nan
    weights, trades, rets = [], [], []
    for i, d in enumerate(dates):
        r = ret.iloc[i]
        c = cash.iloc[i]
        # 当日收益按前一日收盘持仓计算，然后仓位漂移
        if not np.isnan(w):
            if np.isnan(r) or np.isnan(c):
                raise RuntimeError(f"持仓期间缺收益或缺现金利率: {d.date()}")
            port = w * r + (1 - w) * c
            w = w * (1 + r) / (1 + port)
        else:
            port = np.nan
        tgt = target.iloc[i]
        traded = 0.0
        if not np.isnan(tgt):
            if np.isnan(w):
                traded, w = tgt, tgt
            else:
                desired = max(w, tgt) if tgt >= 0.5 else min(w, tgt)
                if abs(desired - w) >= band - band_tol:
                    traded, w = abs(desired - w), desired
        weights.append(w)
        trades.append(traded)
        rets.append(port)
    out = pd.DataFrame({"w": weights, "turnover": trades, "ret": rets}, index=dates)
    if return_target:
        out["target"] = target.to_numpy()
    return out


def perf_daily(
    ret: pd.Series, extra: pd.DataFrame | None = None, rf: pd.Series | None = None
) -> dict[str, float]:
    ret = ret.dropna()
    nav = (1 + ret).cumprod()
    years = len(ret) / TRADING_DAYS
    ann = nav.iloc[-1] ** (1 / years) - 1
    vol = ret.std() * np.sqrt(TRADING_DAYS)
    out = {
        "ann_return": ann,
        "ann_vol": vol,
        "sharpe_rf0": ann / vol if vol else np.nan,
        "max_dd": (nav / nav.cummax() - 1).min(),
        "calmar": ann / abs((nav / nav.cummax() - 1).min()),
        "days": len(ret),
    }
    if rf is not None:
        excess = ret - rf.reindex(ret.index)
        out["sharpe_excess"] = excess.mean() / excess.std() * np.sqrt(TRADING_DAYS)
    if extra is not None:
        e = extra.loc[ret.index]
        out |= {
            "avg_w": e["w"].mean(),
            "trades_per_year": (e["turnover"] > 0).sum() / years,
            "turnover_per_year": e["turnover"].sum() / years,
        }
    return out


def nw_ols(y: pd.Series, x: pd.DataFrame, h: int):
    data = pd.concat([y.rename("y"), x], axis=1).dropna()
    fit = sm.OLS(data["y"], sm.add_constant(data[list(x.columns)])).fit(
        cov_type="HAC", cov_kwds={"maxlags": max(h, 1)}
    )
    return fit, len(data)


def clark_west(y: pd.Series, f_small: pd.Series, f_large: pd.Series, h: int) -> tuple[float, float]:
    f = (y - f_small) ** 2 - ((y - f_large) ** 2 - (f_small - f_large) ** 2)
    fit = sm.OLS(f.to_numpy(), np.ones(len(f))).fit(cov_type="HAC", cov_kwds={"maxlags": max(h, 1)})
    t = float(fit.tvalues[0])
    return t, float(1 - norm.cdf(t))
