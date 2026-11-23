# %% [markdown]
# # A 股股债利差：人民币利率锚还是美元利率锚（第一阶段）
#
# 检验方案事先固定在 `docs/research/erp-rate-anchor.md`。要改方案先改文档，
# 再改这里，不在看到结果后调参数。
#
# 只读：数据库只 SELECT；结果写到 `var/research/erp_rate_anchor/<run_id>/`，
# 并落一份 run log。

# %%
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.index_returns import PostgresIndexReturnRepository
from quantagent.adapters.postgres.index_valuation import PostgresIndexValuationRepository
from quantagent.adapters.postgres.macro import PostgresMacroRepository
from quantagent.contracts.loader import load_bundle
from quantagent.platform.config import get_settings
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log
from quantagent.platform.storage.paths import detect_repo_root, resolve_var_paths

pd.set_option("display.width", 200)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# %% [markdown]
# ## 固定参数（与研究笔记一致）

# %%
AS_OF = date(2026, 11, 20)  # 研究截止日，固定以便复现
START = date(2002, 1, 1)
# 估值代码 -> 全收益指数代码
INDICES = {"000985.CSI": "h00985.CSI", "000300.SH": "h00300.CSI", "000905.SH": "h00905.CSI"}
MAIN = "000985.CSI"
US_STALE_DAYS = 7
CPI_STALE_DAYS = 120
PCT_YEARS = 5
PCT_YEARS_ALT = 6
BAND = 0.10
BAND_TOL = 1e-9  # 正好差 0.10 也调仓；留容差避免 0.7 - 0.6 < 0.1 的浮点误差
HORIZONS = (1, 3, 6, 12)
MIN_HISTORY = 36
OOS_START = pd.Period("2012-12", "M")
EXCLUDE = (pd.Period("2021-02", "M"), pd.Period("2024-09", "M"))
HIKE_CYCLES = {
    "2004-06..2006-06": (pd.Period("2004-06", "M"), pd.Period("2006-06", "M")),
    "2015-12..2018-12": (pd.Period("2015-12", "M"), pd.Period("2018-12", "M")),
    "2022-03..2023-07": (pd.Period("2022-03", "M"), pd.Period("2023-07", "M")),
}
SUBPERIODS = {
    "2010-2014": ("2010-01-01", "2014-12-31"),
    "2015-2020": ("2015-01-01", "2020-12-31"),
    "2021-01..2024-09": ("2021-01-01", "2024-09-30"),
    "2024-10..": ("2024-10-01", "2099-12-31"),
}
N_SIM = 1000
SEED = 20261123
PARAMS = {
    "as_of": AS_OF.isoformat(),
    "indices": INDICES,
    "us_stale_days": US_STALE_DAYS,
    "cpi_stale_days": CPI_STALE_DAYS,
    "cash": "r_cn(prev trading day) / 100 * calendar_days / 365",
    "pct_years": PCT_YEARS,
    "pct_years_alt": PCT_YEARS_ALT,
    "band": BAND,
    "band_rule": "abs(desired - w) >= band - 1e-9",
    "horizons": HORIZONS,
    "min_history": MIN_HISTORY,
    "oos_start": str(OOS_START),
    "exclude": [str(p) for p in EXCLUDE],
    "hike_cycles": list(HIKE_CYCLES),
    "subperiods": SUBPERIODS,
    "n_sim": N_SIM,
    "seed": SEED,
}

started = time.monotonic()
settings = get_settings()
paths = resolve_var_paths(settings, repo_root=detect_repo_root())
conn = connect(settings, "src")
conn.read_only = True
valuations = PostgresIndexValuationRepository(conn)
macro = PostgresMacroRepository(conn)
index_returns = PostgresIndexReturnRepository(conn)
calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")

# %% [markdown]
# ## 读取
#
# 估值、中债、全收益指数是 `same_day_close`，美债是严格早于 as_of，都没有版本：
# 以研究截止日整段读一次，再按信号日切（同日类 `观测日 <= 信号日`，美债
# `观测日 < 信号日`），与逐日传 as_of 等价。TIPS 有版本，按每个信号日的 as_of 单独读取。

# %%
open_days = [
    d.cal_dt
    for d in calendar.list_days(as_of=AS_OF, exchange="SSE", start=START, end=AS_OF)
    if d.is_open
]
open_idx = pd.DatetimeIndex(open_days)
log(f"交易日 {len(open_days)}")

