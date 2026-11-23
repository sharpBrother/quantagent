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
from erp_lib import (
    asof_lookup,
    cash_accrual,
    clark_west,
    nw_ols,
    perf_daily,
    ratchet,
    rolling_percentile,
)

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
# 正好差 0.10 也调仓；留容差避免 0.7 - 0.6 < 0.1 的浮点误差。
# 计算已抽到 `erp_lib.ratchet`，其 band/band_tol 默认值就是这两个数。
BAND_TOL = 1e-9
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
# 第六部分：国家统计局 CPI 口径的分段。A 段起点 None 表示从该窗口的共同起点开始。
NBS_SEGMENTS = {
    "A": (None, "2018-06-03"),
    "B": ("2018-06-04", "2025-07-30"),
    "C": ("2025-07-31", "2099-12-31"),
}
# 第八部分：机制检验的期限与汇改后起点
P8_HORIZONS = (3, 6, 12)
P8_FX_POST = "2015-08"
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
    "nbs_cpi_series": "cn_cpi_yoy_nbs",
    "nbs_segments": NBS_SEGMENTS,
    "p7_mix": "0.5*cpi_yoy_nbs + 0.5*ppi_yoy_nbs, same month",
    "p8_policy_horizons": list(P8_HORIZONS),
    "p8_fx_post": P8_FX_POST,
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


def monthly_asof(series_id: str, *, strict: bool = True) -> list[float]:
    """信号日 as_of 下可见的最近一期月度观测；观测月距信号日超过 120 天视为缺失。

    ``strict=True`` 要求可见日严格早于信号日（ALFRED 版本表）；聚源带发布时刻的源按
    ``InfoPublDate`` 的日期当天可见（09:30 发布，T 日收盘信号可用），用 ``strict=False``。
    """
    out = []
    for t in open_idx:
        rows = macro.list_observations(
            as_of=t.date(),
            start=t.date() - timedelta(days=CPI_STALE_DAYS),
            end=t.date(),
            series_ids=(series_id,),
        )
        rows = [r for r in rows if r.value is not None]
        if strict:
            assert all(r.knowledge_dt < t.date() for r in rows)
        else:
            assert all(r.knowledge_dt <= t.date() for r in rows)
        out.append(float(max(rows, key=lambda r: r.observation_date).value) if rows else np.nan)
    return out


daily["r_de"] = monthly_asof("de_bund_10y")
daily["r_jp"] = monthly_asof("jp_jgb_10y")
log(f"德债有效 {daily['r_de'].notna().sum()} 天，日债有效 {daily['r_jp'].notna().sum()} 天")
daily["r_cn_real"] = daily["r_cn"] - daily["pi_cn"]
log(f"CPI 完成，有效 {daily['pi_cn'].notna().sum()} 天")

# 第六部分：国家统计局 CPI（聚源）。发布当天即可见，所以用非 strict 的可见口径。
daily["pi_nbs"] = monthly_asof("cn_cpi_yoy_nbs", strict=False)
nbs_last = daily["pi_nbs"].last_valid_index()
log(f"国家统计局 CPI 有效 {daily['pi_nbs'].notna().sum()} 天，最后有效日 {nbs_last.date()}")
daily["r_cn_real_nbs"] = daily["r_cn"] - daily["pi_nbs"]

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
    daily[f"Vn|{code}"] = ey - daily["r_cn_real_nbs"]
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
    "Vn_cn_real_nbs": "Vn",
    "EY": "ey",
}
real_pcts = {
    name: rolling_percentile(daily[f"{col}|{MAIN}"], PCT_YEARS) for name, col in REAL_SIGNALS.items()
}
real_start = max(p.first_valid_index() for p in real_pcts.values())
# Vn 的起点约 2012-02，早于 Vr，共同起点仍由 Vr（OECD CPI）决定
assert real_start == pd.Timestamp("2018-06-04"), real_start
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
# ## 第六部分：国家统计局 CPI（聚源）
#
# π_NBS 取聚源指标 110255493（国家统计局 CPI 当期同比），观测日是月末，按
# `InfoPublDate` 的日期当天可见，即 `knowledge_dt <= 信号日`；与 OECD 序列严格早于
# 信号日不同。发布日从 2007-02 起，更早的月份不可见。