val_rows = valuations.list_valuations(
    as_of=AS_OF, start=START, end=AS_OF, wind_codes=tuple(INDICES)
)
pe = (
    pd.DataFrame([(r.trade_dt, r.wind_code, r.pe_ttm) for r in val_rows], columns=["d", "code", "pe"])
    .assign(pe=lambda f: pd.to_numeric(f["pe"], errors="raise").astype(float))
    .pivot(index="d", columns="code", values="pe")
)
pe.index = pd.DatetimeIndex(pe.index)
log(f"估值行 {len(val_rows)}")


def point_series(series_id: str) -> pd.Series:
    rows = macro.list_observations(as_of=AS_OF, start=START, end=AS_OF, series_ids=(series_id,))
    s = pd.Series(
        {pd.Timestamp(r.observation_date): (np.nan if r.value is None else float(r.value)) for r in rows}
    )
    return s.sort_index()


r_cn_raw = point_series("cn_cgb_10y")
r_us_raw = point_series("us_ust_10y").dropna()
log(f"中债 {len(r_cn_raw)} 美债 {len(r_us_raw)}")

ret_rows = index_returns.list_returns(
    as_of=AS_OF, start=START, end=AS_OF, wind_codes=tuple(INDICES.values())
)
pct = (
    pd.DataFrame(
        [(r.trade_dt, r.wind_code, None if r.pct_change is None else float(r.pct_change)) for r in ret_rows],
        columns=["d", "code", "pct"],
    )
    .pivot(index="d", columns="code", values="pct")
)
pct.index = pd.DatetimeIndex(pct.index)
log(f"全收益行 {len(ret_rows)}")

# %% [markdown]
# ## 日频面板（交易日）
#
# - EY、r_CN：信号日当天，同日对齐，不取前值（旧仓 ERP 口径）。
# - r_US：契约严格早于 as_of（美债 T 日收盘在北京时间 T+1 早上，ADR
#   2026-11-23-overseas-daily-next-day），取观测日早于信号日的最近一期，过期超过 7 天即缺失。
# - TIPS：信号日 as_of 下的最近一期（契约严格早于 as_of），同样 7 天过期。

# %%
daily = pd.DataFrame(index=open_idx)
for code in INDICES:
    p = pe[code].reindex(open_idx) if code in pe else pd.Series(np.nan, index=open_idx)
    daily[f"ey|{code}"] = np.where(p > 0, 100.0 / p, np.nan)
daily["r_cn"] = r_cn_raw.reindex(open_idx)