# %%
def series_by_month(series_id: str) -> pd.Series:
    """as_of=AS_OF 下整段读一条月频序列，按月份对齐（观测日可能是月初或月末）。"""
    rows = macro.list_observations(as_of=AS_OF, start=START, end=AS_OF, series_ids=(series_id,))
    s = pd.Series(
        {pd.Period(r.observation_date, "M"): float(r.value) for r in rows if r.value is not None}
    )
    return s.sort_index()


# 数据核对：只描述两条 CPI 在重叠月份上的差异，不判读。
cpi_diff = pd.concat(
    [series_by_month("cn_cpi_yoy").rename("oecd"), series_by_month(PARAMS["nbs_cpi_series"]).rename("nbs")],
    axis=1,
).dropna()
cpi_diff["diff"] = cpi_diff["nbs"] - cpi_diff["oecd"]
nbs_vs_oecd = pd.DataFrame(
    [
        {
            "overlap_months": len(cpi_diff),
            "diff_months": int((cpi_diff["diff"].abs() > 1e-9).sum()),
            "max_abs_diff": float(cpi_diff["diff"].abs().max()),
            "max_diff_month": str(cpi_diff["diff"].abs().idxmax()),
        }
    ]
)
print(nbs_vs_oecd.round(3).to_string(index=False))
print("差异最大的 10 个月:")
print(cpi_diff.loc[cpi_diff["diff"].abs().sort_values(ascending=False).index[:10]].round(3).to_string())

# 日频策略：与第一部分同规则（5 年窗口、T+1 成交），6 年窗口作敏感性。
NBS_SIGNALS = {"U_us": "U", "V_cn": "V", "Max_us_cn": "Mx", "Vn_cn_real_nbs": "Vn", "EY": "ey"}

def compare_windows(
    signals: dict[str, str], prefix: str
) -> tuple[pd.DataFrame, dict[int, tuple[pd.Timestamp, pd.Series]]]:
    """日频策略比较表：5 年为主、6 年作敏感性，从所有信号都出分位的共同起点算。

    回测存进 ``strategy_runs[(f"{prefix}{name}", years, 1)]``，供分段表复用同一条连续回测。
    """
    rows = []
    windows: dict[int, tuple[pd.Timestamp, pd.Series]] = {}
    for years in (PCT_YEARS, PCT_YEARS_ALT):
        pcts = {name: rolling_percentile(daily[f"{col}|{MAIN}"], years) for name, col in signals.items()}
        start = max(p.first_valid_index() for p in pcts.values())
        ret = daily[f"ret|{MAIN}"].loc[start:]
        windows[years] = (start, ret)
        bh = perf_daily(ret.iloc[1:], rf=cash)
        rows.append({"pct_years": years, "signal": "buy_hold", "start": str(start.date())} | bh)
        for name, p in pcts.items():
            run = ratchet(p.loc[start:], ret, lag=1, cash=cash)
            strategy_runs[(f"{prefix}{name}", years, 1)] = run
            rows.append(
                {"pct_years": years, "signal": name, "start": str(start.date())}
                | perf_daily(run["ret"], run, rf=cash)
            )
    return pd.DataFrame(rows), windows


def segment_table(
    signals: dict[str, str], prefix: str, windows: dict[int, tuple[pd.Timestamp, pd.Series]]
) -> pd.DataFrame:
    """同一条连续回测按 NBS_SEGMENTS 切片，A 段从该窗口的共同起点开始。"""
    rows = []
    for years, (start, ret) in windows.items():
        ref = strategy_runs[(f"{prefix}{next(iter(signals))}", years, 1)]
        for seg, (lo, hi) in NBS_SEGMENTS.items():
            seg_lo = start if lo is None else lo
            r = ret.loc[seg_lo:hi].loc[ref.index[1] :]
            rows.append(
                {"pct_years": years, "segment": seg, "signal": "buy_hold"} | perf_daily(r, rf=cash)
            )
            for name in signals:
                run = strategy_runs[(f"{prefix}{name}", years, 1)].loc[seg_lo:hi]
                rows.append(
                    {"pct_years": years, "segment": seg, "signal": name}
                    | perf_daily(run["ret"], run, rf=cash)
                )
    return pd.DataFrame(rows)