def asof_lookup(series: pd.Series, cutoffs: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    pos = series.index.searchsorted(cutoffs, side="right") - 1
    vals = np.where(pos >= 0, series.to_numpy()[np.clip(pos, 0, None)], np.nan)
    obs = np.where(pos >= 0, series.index.to_numpy()[np.clip(pos, 0, None)], np.datetime64("NaT", "ns"))
    return vals, obs


# 与契约 strict 一致：观测日 < 信号日，即 <= 信号日前一天
us_cut = open_idx - pd.Timedelta(days=1)
vals, obs = asof_lookup(r_us_raw, us_cut)
stale = (us_cut - pd.DatetimeIndex(obs)) > pd.Timedelta(days=US_STALE_DAYS)
daily["r_us"] = np.where(stale | pd.isna(obs), np.nan, vals)
daily["r_us_obs"] = pd.DatetimeIndex(obs)
assert (daily["r_us_obs"].dropna() < daily.index[daily["r_us_obs"].notna()]).all()

log("逐日读取 TIPS 版本")
tips_val, tips_obs = [], []
for t in open_idx:
    if t.date() < date(2003, 1, 10):
        tips_val.append(np.nan)
        tips_obs.append(pd.NaT)
        continue
    rows = macro.list_observations(
        as_of=t.date(),
        start=t.date() - timedelta(days=US_STALE_DAYS),
        end=t.date(),
        series_ids=("us_tips_10y",),
    )
    rows = [r for r in rows if r.value is not None]
    assert all(r.knowledge_dt < t.date() for r in rows)
    if rows:
        last = max(rows, key=lambda r: r.observation_date)
        tips_val.append(float(last.value))
        tips_obs.append(pd.Timestamp(last.observation_date))
    else:
        tips_val.append(np.nan)
        tips_obs.append(pd.NaT)
daily["r_us_real"] = tips_val
log("TIPS 完成")

# 中国 CPI 同比：信号日 as_of 下可见的最近一期，观测月距信号日超过 120 天视为缺失
cpi_val = []
for t in open_idx:
    rows = macro.list_observations(
        as_of=t.date(),
        start=t.date() - timedelta(days=CPI_STALE_DAYS),
        end=t.date(),
        series_ids=("cn_cpi_yoy",),
    )
    rows = [r for r in rows if r.value is not None]
    assert all(r.knowledge_dt < t.date() for r in rows)
    cpi_val.append(float(max(rows, key=lambda r: r.observation_date).value) if rows else np.nan)
daily["pi_cn"] = cpi_val


def monthly_asof(series_id: str) -> list[float]:
    """信号日 as_of 下可见的最近一期月度观测；观测月距信号日超过 120 天视为缺失。"""
    out = []
    for t in open_idx:
        rows = macro.list_observations(
            as_of=t.date(),
            start=t.date() - timedelta(days=CPI_STALE_DAYS),
            end=t.date(),
            series_ids=(series_id,),
        )
        rows = [r for r in rows if r.value is not None]
        assert all(r.knowledge_dt < t.date() for r in rows)
        out.append(float(max(rows, key=lambda r: r.observation_date).value) if rows else np.nan)
    return out


daily["r_de"] = monthly_asof("de_bund_10y")
daily["r_jp"] = monthly_asof("jp_jgb_10y")
log(f"德债有效 {daily['r_de'].notna().sum()} 天，日债有效 {daily['r_jp'].notna().sum()} 天")
daily["r_cn_real"] = daily["r_cn"] - daily["pi_cn"]
log(f"CPI 完成，有效 {daily['pi_cn'].notna().sum()} 天")

for code in INDICES:
    ey = daily[f"ey|{code}"]
    daily[f"V|{code}"] = ey - daily["r_cn"]
    daily[f"U|{code}"] = ey - daily["r_us"]
    daily[f"Ur|{code}"] = ey - daily["r_us_real"]
    daily[f"Vr|{code}"] = ey - daily["r_cn_real"]
    daily[f"Ude|{code}"] = ey - daily["r_de"]
    daily[f"Ujp|{code}"] = ey - daily["r_jp"]
    # 负责人原口径：任一利率缺失即缺失（np.maximum 传播 NaN，不用另一个顶替）
    daily[f"Mx|{code}"] = ey - np.maximum(daily["r_us"], daily["r_cn"])
for code, tr in INDICES.items():
    daily[f"ret|{code}"] = pct[tr].reindex(open_idx) / 100.0 if tr in pct else np.nan

print(daily.filter(regex=r"^(r_|ey\|000985|V\|000985|U\|000985|Ur\|000985)").describe().T.round(3))
print("缺失（2005 年起）:\n", daily.loc["2005":].filter(regex=r"^(r_cn|r_us|r_us_real|ey\|000985|ret\|000985)$").isna().sum())

# %% [markdown]
# ## 第一部分：负责人基线策略（日频）
#
# 目标仓位 = 过去 5 年分位；分位 ≥ 0.5 只加仓、< 0.5 只减仓；|目标 − 当前| > 0.10
# 才调仓。T 日收盘出信号，T+1 收盘成交。仓位随行情漂移，不计成本。
# 现金按上一交易日的 10 年期国债收益率计息（act/365，负责人 2026-11-23 裁定）。

# %%
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
    signal: pd.Series, ret: pd.Series, *, lag: int, cash: pd.Series | None = None
) -> pd.DataFrame:
    """``lag=1``：T 日信号 T+1 收盘成交；``lag=0``：T 日收盘成交（敏感性对照）。"""
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
                if abs(desired - w) >= BAND - BAND_TOL:
                    traded, w = abs(desired - w), desired
        weights.append(w)
        trades.append(traded)
        rets.append(port)
    return pd.DataFrame({"w": weights, "turnover": trades, "ret": rets}, index=dates)