nbs_compare, nbs_windows = compare_windows(NBS_SIGNALS, "nbs_")
print(nbs_compare.round(3).to_string(index=False))
nbs_segments = segment_table(NBS_SIGNALS, "nbs_", nbs_windows)
print(
    nbs_segments[["pct_years", "segment", "signal", "ann_return", "sharpe_excess", "max_dd", "avg_w"]]
    .round(3)
    .to_string(index=False)
)

# 月频样本内：样本限定在 Vn、V、U、EY、G 都可见的月份。
panel["Vn"] = panel[f"Vn|{MAIN}"]
nbs_x = pd.concat([panel["Vn"], x_main[["V", "U", "EY", "G"]]], axis=1)
nbs_mask = nbs_x.notna().all(axis=1)

def in_sample_table(x: pd.DataFrame, mask: pd.Series, models: dict[str, list[str]]) -> pd.DataFrame:
    """月频样本内回归：所有模型同一样本，Newey-West 滞后期等于期限。"""
    rows = []
    for h in HORIZONS:
        y = panel[f"fwd{h}|{MAIN}"]
        for name, cols in models.items():
            fit, n = nw_ols(y[mask], x.loc[mask, cols], h)
            for col in cols:
                rows.append(
                    {"h": h, "model": name, "var": col, "coef": fit.params[col],
                     "t_nw": fit.tvalues[col], "r2": fit.rsquared, "n": n}
                )
    return pd.DataFrame(rows)


NBS_IN_MODELS = {"Vn": ["Vn"], "V": ["V"], "U": ["U"], "EY": ["EY"], "Vn+G": ["Vn", "G"]}
nbs_in_sample = in_sample_table(nbs_x, nbs_mask, NBS_IN_MODELS)
print(nbs_in_sample.round(3).to_string(index=False))


# 月频样本外：与第二部分 oos_forecasts 的区别是训练与预测都限定在同一样本（mask 月份）内。
NBS_OOS_MODELS = {"M_EY": ["EY"], "M1_V": ["V"], "M2_U": ["U"], "M_Vn": ["Vn"]}


def sample_oos_forecasts(
    x: pd.DataFrame, mask: pd.Series, models: dict[str, list[str]], h: int
) -> pd.DataFrame:
    """扩张窗口样本外预测，训练与预测都限定在 mask 月份内，且只用信号日已实现的样本。"""
    y = panel[f"fwd{h}|{MAIN}"]
    realized = {p: (entry[periods[i + h]] if i + h < len(periods) else None) for i, p in enumerate(periods)}
    out = []
    for i, p in enumerate(periods):
        if p < OOS_START or np.isnan(y.iloc[i]) or not bool(mask.iloc[i]):
            continue
        t = panel["signal_dt"].iloc[i]
        train = [
            q for q in periods[:i]
            if bool(mask.loc[q]) and realized[q] is not None and realized[q] <= t
        ]
        y_train = y.loc[train].dropna()
        if len(y_train) < MIN_HISTORY:
            continue
        row = {"period": p, "y": y.iloc[i], "M0": y_train.mean()}
        for name, cols in models.items():
            data = pd.concat([y.loc[train].rename("y"), x.loc[train, cols]], axis=1).dropna()
            x_now = x.loc[[p], cols]
            if len(data) < MIN_HISTORY or x_now.isna().any(axis=None):
                row[name] = np.nan
                continue
            fit = sm.OLS(data["y"], sm.add_constant(data[cols])).fit()
            row[name] = float(np.asarray(fit.predict(sm.add_constant(x_now, has_constant="add")))[0])
        out.append(row)
    return pd.DataFrame(out).set_index("period")