# 规则自检：负责人给的例子（目标升了就加，回落到 0.5 以上不减，跌破 0.5 才减）。
# 收益记 0，仓位不漂移。正好差 0.10 也调仓（负责人 2026-11-23 裁定）。
_days = pd.bdate_range("2024-01-01", periods=10)
_check = ratchet(
    pd.Series([0.60, 0.70, 0.75, 0.60, 0.55, 0.45, 0.30, 0.38, 0.52, 0.58], index=_days),
    pd.Series(0.0, index=_days),
    lag=0,
)
assert _check["w"].round(2).tolist() == [
    0.60, 0.70, 0.70, 0.70, 0.70, 0.45, 0.30, 0.30, 0.52, 0.52
], _check
# 0.6→0.7 差正好 0.10，加仓；0.75 与 0.70 差 0.05，不调；回落到 0.6、0.55 不减；
# 跌破 0.5 到 0.45 才减；0.30→0.38 不加；回到 0.52 加仓；0.58 与 0.52 差 0.06，不调。


def perf_daily(
    ret: pd.Series, extra: pd.DataFrame | None = None, rf: pd.Series | None = None
) -> dict[str, float]:
    ret = ret.dropna()
    nav = (1 + ret).cumprod()
    years = len(ret) / 244
    ann = nav.iloc[-1] ** (1 / years) - 1
    vol = ret.std() * np.sqrt(244)
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
        out["sharpe_excess"] = excess.mean() / excess.std() * np.sqrt(244)
    if extra is not None:
        e = extra.loc[ret.index]
        out |= {
            "avg_w": e["w"].mean(),
            "trades_per_year": (e["turnover"] > 0).sum() / years,
            "turnover_per_year": e["turnover"].sum() / years,
        }
    return out


SIGNALS = {"U_us": "U", "V_cn": "V", "Max_us_cn": "Mx", "Ur_tips": "Ur", "EY": "ey"}
cash = cash_accrual(daily["r_cn"])
strategy_runs: dict[tuple[str, int, int], pd.DataFrame] = {}
baseline_rows = []
for years in (PCT_YEARS, PCT_YEARS_ALT):
    pcts = {name: rolling_percentile(daily[f"{col}|{MAIN}"], years) for name, col in SIGNALS.items()}
    # 共同区间：所有信号都已出值之后
    common_start = max(p.first_valid_index() for p in pcts.values())
    ret = daily[f"ret|{MAIN}"].loc[common_start:]
    for lag in (1, 0):
        bh = perf_daily(ret.iloc[1:], rf=cash)
        baseline_rows.append({"pct_years": years, "lag": lag, "signal": "buy_hold"} | bh)
        for name, p in pcts.items():
            run = ratchet(p.loc[common_start:], ret, lag=lag, cash=cash)
            strategy_runs[(name, years, lag)] = run
            baseline_rows.append(
                {"pct_years": years, "lag": lag, "signal": name}
                | perf_daily(run["ret"], run, rf=cash)
            )
baseline = pd.DataFrame(baseline_rows)
log(f"基线策略完成，共同起点 {common_start.date()}")
print(baseline.round(3).to_string(index=False))

# 分段表现（5 年窗口、T+1 成交）
seg_rows = []
for seg, (a, b) in SUBPERIODS.items():
    ret = daily[f"ret|{MAIN}"]
    for name in ("buy_hold", *SIGNALS):
        if name == "buy_hold":
            r = ret.loc[a:b].loc[strategy_runs[("U_us", PCT_YEARS, 1)].index[1] :]
            seg_rows.append({"segment": seg, "signal": name} | perf_daily(r, rf=cash))
        else:
            run = strategy_runs[(name, PCT_YEARS, 1)].loc[a:b]
            seg_rows.append(
                {"segment": seg, "signal": name} | perf_daily(run["ret"], run, rf=cash)
            )
segments = pd.DataFrame(seg_rows)
print(segments[["segment", "signal", "ann_return", "max_dd", "avg_w"]].round(3).to_string(index=False))

# %% [markdown]
# ## 第二部分：月频预测检验
#
# 信号日取每月最后一个交易日；未来收益从 T+1 收盘起算，全收益对数收益（百分点）。