def oos_table(
    x: pd.DataFrame, mask: pd.Series, models: dict[str, list[str]], extra: tuple[str, str] | None
) -> pd.DataFrame:
    """相对 M0 的 R²_OS 与 Clark-West；``extra=(大模型, 嵌套小模型)`` 只报 R²_OS，不做检验。"""
    rows = []
    for h in HORIZONS:
        c = sample_oos_forecasts(x, mask, models, h).dropna()
        span = {"n": len(c), "first_period": str(c.index[0]), "last_period": str(c.index[-1])}
        for name in models:
            r2 = 1 - ((c["y"] - c[name]) ** 2).sum() / ((c["y"] - c["M0"]) ** 2).sum()
            t, p = clark_west(c["y"], c["M0"], c[name], h)
            rows.append(
                {"h": h, "model": name, "vs": "M0", "r2_oos": r2, "cw_t": t, "cw_p": p} | span
            )
        if extra is not None:
            large, small = extra
            r2 = 1 - ((c["y"] - c[large]) ** 2).sum() / ((c["y"] - c[small]) ** 2).sum()
            rows.append(
                {"h": h, "model": large, "vs": small, "r2_oos": r2, "cw_t": np.nan, "cw_p": np.nan}
                | span
            )
    return pd.DataFrame(rows)


nbs_oos = oos_table(nbs_x, nbs_mask, NBS_OOS_MODELS, ("M_Vn", "M1_V"))
print(nbs_oos.round(3).to_string(index=False))
log("国家统计局 CPI 检验完成")

# %% [markdown]
# ## 第七部分：通胀代理
#
# 第六部分否定的是 CPI 同比这个代理。CPI 受食品价格主导，中证全指的盈利更贴近 PPI。
# 主口径 π_mix = 0.5 × CPI + 0.5 × PPI，近似 GDP 平减指数；非食品 CPI 与 PPI 单独作稳健性。
# 三个序列都是聚源源，按 `InfoPublDate` 日期当天可见（`knowledge_dt <= 信号日`）。

# %%
daily["pi_ppi"] = monthly_asof("cn_ppi_yoy_nbs", strict=False)
daily["pi_core"] = monthly_asof("cn_cpi_nonfood_yoy_nbs", strict=False)


def nbs_mix_asof(series_a: str, series_b: str) -> list[float]:
    """两条月度序列同月都可见才出值：取交集里最大的观测月，各半加权；交集为空即缺失。

    主口径要求两项通胀来自同一个月；各自取“最近一期”会把发布不同步的两个月拼在一起。
    """
    out = []
    for t in open_idx:
        rows = macro.list_observations(
            as_of=t.date(),
            start=t.date() - timedelta(days=CPI_STALE_DAYS),
            end=t.date(),
            series_ids=(series_a, series_b),
        )
        assert all(r.knowledge_dt <= t.date() for r in rows)
        values: dict[str, dict[date, float]] = {series_a: {}, series_b: {}}
        for r in rows:
            if r.value is not None:
                values[r.series_id][r.observation_date] = float(r.value)
        common = sorted(values[series_a].keys() & values[series_b].keys())
        out.append(
            0.5 * (values[series_a][common[-1]] + values[series_b][common[-1]]) if common else np.nan
        )
    return out


daily["pi_mix"] = nbs_mix_asof("cn_cpi_yoy_nbs", "cn_ppi_yoy_nbs")
log(
    f"通胀代理有效天数: PPI {daily['pi_ppi'].notna().sum()} "
    f"非食品 {daily['pi_core'].notna().sum()} 混合 {daily['pi_mix'].notna().sum()}"
)
print(daily[["pi_ppi", "pi_core", "pi_mix"]].describe().T.round(3))
for code in INDICES:
    ey = daily[f"ey|{code}"]
    daily[f"Vm|{code}"] = ey - (daily["r_cn"] - daily["pi_mix"])
    daily[f"Vcore|{code}"] = ey - (daily["r_cn"] - daily["pi_core"])
    daily[f"Vppi|{code}"] = ey - (daily["r_cn"] - daily["pi_ppi"])