# %%
month = pd.Series(open_idx, index=open_idx.to_period("M"))
signal_dates = month.groupby(level=0).max()
signal_dates = signal_dates[signal_dates.index < pd.Period(AS_OF, "M")]
pos_of = {d: i for i, d in enumerate(open_idx)}
entry = {p: (open_idx[pos_of[t] + 1] if pos_of[t] + 1 < len(open_idx) else None) for p, t in signal_dates.items()}
periods = list(signal_dates.index)

panel = daily.loc[signal_dates.to_numpy()].copy()
panel.index = signal_dates.index
panel["signal_dt"] = signal_dates.to_numpy()
log_ret = np.log1p(daily.filter(like="ret|"))


def forward_return(code: str, i: int, h: int) -> float:
    if i + h >= len(periods):
        return np.nan
    a, b = entry[periods[i]], entry[periods[i + h]]
    if a is None or b is None:
        return np.nan
    w = log_ret.loc[(log_ret.index > a) & (log_ret.index <= b), f"ret|{code}"]
    if w.empty or w.isna().any():
        return np.nan
    return float(w.sum() * 100.0)


for code in INDICES:
    for h in HORIZONS:
        panel[f"fwd{h}|{code}"] = [forward_return(code, i, h) for i in range(len(periods))]


def predictors(code: str) -> pd.DataFrame:
    g = panel["r_us"] - panel["r_cn"]
    return pd.DataFrame(
        {
            "EY": panel[f"ey|{code}"],
            "V": panel[f"V|{code}"],
            "U": panel[f"U|{code}"],
            "G": g,
            "U_real": panel[f"Ur|{code}"],
            "Mx": panel[f"Mx|{code}"],
            "Gp": g.clip(lower=0),
            "Gm": g.clip(upper=0),
        }
    )


MODELS = {
    "M_EY": ["EY"],
    "M1_V": ["V"],
    "M2_U": ["U"],
    "M2r_Ureal": ["U_real"],
    "M3_V+G": ["V", "G"],
    "M6_Max": ["Mx"],
    "M7_V+G+G-": ["V", "Gp", "Gm"],
}


def nw_ols(y: pd.Series, x: pd.DataFrame, h: int):
    data = pd.concat([y.rename("y"), x], axis=1).dropna()
    fit = sm.OLS(data["y"], sm.add_constant(data[list(x.columns)])).fit(
        cov_type="HAC", cov_kwds={"maxlags": max(h, 1)}
    )
    return fit, len(data)


in_sample = []
for code in INDICES:
    x_all = predictors(code)
    for h in HORIZONS:
        y = panel[f"fwd{h}|{code}"]
        for name, cols in MODELS.items():
            fit, n = nw_ols(y, x_all[cols], h)
            for col in cols:
                in_sample.append(
                    {"index": code, "h": h, "model": name, "var": col, "coef": fit.params[col],
                     "t_nw": fit.tvalues[col], "r2": fit.rsquared, "n": n}
                )
in_sample = pd.DataFrame(in_sample)
print(in_sample[in_sample["index"] == MAIN].round(3).to_string(index=False))


def oos_forecasts(code: str, h: int) -> pd.DataFrame:
    x_all = predictors(code)
    y = panel[f"fwd{h}|{code}"]
    realized = {p: (entry[periods[i + h]] if i + h < len(periods) else None) for i, p in enumerate(periods)}
    out = []
    for i, p in enumerate(periods):
        if p < OOS_START or np.isnan(y.iloc[i]):
            continue
        t = panel["signal_dt"].iloc[i]
        # 只用信号日已实现的样本训练
        train = [q for q in periods[:i] if realized[q] is not None and realized[q] <= t]
        y_train = y.loc[train].dropna()
        if len(y_train) < MIN_HISTORY:
            continue
        row = {"period": p, "y": y.iloc[i], "M0": y_train.mean()}
        for name, cols in MODELS.items():
            data = pd.concat([y.loc[train].rename("y"), x_all.loc[train, cols]], axis=1).dropna()
            x_now = x_all.loc[[p], cols]
            if len(data) < MIN_HISTORY or x_now.isna().any(axis=None):
                row[name] = np.nan
                continue
            fit = sm.OLS(data["y"], sm.add_constant(data[cols])).fit()
            row[name] = float(np.asarray(fit.predict(sm.add_constant(x_now, has_constant="add")))[0])
        out.append(row)
    return pd.DataFrame(out).set_index("period")


def clark_west(y: pd.Series, f_small: pd.Series, f_large: pd.Series, h: int) -> tuple[float, float]:
    f = (y - f_small) ** 2 - ((y - f_large) ** 2 - (f_small - f_large) ** 2)
    fit = sm.OLS(f.to_numpy(), np.ones(len(f))).fit(cov_type="HAC", cov_kwds={"maxlags": max(h, 1)})
    t = float(fit.tvalues[0])
    return t, float(1 - norm.cdf(t))


oos = []
for code in INDICES:
    for h in HORIZONS:
        c = oos_forecasts(code, h).dropna()
        for name in MODELS:
            r2 = 1 - ((c["y"] - c[name]) ** 2).sum() / ((c["y"] - c["M0"]) ** 2).sum()
            t, p = clark_west(c["y"], c["M0"], c[name], h)
            oos.append({"index": code, "h": h, "model": name, "vs": "M0", "r2_oos": r2, "cw_t": t, "cw_p": p, "n": len(c)})
        r2 = 1 - ((c["y"] - c["M3_V+G"]) ** 2).sum() / ((c["y"] - c["M1_V"]) ** 2).sum()
        t, p = clark_west(c["y"], c["M1_V"], c["M3_V+G"], h)
        oos.append({"index": code, "h": h, "model": "M3_V+G", "vs": "M1_V", "r2_oos": r2, "cw_t": t, "cw_p": p, "n": len(c)})
oos = pd.DataFrame(oos)
print(oos[oos["index"] == MAIN].round(3).to_string(index=False))
log("月频预测完成")

# %% [markdown]
# ## 稳健性（主口径）

# %%
x_main = predictors(MAIN)
# 倒挂月份：第五部分的有效样本
inverted = x_main["G"] > 0
episodes = (inverted != inverted.shift()).cumsum()[inverted]
inversion_spells = [
    {"start": str(g.index[0]), "end": str(g.index[-1]), "months": len(g)}
    for _k, g in episodes.groupby(episodes)
]
print("中美利差倒挂月份段:", inversion_spells)
robust = []


def record(tag: str, mask: pd.Series) -> None:
    for h in HORIZONS:
        y = panel[f"fwd{h}|{MAIN}"][mask]
        for name, cols in MODELS.items():
            fit, n = nw_ols(y, x_main.loc[mask, cols], h)
            robust.append(
                {"sample": tag, "h": h, "model": name}
                | {f"coef_{c}": fit.params[c] for c in cols}
                | {f"t_{c}": fit.tvalues[c] for c in cols}
                | {"r2": fit.rsquared, "n": n}
            )


idx = panel.index
record("full", pd.Series(True, index=idx))
record("excl_2021-02..2024-09", pd.Series(~((idx >= EXCLUDE[0]) & (idx <= EXCLUDE[1])), index=idx))
for tag, (a, b) in HIKE_CYCLES.items():
    record(f"drop_{tag}", pd.Series(~((idx >= a) & (idx <= b)), index=idx))
robust = pd.DataFrame(robust)

trend = pd.Series(np.arange(len(panel)) / 120.0, index=idx, name="TREND")
g = x_main["G"].dropna()
ar = sm.OLS(g.iloc[1:].to_numpy(), sm.add_constant(g.iloc[:-1].to_numpy())).fit()
c0, phi = ar.params
sigma = float(np.std(ar.resid, ddof=2))
rng = np.random.default_rng(SEED)
sims_z = []
for _ in range(N_SIM):
    z = np.empty(len(g))
    z[0] = g.iloc[0]
    eps = rng.normal(0.0, sigma, len(g))
    for k in range(1, len(g)):
        z[k] = c0 + phi * z[k - 1] + eps[k]
    sims_z.append(pd.Series(z, index=g.index, name="Z"))
placebo = []
for h in HORIZONS:
    y = panel[f"fwd{h}|{MAIN}"]
    fit_g, _ = nw_ols(y, x_main[["V", "G"]], h)
    fit_t, _ = nw_ols(y, pd.concat([x_main["V"], trend], axis=1), h)
    sims = np.abs([nw_ols(y, pd.concat([x_main["V"], z], axis=1), h)[0].tvalues["Z"] for z in sims_z])
    placebo.append(
        {"h": h, "t_G": fit_g.tvalues["G"], "r2_VG": fit_g.rsquared, "t_TREND": fit_t.tvalues["TREND"],
         "r2_VTREND": fit_t.rsquared, "ar1_phi_G": phi, "sim_p_abs_t": float(np.mean(sims >= abs(fit_g.tvalues["G"]))),
         "sim_abs_t_95": float(np.quantile(sims, 0.95))}
    )