# 日频策略：做法与第六部分 nbs_compare / nbs_segments 完全相同。
P7_SIGNALS = {
    "U_us": "U",
    "V_cn": "V",
    "Max_us_cn": "Mx",
    "Vn_cn_real_nbs": "Vn",
    "Vm_mix": "Vm",
    "Vcore_nonfood": "Vcore",
    "Vppi": "Vppi",
    "EY": "ey",
}
p7_compare, p7_windows = compare_windows(P7_SIGNALS, "p7_")
print(p7_compare.round(3).to_string(index=False))
p7_segments = segment_table(P7_SIGNALS, "p7_", p7_windows)
print(
    p7_segments[["pct_years", "segment", "signal", "ann_return", "sharpe_excess", "max_dd", "avg_w"]]
    .round(3)
    .to_string(index=False)
)

# 月频：样本限定在 Vm、Vcore、Vppi、Vn、V、U、EY、G 都可见的月份。
# panel 在第二部分由 daily 取样建立，第七部分的日频列是后加的，要按信号日重新取样。
def panel_col(col: str) -> pd.Series:
    return pd.Series(
        daily[col].reindex(panel["signal_dt"].to_numpy()).to_numpy(), index=panel.index
    )


panel["Vm"] = panel_col(f"Vm|{MAIN}")
panel["Vcore"] = panel_col(f"Vcore|{MAIN}")
panel["Vppi"] = panel_col(f"Vppi|{MAIN}")
p7_x = pd.concat(
    [panel[["Vm", "Vcore", "Vppi", "Vn"]], x_main[["V", "U", "EY", "G"]]], axis=1
)
p7_mask = p7_x.notna().all(axis=1)
P7_IN_MODELS = {
    "Vm": ["Vm"],
    "Vcore": ["Vcore"],
    "Vppi": ["Vppi"],
    "Vn": ["Vn"],
    "V": ["V"],
    "U": ["U"],
    "EY": ["EY"],
    "Vm+G": ["Vm", "G"],
}
p7_in_sample = in_sample_table(p7_x, p7_mask, P7_IN_MODELS)
print(p7_in_sample.round(3).to_string(index=False))

P7_OOS_MODELS = {
    "M_EY": ["EY"],
    "M1_V": ["V"],
    "M2_U": ["U"],
    "M_Vn": ["Vn"],
    "M_Vm": ["Vm"],
    "M_Vcore": ["Vcore"],
    "M_Vppi": ["Vppi"],
}
p7_oos = oos_table(p7_x, p7_mask, P7_OOS_MODELS, ("M_Vm", "M1_V"))
print(p7_oos.round(3).to_string(index=False))
log("通胀代理检验完成")

# %% [markdown]
# ## 第八部分：机制检验
#
# 月频、主口径 000985、Newey-West 滞后期等于期限。预期符号与判读标准写在研究笔记里。
# 除声明的 mask 外不加样本限制，缺失由 `nw_ols` 的 dropna 处理。

# %%
# 8a Fed 模型分解：`fwd_h ~ EY + r_CN`（A）与加 r_US（B）。Fed 模型要求 r_CN 系数为负
# 且与 EY 系数之和为 0，所以每个模型都报 Wald 检验 EY + r_CN = 0 的 p 值。
p8a_x = pd.DataFrame({"EY": panel[f"ey|{MAIN}"], "r_cn": panel["r_cn"], "r_us": panel["r_us"]})
p8a_rows = []
for h in HORIZONS:
    y = panel[f"fwd{h}|{MAIN}"]
    for model, cols in (("A_ey_rcn", ["EY", "r_cn"]), ("B_ey_rcn_rus", ["EY", "r_cn", "r_us"])):
        fit, n = nw_ols(y, p8a_x[cols], h)
        wald_p = float(np.ravel(fit.t_test("EY + r_cn = 0").pvalue)[0])
        for col in cols:
            p8a_rows.append(
                {"h": h, "model": model, "var": col, "coef": fit.params[col],
                 "t_nw": fit.tvalues[col], "n": n, "wald_p_ey_plus_rcn": wald_p}
            )