placebo = pd.DataFrame(placebo)
persistence = {
    n: float(sm.OLS(s.iloc[1:].to_numpy(), sm.add_constant(s.iloc[:-1].to_numpy())).fit().params[1])
    for n, s in ((n, x_main[n].dropna()) for n in ("EY", "V", "U", "G", "U_real", "Mx"))
}
corr = x_main.corr()
print(robust[robust["model"] == "M3_V+G"].round(3).to_string(index=False))
print(placebo.round(3).to_string(index=False))
print("AR(1):", {k: round(v, 3) for k, v in persistence.items()})
print(corr.round(2))
log("稳健性完成")

# %% [markdown]
# ## 第三部分：中国实际利率口径
#
# Vr = EY − (r_CN − π_CN)。只在 Vr 有分位的区间内，与 U、V、EY 同区间比较。
# 月频只做样本内回归（样本太短，不做样本外）。

# %%
REAL_SIGNALS = {
    "U_us": "U",
    "U_de": "Ude",
    "U_jp": "Ujp",
    "V_cn": "V",
    "Max_us_cn": "Mx",
    "Vr_cn_real": "Vr",
    "EY": "ey",
}
real_pcts = {
    name: rolling_percentile(daily[f"{col}|{MAIN}"], PCT_YEARS) for name, col in REAL_SIGNALS.items()
}
real_start = max(p.first_valid_index() for p in real_pcts.values())
real_ret = daily[f"ret|{MAIN}"].loc[real_start:]
real_rows = [{"signal": "buy_hold"} | perf_daily(real_ret.iloc[1:], rf=cash)]
for name, p in real_pcts.items():
    run = ratchet(p.loc[real_start:], real_ret, lag=1, cash=cash)
    strategy_runs[(f"real_{name}", PCT_YEARS, 1)] = run
    real_rows.append({"signal": name} | perf_daily(run["ret"], run, rf=cash))
real_compare = pd.DataFrame(real_rows).assign(start=str(real_start.date()))
cpi_last = daily["pi_cn"].last_valid_index()
log(f"实际利率口径共同起点 {real_start.date()}，CPI 最后有效日 {cpi_last.date()}")
print(real_compare.round(3).to_string(index=False))

panel["Vr"] = panel[f"Vr|{MAIN}"]
real_in_sample = []
for h in HORIZONS:
    y = panel[f"fwd{h}|{MAIN}"]
    for name, cols in {"Vr": ["Vr"], "V": ["V"], "U": ["U"], "Vr+G": ["Vr", "G"]}.items():
        x = pd.concat([panel["Vr"], x_main[["V", "U", "G"]]], axis=1)[cols]
        mask = panel["Vr"].notna()
        fit, n = nw_ols(y[mask], x[mask], h)
        for col in cols:
            real_in_sample.append(
                {"h": h, "model": name, "var": col, "coef": fit.params[col], "t_nw": fit.tvalues[col], "r2": fit.rsquared, "n": n}
            )
real_in_sample = pd.DataFrame(real_in_sample)
print(real_in_sample.round(3).to_string(index=False))
print(pd.concat([panel["Vr"], x_main[["V", "U", "G"]]], axis=1).dropna().corr().round(2))

# 第四部分月频：同一样本（G_de、G_jp 都可见）比较 V + G_x
panel["G_de"] = panel["r_de"] - panel["r_cn"]
panel["G_jp"] = panel["r_jp"] - panel["r_cn"]
panel["G_us"] = panel["r_us"] - panel["r_cn"]
placebo_mask = panel[["G_de", "G_jp", "G_us"]].notna().all(axis=1)
foreign_rows = []
for h in HORIZONS:
    y = panel[f"fwd{h}|{MAIN}"][placebo_mask]
    for g in ("G_us", "G_de", "G_jp"):
        fit, n = nw_ols(y, pd.concat([x_main["V"], panel[g]], axis=1)[placebo_mask], h)
        foreign_rows.append(
            {"h": h, "G": g, "coef_V": fit.params["V"], "t_V": fit.tvalues["V"],
             "coef_G": fit.params[g], "t_G": fit.tvalues[g], "r2": fit.rsquared, "n": n}
        )