p8a_fed = pd.DataFrame(p8a_rows)
print(p8a_fed.round(3).to_string(index=False))

# 8b 估值陷阱：EPS 用价格指数与 PE_TTM 反推（Wind PE 为当前版本，见 pit_report）。
price_rows = index_returns.list_returns(
    as_of=AS_OF, start=START, end=AS_OF, wind_codes=("000985.CSI",)
)
if not price_rows:
    raise RuntimeError("000985.CSI 价格指数日涨跌幅没有数据，第八部分无法反推 EPS，停下不换代码")
price_pct = pd.Series(
    {
        pd.Timestamp(r.trade_dt): (np.nan if r.pct_change is None else float(r.pct_change))
        for r in price_rows
    }
).sort_index()
px_first, px_last = price_pct.first_valid_index(), price_pct.last_valid_index()
px_window = open_idx[(open_idx >= px_first) & (open_idx <= px_last)]
px_missing = px_window.difference(price_pct.dropna().index)
if len(px_missing):
    raise RuntimeError(
        f"价格指数从 {px_missing[0].date()} 起有 {len(px_missing)} 个交易日缺涨跌幅，不填充"
    )
price_level = (1 + price_pct.reindex(px_window) / 100).cumprod()
log(f"价格指数 {px_first.date()}..{px_last.date()}，{len(px_window)} 个交易日，无缺日")

pe_main = pe[MAIN].reindex(panel["signal_dt"].to_numpy())
pe_ok = pe_main.where(pe_main > 0)
eps = price_level.reindex(panel["signal_dt"].to_numpy()).to_numpy() / pe_ok.to_numpy()
n_months = len(panel)
g_fwd12 = np.full(n_months, np.nan)
g_past12 = np.full(n_months, np.nan)
for i in range(n_months):
    if i + 12 < n_months and eps[i] > 0 and eps[i + 12] > 0:
        g_fwd12[i] = 100.0 * np.log(eps[i + 12] / eps[i])
    if i >= 12 and eps[i] > 0 and eps[i - 12] > 0:
        g_past12[i] = 100.0 * np.log(eps[i] / eps[i - 12])
panel["g_fwd12"] = g_fwd12
panel["g_past12"] = g_past12
panel["dr_cn12"] = panel["r_cn"] - panel["r_cn"].shift(12)

fit_eps, n_eps = nw_ols(
    panel["g_fwd12"], pd.DataFrame({"dr_cn12": panel["dr_cn12"], "g_past12": panel["g_past12"]}), 12
)
p8b_eps = pd.DataFrame(
    [
        {"var": col, "coef": fit_eps.params[col], "t_nw": fit_eps.tvalues[col],
         "r2": fit_eps.rsquared, "n": n_eps}
        for col in ("dr_cn12", "g_past12")
    ]
)
print(p8b_eps.round(3).to_string(index=False))

# D = 1{Δr_CN < 0}；Δr_CN 缺失时 D 保持缺失（不按 0 处理）。
rate_down = panel["dr_cn12"]
d_rate = pd.Series(
    np.where(rate_down.isna(), np.nan, (rate_down < 0).astype(float)), index=panel.index, name="D"
)
v_sig = x_main["V"]
p8b_x = pd.DataFrame({"V": v_sig, "D": d_rate, "VxD": v_sig * d_rate})
p8b_rows = []
for h in HORIZONS:
    y = panel[f"fwd{h}|{MAIN}"]
    fit, n = nw_ols(y, p8b_x, h)
    for col in ("V", "D", "VxD"):
        p8b_rows.append(
            {"h": h, "var": col, "coef": fit.params[col], "t_nw": fit.tvalues[col], "n": n}
        )
p8b_interaction = pd.DataFrame(p8b_rows)
print(p8b_interaction.round(3).to_string(index=False))


# 8c 央行约束：因变量是同业拆借 7 天与 r_CN 未来 h 个月的变化，自变量 G 与当月水平。
def month_mean(s: pd.Series) -> pd.Series:
    """按观测日的自然月取均值；没有观测的月份保持缺失，不补前值、不跨月池化。"""
    return s.groupby(s.index.to_period("M")).mean()


# cn_ibo_7d 是日频、单版本（源端不改写历史值）、发布当天可见，所以 as_of=AS_OF 下
# 整段读一次与逐日传 as_of 读等价：任何观测日在任何信号日上取到的都是同一版本。
ibo_m = month_mean(point_series("cn_ibo_7d")).reindex(panel.index)
policy = pd.DataFrame({"G": x_main["G"], "ibo_m": ibo_m, "r_cn": panel["r_cn"]})
p8c_rows = []
for h in P8_HORIZONS:
    future = policy.shift(-h)
    for dep, y_dep, lvl in (
        ("d_ibo_7d", future["ibo_m"] - policy["ibo_m"], "ibo_m"),
        ("d_r_cn", future["r_cn"] - policy["r_cn"], "r_cn"),
    ):
        x_dep = policy[["G", lvl]]
        fit, n = nw_ols(y_dep, x_dep, h)
        used = pd.concat([y_dep.rename("y"), x_dep], axis=1).dropna()
        for var in ("G", lvl):
            p8c_rows.append(
                {"h": h, "dep": dep, "var": var, "coef": fit.params[var],
                 "t_nw": fit.tvalues[var], "n": n, "first_period": str(used.index[0]),
                 "last_period": str(used.index[-1])}
            )
p8c_policy = pd.DataFrame(p8c_rows)
print(p8c_policy.round(3).to_string(index=False))

# 8d 汇率：`cn_usdcny_fix`（人民币每美元）同样单版本、整段读一次，按自然月取均值。
fx_m = month_mean(point_series("cn_usdcny_fix")).reindex(panel.index)
p8d_rows = []
for sample, lo in (("full", None), (f"post_{P8_FX_POST}", pd.Period(P8_FX_POST, "M"))):
    sample_mask = pd.Series(True, index=panel.index) if lo is None else panel.index >= lo
    for h in P8_HORIZONS:
        dep = 100.0 * np.log(fx_m.shift(-h) / fx_m)
        fit, n = nw_ols(dep[sample_mask], x_main.loc[sample_mask, ["G"]], h)
        used = pd.concat([dep.rename("y"), x_main[["G"]]], axis=1)[sample_mask].dropna()
        p8d_rows.append(
            {"sample": sample, "h": h, "coef_G": fit.params["G"], "t_G": fit.tvalues["G"],
             "r2": fit.rsquared, "n": n, "first_period": str(used.index[0]),
             "last_period": str(used.index[-1])}
        )
p8d_fx = pd.DataFrame(p8d_rows)
print(p8d_fx.round(3).to_string(index=False))
log("机制检验完成")

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
    "src.jydb.c_ed_macroindicatordata",
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
        "国家统计局 CPI（聚源 110255493）按 InfoPublDate 日期当天可见，源镜像数值为当前版本；"
        "观测月末距信号日超过 120 天视为缺失。",
        "PPI 源端口径为上年同月=100，读取时减 100 转为同比。",
        "第八部分的滚动 EPS 由价格指数与 PE_TTM 反推，Wind PE 为当前版本。",
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
    "nbs_vs_oecd": nbs_vs_oecd,
    "nbs_compare": nbs_compare,
    "nbs_segments": nbs_segments,
    "nbs_in_sample": nbs_in_sample,
    "nbs_oos": nbs_oos,
    "p7_compare": p7_compare,
    "p7_segments": p7_segments,
    "p7_in_sample": p7_in_sample,
    "p7_oos": p7_oos,
    "p8a_fed": p8a_fed,
    "p8b_eps": p8b_eps,
    "p8b_interaction": p8b_interaction,
    "p8c_policy": p8c_policy,
    "p8d_fx": p8d_fx,
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