foreign_in_sample = pd.DataFrame(foreign_rows)
print(foreign_in_sample.round(3).to_string(index=False))
print(panel.loc[placebo_mask, ["r_us", "r_de", "r_jp", "r_cn"]].corr().round(2))

# %% [markdown]
# ## 落盘：结果表、pit_report、run log

# %%
bundle = load_bundle()
datasets = (
    "src.wind.aindexvaluation",
    "src.wind.cbondcurvecnbd",
    "src.tushare.us_treasury_yield",
    "src.macro.fred_observation_vintage",
    "src.wind.aindexeodprices",
    "std.trade_calendar",
)
inputs = [
    {
        "dataset": ds,
        "grade": bundle.visibilities[ds].visibility.grade,
        "pit_from": None if bundle.visibilities[ds].pit_from is None else bundle.visibilities[ds].pit_from.isoformat(),
        "pit_recoverable": bundle.visibilities[ds].pit_recoverable,
        "rationale": bundle.visibilities[ds].visibility.rationale.strip(),
    }
    for ds in datasets
]
pit_report = {
    "inputs": inputs,
    "worst_grade": max(i["grade"] for i in inputs),
    "untrusted_ratio": 0.0,
    "notes": [
        "美债名义利率严格早于信号日可见（契约 2026-11-23 改为 strict，旧仓同日可见）。",
        "美国序列按 as-of 取最近一期，超过 7 个自然日视为缺失；中国 CPI 与德债、日债月度序列超过 120 天视为缺失。",
        "德债、日债为 OECD 月均，超精度值按 8 位量化（ADR 2026-11-23-fred-oecd-yield-rounding）。",
        "现金按上一交易日 10Y 国债收益率 act/365 计息，不含久期损益。",
        "Wind 源镜像跟随源端修订，估值与中债为当前版本，不是当时版本。",
    ],
}

daily_out = daily.reset_index(names="trade_dt")
panel_out = panel.reset_index(names="period").assign(period=lambda f: f["period"].astype(str))
input_digest = digest_json(
    {"params": PARAMS, "daily": json.loads(daily_out.to_json(orient="records", date_format="iso"))}
)
results = {
    "baseline": baseline,
    "segments": segments,
    "in_sample": in_sample,
    "oos": oos,
    "robust": robust,
    "placebo": placebo,
    "corr": corr.reset_index(names="var"),
    "real_compare": real_compare,
    "real_in_sample": real_in_sample,
    "foreign_in_sample": foreign_in_sample,
}
output_digest = digest_json({k: json.loads(v.to_json(orient="records")) for k, v in results.items()})

run_id = new_run_id()
out_dir = paths.root / "research" / "erp_rate_anchor" / run_id
out_dir.mkdir(parents=True, exist_ok=False)
daily_out.to_csv(out_dir / "daily.csv", index=False)
panel_out.to_csv(out_dir / "monthly.csv", index=False)
for (name, years, lag), run in strategy_runs.items():
    run.to_csv(out_dir / f"strategy_{name}_{years}y_lag{lag}.csv")
for name, frame in results.items():
    frame.to_csv(out_dir / f"{name}.csv", index=False)
(out_dir / "summary.json").write_text(
    json.dumps(
        {"params": PARAMS, "pit_report": pit_report, "persistence_ar1": persistence,
         "inversion_spells": inversion_spells,
         "input_digest": input_digest, "output_digest": output_digest, "research_only": True,
         "no_database_write": True, "production_qualified": False},
        ensure_ascii=False, indent=2, default=str,
    ),
    encoding="utf-8",
)
log_path = persist_run_log(
    RunLog(
        run_id=run_id,
        action="research.erp_rate_anchor",
        status="success",
        finished_at=datetime.now(UTC),
        elapsed_ms=int((time.monotonic() - started) * 1000),
        input_digest=input_digest,
        output_digest=output_digest,
        row_count=len(daily),
        dml_count=0,
    ),
    paths,
)
conn.close()
log(f"输出 {out_dir}")
log(f"run log {log_path}")
sys.stdout.flush()
