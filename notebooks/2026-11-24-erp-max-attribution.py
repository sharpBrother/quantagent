# %% [markdown]
# # A 股股债利差：max 口径超额收益归因与机制检验（P0.1–P0.5）
#
# 方案固定于 `docs/research/erp-phase2-plan.md` 的 P0 一节。P0.1 是逐日精确归因，
# P0.2 是每次只改一处的机制实验，P0.3 是控制仓位差异的择时回归与基准，
# P0.4 是实施敏感性（成本、现金腿、PE 修订、信号断档），P0.5 是策略层安慰剂。
#
# 只读：数据库只 SELECT；结果写到 `var/research/erp_max_attribution/<run_id>/`，
# 并落一份 run log。第一步是复现断言：A、B、C 的仓位与收益必须与旧 run
# `bd015b89…` 逐日相等，否则停下。

# %%
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
from erp_lib import (
    asof_lookup,
    cash_accrual,
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

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# %% [markdown]
# ## 固定参数

# %%
AS_OF = date(2026, 11, 20)  # 研究截止日，固定以便复现
START = date(2002, 1, 1)
MAIN = "000985.CSI"
TR = "h00985.CSI"
US_STALE_DAYS = 7
PCT_YEARS = 5
PCT_YEARS_ALT = 6
BAND = 0.10
# 正好差 0.10 也调仓；留容差避免 0.7 - 0.6 < 0.1 的浮点误差。默认值即 erp_lib.ratchet 的默认。
BAND_TOL = 1e-9
# 2022 年首个 G > 0 日。看过数据后确定的，D 实验只作诊断。
TAU = pd.Timestamp("2022-04-12")
TAU_SHIFTS = (-126, -63, 0, 63, 126)
KAPPAS = (-0.5, 0.5)
VOL_TARGET = 0.12  # 波动率目标基准，事先写定（docs/research/erp-phase2-plan.md P0.3）
VOL_WINDOW = 60
NW_LAGS = 3  # 月频择时回归的 Newey-West 滞后期
POST_2024 = pd.Timestamp("2024-10-01")
SEED = 20261124
# P0.4 实施敏感性：单边成本（bp）、现金腿、PE 修订快照
COST_BPS = (0, 5, 10)
CASH_LEGS = ("cash_10y", "cash_0", "cash_ibo7d")
PE_GOLDEN = "tests/golden/market_data/erp_000985_wx2.json"
# P0.5 安慰剂：路径数、时间平移的最小位移与步长（交易日）
PLACEBO_N = 1000
SHIFT_MIN = 488
SHIFT_STEP = 21
# 复现基准：上一次运行（口径与本脚本一致）
OLD_RUN = "bd015b895ceb4b7096a84f71994a28cf"
# 原脚本 SUBPERIODS 原样拷贝
SUBPERIODS = {
    "2010-2014": ("2010-01-01", "2014-12-31"),
    "2015-2020": ("2015-01-01", "2020-12-31"),
    "2021-01..2024-09": ("2021-01-01", "2024-09-30"),
    "2024-10..": ("2024-10-01", "2099-12-31"),
}
PARAMS = {
    "as_of": AS_OF.isoformat(),
    "start": START.isoformat(),
    "main": MAIN,
    "total_return_index": TR,
    "us_stale_days": US_STALE_DAYS,
    "cash": "r_cn(prev trading day) / 100 * calendar_days / 365",
    "pct_years": PCT_YEARS,
    "pct_years_alt": PCT_YEARS_ALT,
    "band": BAND,
    "band_tol": BAND_TOL,
    "band_rule": "abs(desired - w) >= band - 1e-9",
    "tau": str(TAU.date()),
    "tau_shifts_trading_days": list(TAU_SHIFTS),
    "kappas": list(KAPPAS),
    "vol_target": VOL_TARGET,
    "vol_window": VOL_WINDOW,
    "nw_lags": NW_LAGS,
    "post_2024_from": str(POST_2024.date()),
    "seed": SEED,
    "cost_bps": list(COST_BPS),
    "cash_legs": list(CASH_LEGS),
    "placebo_n": PLACEBO_N,
    "shift_min": SHIFT_MIN,
    "shift_step": SHIFT_STEP,
    "old_run": f"research/erp_rate_anchor/{OLD_RUN}",
    "subperiods": SUBPERIODS,
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
# 与原脚本第一部分同口径：估值、中债、全收益指数是 `same_day_close`，美债严格早于
# as_of（7 天过期）。以研究截止日整段读一次，再按信号日切。

# %%
open_days = [
    d.cal_dt
    for d in calendar.list_days(as_of=AS_OF, exchange="SSE", start=START, end=AS_OF)
    if d.is_open
]
open_idx = pd.DatetimeIndex(open_days)
log(f"交易日 {len(open_days)}")

val_rows = valuations.list_valuations(
    as_of=AS_OF, start=START, end=AS_OF, wind_codes=(MAIN,)
)
pe = pd.Series(
    {
        pd.Timestamp(r.trade_dt): float(r.pe_ttm)
        for r in val_rows
        if r.wind_code == MAIN and r.pe_ttm is not None
    }
).sort_index()
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
    as_of=AS_OF, start=START, end=AS_OF, wind_codes=(TR,)
)
pct = pd.Series(
    {
        pd.Timestamp(r.trade_dt): (np.nan if r.pct_change is None else float(r.pct_change))
        for r in ret_rows
        if r.wind_code == TR
    }
).sort_index()
log(f"全收益行 {len(ret_rows)}")

# %% [markdown]
# ## 日频面板
#
# EY、r_CN 同日对齐；r_US 取观测日严格早于信号日的最近一期，过期超过 7 天即缺失。
# `M = EY − max(r_US, r_CN)`：任一利率缺失即缺失（np.maximum 传播 NaN）。

# %%
p_main = pe.reindex(open_idx)
ey = pd.Series(np.where(p_main > 0, 100.0 / p_main, np.nan), index=open_idx)
r_cn = r_cn_raw.reindex(open_idx)

us_cut = open_idx - pd.Timedelta(days=1)
vals, obs = asof_lookup(r_us_raw, us_cut)
stale = (us_cut - pd.DatetimeIndex(obs)) > pd.Timedelta(days=US_STALE_DAYS)
r_us = pd.Series(np.where(stale | pd.isna(obs), np.nan, vals), index=open_idx)
assert (pd.DatetimeIndex(obs)[r_us.notna().to_numpy()] < open_idx[r_us.notna().to_numpy()]).all()

V = ey - r_cn
U = ey - r_us
M = ey - np.maximum(r_us, r_cn)
G = r_us - r_cn
ret_d = pct.reindex(open_idx) / 100.0
cash = cash_accrual(r_cn)

daily = pd.DataFrame(
    {"ey": ey, "r_cn": r_cn, "r_us": r_us, "V": V, "U": U, "M": M, "G": G, "ret": ret_d, "cash": cash}
)
log(
    f"有效天数: EY {ey.notna().sum()} r_cn {r_cn.notna().sum()} r_us {r_us.notna().sum()} "
    f"G {G.notna().sum()} ret {ret_d.notna().sum()}"
)

# %% [markdown]
# ## 第一步：复现断言
#
# 共同起点不自己算，直接读旧 run 的 `strategy_V_cn_{5,6}y_lag1.csv` 第一行日期。
# 新旧 `w`、`turnover`、`ret` 三列必须逐位相等（NaN 位置也一致）。

# %%
old_dir = paths.root / "research" / "erp_rate_anchor" / OLD_RUN
if not old_dir.is_dir():
    raise RuntimeError(f"旧 run 目录不存在：{old_dir}")


def read_old(name: str) -> pd.DataFrame:
    return pd.read_csv(
        old_dir / f"strategy_{name}.csv",
        index_col=0,
        parse_dates=True,
        float_precision="round_trip",
    )


def assert_identical(new: pd.Series, old: pd.Series, label: str) -> int:
    """逐位相等：索引、NaN 位置、数值都相同（atol=rtol=0）。返回比较点数。"""
    if not new.index.equals(old.index):
        raise AssertionError(f"{label}: 索引不一致（新 {len(new)} 行 / 旧 {len(old)} 行）")
    a, b = new.to_numpy(dtype=float), old.to_numpy(dtype=float)
    if not np.array_equal(np.isnan(a), np.isnan(b)):
        raise AssertionError(f"{label}: NaN 位置不一致")
    if not np.allclose(a, b, rtol=0, atol=0, equal_nan=True):
        bad = np.flatnonzero(~((a == b) | (np.isnan(a) & np.isnan(b))))
        raise AssertionError(f"{label}: 数值不一致，首个差异 {new.index[bad[0]].date()}")
    return len(a)


PCTS = {PCT_YEARS: {}, PCT_YEARS_ALT: {}}
SPREAD = {"Max_us_cn": M, "V_cn": V, "U_us": U}
runs: dict[tuple[int, str], pd.DataFrame] = {}
window: dict[int, dict[str, pd.Series | pd.Timestamp]] = {}
for years in (PCT_YEARS, PCT_YEARS_ALT):
    for name, spread in SPREAD.items():
        PCTS[years][name] = rolling_percentile(spread, years)

repro_rows = []
for years in (PCT_YEARS, PCT_YEARS_ALT):
    starts = {name: read_old(f"{name}_{years}y_lag1").index[0] for name in SPREAD}
    if len(set(starts.values())) != 1:
        raise AssertionError(f"{years} 年窗口的旧 run 起点不一致：{starts}")
    start = next(iter(starts.values()))
    ret_w, cash_w = ret_d.loc[start:], cash.loc[start:]
    window[years] = {"start": start, "ret": ret_w, "cash": cash_w}
    for name in SPREAD:
        old = read_old(f"{name}_{years}y_lag1")
        run = ratchet(
            PCTS[years][name].loc[start:], ret_w, lag=1, cash=cash_w, return_target=True
        )
        n = max(assert_identical(run[col], old[col], f"{name} {years}y {col}")
                for col in ("w", "turnover", "ret"))
        runs[(years, name)] = run
        repro_rows.append(
            {"pct_years": years, "signal": name, "start": str(start.date()), "rows": n,
             "equal_w": True, "equal_turnover": True, "equal_ret": True}
        )
repro = pd.DataFrame(repro_rows)
log("复现断言通过：A/B/C 的 w、turnover、ret 与旧 run 逐位相等（atol=rtol=0，NaN 位置一致）")
print(repro.to_string(index=False))

START5, START6 = window[PCT_YEARS]["start"], window[PCT_YEARS_ALT]["start"]
RET5, CASH5 = window[PCT_YEARS]["ret"], window[PCT_YEARS]["cash"]
IDX5 = RET5.index
RUN_A, RUN_B, RUN_C = (runs[(PCT_YEARS, "Max_us_cn")], runs[(PCT_YEARS, "V_cn")],
                       runs[(PCT_YEARS, "U_us")])
log(f"5 年窗口 {START5.date()}..{IDX5[-1].date()}，{len(IDX5)} 个交易日；"
    f"6 年窗口起点 {START6.date()}")

# %% [markdown]
# ## P0.1 逐日精确归因
#
# 同一现金腿、不计成本时 `r_A − r_B = (w_A,t−1 − w_B,t−1)(R_t − c_t)` 是恒等式。
# 先断言，再用它拆贡献。

# %%
for years in (PCT_YEARS, PCT_YEARS_ALT):
    ra, rb, rc = (runs[(years, "Max_us_cn")], runs[(years, "V_cn")], runs[(years, "U_us")])
    for tag, other in (("A-B", rb), ("A-C", rc)):
        d = (ra["w"] - other["w"]).shift(1) * (window[years]["ret"] - window[years]["cash"])
        diff = (ra["ret"] - other["ret"] - d).abs()
        if not diff.max() < 1e-12:
            raise RuntimeError(f"{years} 年 {tag} 归因恒等式不成立：最大误差 {diff.max()}")
        log(f"恒等式 {years}y {tag}: 最大绝对误差 {diff.max():.3e}")


def pair_stats(d: pd.Series, ra: pd.Series, rb: pd.Series) -> dict[str, float]:
    """算术 Σd、ln NAV 差、复利项（两者之差）、τ 以后的 Σd 占比。"""
    ln_diff = float(np.log((1 + ra.dropna()).prod()) - np.log((1 + rb.dropna()).prod()))
    total = float(d.sum())
    post = float(d[d.index >= TAU].sum())
    return {
        "sum_d": total,
        "ln_nav_diff": ln_diff,
        "compounding": ln_diff - total,
        "share_post_tau": post / total if total != 0 else np.nan,
    }


def events_of(diff: pd.Series, d: pd.Series) -> pd.DataFrame:
    """事件 = `wprev_A − wprev_B` 符号不变且 |差| > 1e-9 的最长连续区间。

    缺失日与|差|≤1e-9 的日子都不是事件的一部分，也会打断区间（不跨缺口合并）。
    """
    sign = np.sign(diff.where(diff.abs() > 1e-9))
    s = sign.to_numpy(dtype=float)
    grp = np.full(len(s), -1, dtype=int)
    cur, prev = 0, None
    for i, v in enumerate(s):
        if np.isnan(v):
            prev = None
            continue
        if prev is None or v != prev:
            cur += 1
        grp[i] = cur
        prev = v
    rows = []
    for k in range(1, cur + 1):
        mask = grp == k
        if not mask.any():
            continue
        seg = d[mask]
        rows.append(
            {"start": seg.index[0], "end": seg.index[-1], "days": len(seg),
             "avg_diff": float(diff[mask].mean()), "sum_d": float(seg.sum())}
        )
    return pd.DataFrame(rows).sort_values("sum_d", ascending=False).reset_index(drop=True)


def window_components(years: int) -> dict:
    """一个分位窗口下的 A/B/C 回测、逐日仓位差与贡献。"""
    ra, rb, rc = runs[(years, "Max_us_cn")], runs[(years, "V_cn")], runs[(years, "U_us")]
    ret_w, cash_w = window[years]["ret"], window[years]["cash"]
    w_a = ra["w"].shift(1)
    excess = ret_w - cash_w
    d_ab = (w_a - rb["w"].shift(1)) * excess
    d_ac = (w_a - rc["w"].shift(1)) * excess
    return {
        "years": years, "runs": (ra, rb, rc), "ret": ret_w, "cash": cash_w,
        "w_a": w_a, "excess": excess, "d_ab": d_ab, "d_ac": d_ac,
        "events_ab": events_of(w_a - rb["w"].shift(1), d_ab),
        "events_ac": events_of(w_a - rc["w"].shift(1), d_ac),
    }


COMPS = {years: window_components(years) for years in (PCT_YEARS, PCT_YEARS_ALT)}
summary_rows = []
for years, c in COMPS.items():
    ra, rb, rc = c["runs"]
    # A 相对买入持有的机会成本：Σ (w_A,t−1 − 1)(R_t − c_t)
    post_bh = float((c["w_a"] - 1.0).loc[POST_2024:].mul(c["excess"].loc[POST_2024:]).sum())
    for pair, d, other, ev in (
        ("AB", c["d_ab"], rb, c["events_ab"]),
        ("AC", c["d_ac"], rc, c["events_ac"]),
    ):
        row = {"window": f"{years}y", "pair": pair} | pair_stats(d, ra["ret"], other["ret"])
        row |= {
            "n_events": len(ev),
            # 前 k 个事件的 Σd 之和 / 全区间净 Σd（零差日与缺失日不在事件内，故分母是净额）
            "top1_share": ev["sum_d"].iloc[0] / row["sum_d"] if len(ev) else np.nan,
            "top3_share": ev["sum_d"].head(3).sum() / row["sum_d"] if len(ev) else np.nan,
            "post_2024_10_sum_d_ab": float(c["d_ab"].loc[POST_2024:].sum()),
            "post_2024_10_sum_d_ac": float(c["d_ac"].loc[POST_2024:].sum()),
            "post_2024_10_sum_d_a_vs_bh": post_bh,
        }
        summary_rows.append(row)
p01_summary = pd.DataFrame(summary_rows)

D_AB, D_AC = COMPS[PCT_YEARS]["d_ab"], COMPS[PCT_YEARS]["d_ac"]
p01_events_out = pd.concat(
    [
        COMPS[PCT_YEARS]["events_ab"].assign(pair="AB"),
        COMPS[PCT_YEARS]["events_ac"].assign(pair="AC"),
    ],
    ignore_index=True,
)
p01_events_out["start"] = p01_events_out["start"].dt.date.astype(str)
p01_events_out["end"] = p01_events_out["end"].dt.date.astype(str)
print("复现起点:", str(START5.date()), "| τ =", str(TAU.date()))
print(p01_summary.round(4).to_string(index=False))

G5 = G.reindex(IDX5)
p01_daily = pd.DataFrame(
    {
        "ret": RET5,
        "cash": CASH5,
        "G": G5,
        "g_positive": np.where(G5.isna(), np.nan, (G5 > 0).astype(float)),
    }
)
for tag, name, spread in (
    ("a", "Max_us_cn", M),
    ("b", "V_cn", V),
    ("c", "U_us", U),
):
    p01_daily[f"{tag}_signal"] = spread.reindex(IDX5)
    p01_daily[f"{tag}_pct"] = PCTS[PCT_YEARS][name].reindex(IDX5)
    for col in ("target", "w", "turnover", "ret"):
        p01_daily[f"{tag}_{col}"] = runs[(PCT_YEARS, name)][col].reindex(IDX5)
p01_daily["d_ab"] = D_AB
p01_daily["d_ac"] = D_AC
p01_daily["cum_d_ab"] = D_AB.cumsum()
p01_daily["cum_d_ac"] = D_AC.cumsum()
p01_daily = p01_daily.reset_index(names="trade_dt")
print(p01_daily.head(3).round(4).to_string(index=False))

p01_by_year = pd.DataFrame(
    {
        "days": D_AB.notna().groupby(D_AB.index.year).sum(),
        "sum_d_ab": D_AB.groupby(D_AB.index.year).sum(),
        "sum_d_ac": D_AC.groupby(D_AC.index.year).sum(),
    }
).reset_index(names="year")
# C − B = (A−B) − (A−C)：两条差额序列按年算术相减
p01_by_year["sum_d_cb"] = p01_by_year["sum_d_ab"] - p01_by_year["sum_d_ac"]
print(p01_by_year.round(4).to_string(index=False))

state = pd.Series(
    np.where(G5.isna(), "G_missing", np.where(G5 > 0, "G>0", "G<=0")),
    index=IDX5,
    name="state",
)
p01_by_state = pd.DataFrame(
    {
        "state": ["G>0", "G<=0", "G_missing"],
    }
).assign(
    days=lambda f: [int(D_AB[state == s].notna().sum()) for s in f["state"]],
    sum_d_ab=lambda f: [float(D_AB[state == s].sum()) for s in f["state"]],
    sum_d_ac=lambda f: [float(D_AC[state == s].sum()) for s in f["state"]],
    avg_g=lambda f: [float(G5[state == s].mean()) for s in f["state"]],
)
print(p01_by_state.round(4).to_string(index=False))

seg_rows = []
for seg, (a, b) in SUBPERIODS.items():
    d_ab_s, d_ac_s = D_AB.loc[a:b], D_AC.loc[a:b]
    seg_rows.append(
        {
            "segment": seg,
            "days": int(d_ab_s.notna().sum()),
            "sum_d_ab": float(d_ab_s.sum()),
            "sum_d_ac": float(d_ac_s.sum()),
            "avg_w_a": float(RUN_A["w"].loc[a:b].mean()),
            "avg_w_b": float(RUN_B["w"].loc[a:b].mean()),
            "avg_w_c": float(RUN_C["w"].loc[a:b].mean()),
        }
    )
p01_by_segment = pd.DataFrame(seg_rows)
# C − B = (A−B) − (A−C)，与 p01_by_year 同口径
p01_by_segment["sum_d_cb"] = p01_by_segment["sum_d_ab"] - p01_by_segment["sum_d_ac"]
print(p01_by_segment.round(4).to_string(index=False))

print("事件表（AB / AC 各前 10 行，按 Σd 降序）:")
print(
    p01_events_out.groupby("pair", sort=False).head(10).round(4).to_string(index=False)
)

p01_trades = pd.DataFrame(
    {
        "turnover_a": RUN_A["turnover"],
        "turnover_b": RUN_B["turnover"],
        "turnover_c": RUN_C["turnover"],
        "w_a": RUN_A["w"],
        "w_b": RUN_B["w"],
        "w_c": RUN_C["w"],
        "dw_a": RUN_A["w"].diff(),
        "dw_b": RUN_B["w"].diff(),
        "dw_c": RUN_C["w"].diff(),
    }
)
p01_trades = p01_trades[
    (p01_trades["turnover_a"] > 0) | (p01_trades["turnover_b"] > 0) | (p01_trades["turnover_c"] > 0)
].reset_index(names="trade_dt")
log(f"调仓日 {len(p01_trades)} 天")

# %% [markdown]
# ## P0.2 机制实验
#
# 每次只改一处，其余与 A 相同；比较区间都从 A 的起点开始，lag=1，现金同 P0.1。

# %%
BASE_SUM_AB = float(p01_summary.loc[(p01_summary["window"] == "5y") & (p01_summary["pair"] == "AB"),
                                    "sum_d"].iloc[0])
exp_rows = []


def exp_stats(run: pd.DataFrame, label: str, param: str, index: pd.DatetimeIndex | None = None) -> dict:
    """一个实验变体的绩效与相对 B、C 的 Σd（按日 ret 差累加）。"""
    idx = IDX5 if index is None else index
    r = run["ret"].reindex(idx)
    perf = perf_daily(r, run.reindex(idx), rf=CASH5)
    sum_b = float((r - RUN_B["ret"].reindex(idx)).sum())
    return {
        "experiment": label,
        "param": param,
        "ann_return": perf["ann_return"],
        "ann_vol": perf["ann_vol"],
        "sharpe_excess": perf["sharpe_excess"],
        "max_dd": perf["max_dd"],
        "avg_w": perf["avg_w"],
        "sum_d_vs_B": sum_b,
        "sum_d_vs_C": float((r - RUN_C["ret"].reindex(idx)).sum()),
        "ratio_vs_baseline_ab": sum_b / BASE_SUM_AB,
    }


# D：τ 之前用 V、τ 起用 U，一次切换。τ 是看过数据后定的，只作诊断。
tau_pos = int(open_idx.searchsorted(TAU))
if open_idx[tau_pos] != TAU:
    raise RuntimeError(f"TAU={TAU.date()} 不是交易日，D 实验的切换点无法定义")
for shift in TAU_SHIFTS:
    tau = open_idx[tau_pos + shift]
    sig_d = rolling_percentile(pd.Series(np.where(open_idx < tau, V, U), index=open_idx), PCT_YEARS)
    run_d = ratchet(sig_d.loc[START5:], RET5, lag=1, cash=CASH5)
    exp_rows.append(exp_stats(run_d, f"D_tau{shift:+d}", f"tau={tau.date()}"))

# E：分位按状态取，G > 0 用 U 的历史分位，G <= 0 用 V 的，G 缺失则无目标。
sig_e = pd.Series(
    np.where(G > 0, PCTS[PCT_YEARS]["U_us"], np.where(G <= 0, PCTS[PCT_YEARS]["V_cn"], np.nan)),
    index=open_idx,
)
run_e = ratchet(sig_e.loc[START5:], RET5, lag=1, cash=CASH5)
exp_rows.append(exp_stats(run_e, "E_state_pct", "G>0:U_pct / G<=0:V_pct"))

# H：从 τ 起用 C 的目标仓位，初始仓位是 A 在 τ 前一日的仓位。
pos_tau = int(IDX5.get_loc(TAU))
w0_h = float(RUN_A["w"].iloc[pos_tau - 1])
ret_h, cash_h = RET5.loc[TAU:], CASH5.loc[TAU:]
run_h = ratchet(
    PCTS[PCT_YEARS]["U_us"].loc[TAU:], ret_h, lag=1, cash=cash_h, w0=w0_h, return_target=True
)
# w0 语义自检：H 在 τ 当日的收益就是 A 那天用同一持仓算出的收益
if not np.allclose(run_h["ret"].iloc[0], RUN_A["ret"].loc[TAU], rtol=0, atol=0):
    raise RuntimeError(f"H 首日收益与 A 不一致：{run_h['ret'].iloc[0]} vs {RUN_A['ret'].loc[TAU]}")
log(f"H 首日收益与 A 逐位相等（w0={w0_h:.4f}）：{run_h['ret'].iloc[0]:.10f}")
sum_ah = float((RUN_A["ret"].reindex(ret_h.index) - run_h["ret"]).sum())
sum_hc = float((run_h["ret"] - RUN_C["ret"].reindex(ret_h.index)).sum())
sum_ac_post = float((RUN_A["ret"].reindex(ret_h.index) - RUN_C["ret"].reindex(ret_h.index)).sum())
if not abs(sum_ah + sum_hc - sum_ac_post) < 1e-12:
    raise RuntimeError(f"H 分解不闭合：{sum_ah} + {sum_hc} != {sum_ac_post}")
log(f"H 分解（τ 以后）: Σ(A−H)={sum_ah:.6f} + Σ(H−C)={sum_hc:.6f} = Σ(A−C)={sum_ac_post:.6f}")
row_h = exp_stats(run_h, "H_from_tau", f"w0={w0_h:.4f} @ {IDX5[pos_tau - 1].date()}", index=ret_h.index)
row_h |= {"sum_d_a_vs_h": sum_ah, "sum_d_h_vs_c": sum_hc, "sum_d_a_vs_c": sum_ac_post}
exp_rows.append(row_h)

# F1/F2/F3：仓位规则。F1 去掉单向约束，F2 去掉 0.10 阈值，F3 两者都去掉。
F_VARIANTS = {
    "F1_no_one_way": {"one_way": False},
    "F2_no_band": {"band": 0.0},
    "F3_no_one_way_no_band": {"one_way": False, "band": 0.0},
}
for label, kw in F_VARIANTS.items():
    f_runs = {}
    for tag, name in (("A", "Max_us_cn"), ("B", "V_cn"), ("C", "U_us")):
        f_runs[tag] = ratchet(PCTS[PCT_YEARS][name].loc[START5:], RET5, lag=1, cash=CASH5, **kw)
    # 同一规则下重新定义 A−B、A−C，与相对基线的 Σd 分开报，两种读法都能查
    sum_ab = float((f_runs["A"]["ret"] - f_runs["B"]["ret"]).sum())
    sum_ac = float((f_runs["A"]["ret"] - f_runs["C"]["ret"]).sum())
    for tag in ("A", "B", "C"):
        exp_rows.append(
            exp_stats(f_runs[tag], f"{label}_{tag}", json.dumps(kw))
            | {"sum_d_ab_same_rule": sum_ab, "sum_d_ac_same_rule": sum_ac}
        )
        if label.startswith("F3"):
            exp_rows[-1]["f3_ratio"] = sum_ab / BASE_SUM_AB

# G：只在每月最后一个交易日更新目标，其余置 NaN（不前向填充）。
month = open_idx.to_period("M")
last_of_month = pd.Series(open_idx, index=month).groupby(level=0).max()
keep = open_idx.isin(pd.DatetimeIndex(last_of_month.to_numpy()))
for tag, name in (("A", "Max_us_cn"), ("B", "V_cn"), ("C", "U_us")):
    run_g = ratchet(PCTS[PCT_YEARS][name].where(keep).loc[START5:], RET5, lag=1, cash=CASH5)
    exp_rows.append(exp_stats(run_g, f"G_monthly_{tag}", "last trading day of month, no ffill"))
# 同规则（都改月频）的 A−B、A−C：exp_stats 的 sum_d_vs_B/C 都相对同一条基线 B/C，
# 相减即得同规则差额（算术可加）。三行同值，便于直接和 F1/F2/F3 的列对比。
_g_a, _g_b, _g_c = exp_rows[-3:]
for _row in (_g_a, _g_b, _g_c):
    _row["sum_d_ab_same_rule"] = _g_a["sum_d_vs_B"] - _g_b["sum_d_vs_B"]
    _row["sum_d_ac_same_rule"] = _g_a["sum_d_vs_C"] - _g_c["sum_d_vs_C"]

# κ：S = V − max(G − κ, 0)，κ = ∓0.5 个百分点。
for kappa in KAPPAS:
    s_k = V - np.maximum(G - kappa, 0.0)
    run_k = ratchet(rolling_percentile(s_k, PCT_YEARS).loc[START5:], RET5, lag=1, cash=CASH5)
    exp_rows.append(exp_stats(run_k, f"kappa{kappa:+.1f}", f"S = V - max(G - ({kappa}), 0)"))

p02_experiments = pd.DataFrame(exp_rows)
print("基线 Σd_AB（5y）=", round(BASE_SUM_AB, 6), "| H 分解闭合已断言")
f3 = p02_experiments[p02_experiments["experiment"].str.startswith("F3")]
log(
    "f3_ratio（F3 同规则 Σd_AB / 基线 Σd_AB）= "
    f"{float(f3['sum_d_ab_same_rule'].iloc[0]) / BASE_SUM_AB:.4f}；"
    f"F3_A 相对基线 B 的比值 = {float(f3.loc[f3['experiment'] == 'F3_no_one_way_no_band_A', 'ratio_vs_baseline_ab'].iloc[0]):.4f}"
)
print(p02_experiments.round(4).to_string(index=False))

# %% [markdown]
# ## P0.3 控制仓位差异
#
# 月收益由日收益复利；择时回归用月度超额收益，Newey-West 滞后期 3。

# %%
mret = {}
for tag, run in (("A", RUN_A), ("B", RUN_B), ("C", RUN_C)):
    r = run["ret"].dropna()
    mret[tag] = (1 + r).groupby(r.index.to_period("M")).prod() - 1
bh_d = RET5.iloc[1:]  # 首日策略无收益，买入持有同区间
mret["BH"] = (1 + bh_d).groupby(bh_d.index.to_period("M")).prod() - 1
cash_ok = CASH5.dropna()
mret["cash"] = (1 + cash_ok).groupby(cash_ok.index.to_period("M")).prod() - 1
monthly = pd.DataFrame(mret)
ex_m = monthly["BH"] - monthly["cash"]
X_MODELS = {
    "CAPM": pd.DataFrame({"ex_m": ex_m}),
    "TM": pd.DataFrame({"ex_m": ex_m, "ex_m2": ex_m**2}),
    "HM": pd.DataFrame({"ex_m": ex_m, "ex_m_pos": ex_m.clip(lower=0.0)}),
}
timing_rows = []
for tag in ("A", "B", "C"):
    ex_s = monthly[tag] - monthly["cash"]
    for model, x in X_MODELS.items():
        fit, n = nw_ols(ex_s, x, NW_LAGS)
        row = {"strategy": tag, "model": model, "n": n}
        for var in ("const", *x.columns):
            row[f"coef_{var}"] = float(fit.params[var])
            row[f"t_{var}"] = float(fit.tvalues[var])
        row["alpha_ann"] = float(fit.params["const"]) * 12
        row["r2"] = float(fit.rsquared)
        timing_rows.append(row)
p03_timing = pd.DataFrame(timing_rows)
print(p03_timing.round(4).to_string(index=False))

bench_rows = []
for tag, run in (("A", RUN_A), ("B", RUN_B), ("C", RUN_C)):
    w_bar = float(run["w"].mean())
    r_fix = ratchet(
        pd.Series(w_bar, index=IDX5), RET5, lag=1, cash=CASH5, one_way=False, band=0.0
    )
    bench_rows.append(
        {"benchmark": f"fixed_w_{tag}", "target_w": w_bar, "target_rule": "constant, daily rebalance"}
        | perf_daily(r_fix["ret"], r_fix, rf=CASH5)
    )
sigma60 = RET5.rolling(VOL_WINDOW).std() * np.sqrt(244)
vol_target = (VOL_TARGET / sigma60).clip(upper=1.0)
r_vol = ratchet(vol_target, RET5, lag=1, cash=CASH5, one_way=False)
bench_rows.append(
    {"benchmark": "vol_target_12pct", "target_w": float(vol_target.mean()),
     "target_rule": f"min(1, {VOL_TARGET} / sigma{VOL_WINDOW}), band 0.10, no one-way"}
    | perf_daily(r_vol["ret"], r_vol, rf=CASH5)
)
p03_benchmarks = pd.DataFrame(bench_rows)
print(p03_benchmarks.round(4).to_string(index=False))

# %% [markdown]
# ## P0.4 实施敏感性
#
# 三条单边成本、三条现金腿、一次 PE 修订重跑，另报信号断档。成本按成交日扣：
# `ret_net = ret − c/1e4 × turnover`。买入持有满仓全收益指数、只在首日建仓，不计成本。
#
# 现金腿换的是现金流，目标序列与仓位规则不变；但现金同时进入当日收益和仓位漂移，
# 所以每条腿都要用新 cash 重跑 ratchet（包括主口径 `cash_10y`，它必须逐位复现基线）。

# %%
STAT_B = perf_daily(RUN_B["ret"], RUN_B, rf=CASH5)["sharpe_excess"]

# 买入持有：满仓全收益指数，首日无收益（与 P0.3 的 BH 同口径），不计建仓成本。
bh_ret = RET5.copy()
bh_ret.iloc[0] = np.nan
BH_RUN = pd.DataFrame({"w": 1.0, "turnover": 0.0, "ret": bh_ret})

cost_rows = []
for bps in COST_BPS:
    fee = bps / 1e4
    net = {
        tag: run["ret"] - fee * run["turnover"]
        for tag, run in (("A", RUN_A), ("B", RUN_B), ("C", RUN_C))
    }
    sum_ab = float((net["A"] - net["B"]).sum())
    sum_ac = float((net["A"] - net["C"]).sum())
    if bps == 0 and abs(sum_ab - BASE_SUM_AB) > 1e-12:
        raise RuntimeError(f"0bp 的 Σ(A−B) 与 P0.1 基线不一致：{sum_ab} vs {BASE_SUM_AB}")
    for tag in ("A", "B", "C"):
        perf = perf_daily(net[tag], None, rf=CASH5)
        cost_rows.append(
            {"strategy": tag, "cost_bps": bps, "ann_return": perf["ann_return"],
             "ann_vol": perf["ann_vol"], "sharpe_excess": perf["sharpe_excess"],
             "max_dd": perf["max_dd"], "sum_d_ab_net": sum_ab, "sum_d_ac_net": sum_ac}
        )
    perf_bh = perf_daily(BH_RUN["ret"], None, rf=CASH5)
    cost_rows.append(
        {"strategy": "BH", "cost_bps": bps, "ann_return": perf_bh["ann_return"],
         "ann_vol": perf_bh["ann_vol"], "sharpe_excess": perf_bh["sharpe_excess"],
         "max_dd": perf_bh["max_dd"], "sum_d_ab_net": np.nan, "sum_d_ac_net": np.nan}
    )
p04_costs = pd.DataFrame(cost_rows)
print("P0.4 成本敏感性（净收益口径）:")
print(p04_costs.round(4).to_string(index=False))

# %% [markdown]
# 现金腿：`cash_10y` 是主口径，`cash_0` 全零，`cash_ibo7d` 用同业拆借 7 天。

# %%
ibo_rows = macro.list_observations(as_of=AS_OF, start=START, end=AS_OF, series_ids=("cn_ibo_7d",))
ibo = pd.Series(
    {
        pd.Timestamp(r.observation_date): (np.nan if r.value is None else float(r.value))
        for r in ibo_rows
    }
).sort_index()
log(f"ibo7d {len(ibo)} 行 {ibo.index[0].date()}..{ibo.index[-1].date()}")
# cn_ibo_7d 是日频、每个观测只有一个版本、发布当天可见，所以 as_of=AS_OF 整段读一次
# 与逐日传 as_of 读等价：任何观测在任何信号日上取到的都是同一个版本。
vals_ibo, obs_ibo = asof_lookup(ibo.dropna(), open_idx)
stale_ibo = (open_idx - pd.DatetimeIndex(obs_ibo)) > pd.Timedelta(days=US_STALE_DAYS)
ibo_aligned = pd.Series(np.where(stale_ibo | pd.isna(obs_ibo), np.nan, vals_ibo), index=open_idx)
CASH_IBO = cash_accrual(ibo_aligned)
# 持仓期间缺现金利率时 ratchet 会 raise；先查一遍并把缺失日期报出来，不填充。
# 首日必然缺（cash 取上一交易日），而首日还没有持仓，不算。
_gap = CASH_IBO.reindex(IDX5).iloc[1:]
_gap = _gap[_gap.isna()]
if len(_gap):
    raise RuntimeError(
        f"ibo7d 现金腿在持仓期间缺失 {len(_gap)} 天：{[str(d.date()) for d in _gap.index]}"
    )
log(f"ibo7d 对齐后缺失 {int(ibo_aligned.reindex(IDX5).isna().sum())} 天（含首日）")

CASH_BY_LEG = {
    "cash_10y": CASH5,
    "cash_0": pd.Series(0.0, index=IDX5),
    "cash_ibo7d": CASH_IBO.reindex(IDX5),
}
cash_rows = []
for leg in CASH_LEGS:
    cash_leg = CASH_BY_LEG[leg]
    leg_runs = {
        tag: ratchet(PCTS[PCT_YEARS][name].loc[START5:], RET5, lag=1, cash=cash_leg)
        for tag, name in (("A", "Max_us_cn"), ("B", "V_cn"), ("C", "U_us"))
    }
    if leg == "cash_10y":
        for tag, name in (("A", "Max_us_cn"), ("B", "V_cn"), ("C", "U_us")):
            base = runs[(PCT_YEARS, name)]
            for col in ("w", "turnover", "ret"):
                assert_identical(leg_runs[tag][col], base[col], f"cash_10y {tag} {col}")
    sum_ab = float((leg_runs["A"]["ret"] - leg_runs["B"]["ret"]).sum())
    sum_ac = float((leg_runs["A"]["ret"] - leg_runs["C"]["ret"]).sum())
    for tag in ("A", "B", "C"):
        perf = perf_daily(leg_runs[tag]["ret"], leg_runs[tag], rf=cash_leg)
        cash_rows.append(
            {"leg": leg, "strategy": tag, "ann_return": perf["ann_return"],
             "ann_vol": perf["ann_vol"], "sharpe_excess": perf["sharpe_excess"],
             "max_dd": perf["max_dd"], "avg_w": perf["avg_w"],
             "sum_d_ab": sum_ab, "sum_d_ac": sum_ac}
        )
    perf_bh = perf_daily(BH_RUN["ret"], BH_RUN, rf=cash_leg)
    cash_rows.append(
        {"leg": leg, "strategy": "BH", "ann_return": perf_bh["ann_return"],
         "ann_vol": perf_bh["ann_vol"], "sharpe_excess": perf_bh["sharpe_excess"],
         "max_dd": perf_bh["max_dd"], "avg_w": perf_bh["avg_w"],
         "sum_d_ab": np.nan, "sum_d_ac": np.nan}
    )
p04_cash = pd.DataFrame(cash_rows)
log("cash_10y 腿逐位复现基线 A/B/C 的 w、turnover、ret")
print("P0.4 现金腿（rf 用同一条 cash）:")
print(p04_cash.round(4).to_string(index=False))

# %% [markdown]
# PE 修订：golden 快照里的 `revised` 是 Wind 修过、旧快照仍是修订前值的日期。
# 把这些日期的 PE 换回 wx2 值，其余不变，重算 ey、V、U、M、5 年分位与 ratchet。

# %%
revised = json.loads((detect_repo_root() / PE_GOLDEN).read_text(encoding="utf-8"))["revised"]
rev_map = {
    pd.Timestamp(f"{k[:4]}-{k[4:6]}-{k[6:]}"): float(v["wx2_pe_ttm"]) for k, v in revised.items()
}
pe_rev = pe.copy()
_hit = [d for d in sorted(rev_map) if d in pe_rev.index]
pe_rev.update(pd.Series({d: rev_map[d] for d in _hit}))
log(
    f"PE 修订登记 {len(rev_map)} 天，换回 {len(_hit)} 天，"
    f"其中 5 年窗口内 {sum(1 for d in _hit if d >= START5)} 天"
)

ey_rev = pd.Series(np.where(pe_rev.reindex(open_idx) > 0, 100.0 / pe_rev.reindex(open_idx), np.nan),
                   index=open_idx)
SPREAD_REV = {
    "Max_us_cn": ey_rev - np.maximum(r_us, r_cn),
    "V_cn": ey_rev - r_cn,
    "U_us": ey_rev - r_us,
}
rev_rows = []
for tag, name in (("A", "Max_us_cn"), ("B", "V_cn"), ("C", "U_us")):
    run_rev = ratchet(
        rolling_percentile(SPREAD_REV[name], PCT_YEARS).loc[START5:], RET5, lag=1, cash=CASH5
    )
    base = runs[(PCT_YEARS, name)]
    perf = perf_daily(run_rev["ret"], run_rev, rf=CASH5)
    w_diff = (run_rev["w"].isna() != base["w"].isna()) | (
        (run_rev["w"] - base["w"]).abs() > 1e-12
    )
    rev_rows.append(
        {"strategy": tag, "days_replaced_file": len(rev_map), "days_replaced_in_data": len(_hit),
         "days_replaced_in_window": sum(1 for d in _hit if d >= START5),
         "ann_return": perf["ann_return"], "ann_vol": perf["ann_vol"],
         "sharpe_excess": perf["sharpe_excess"], "max_dd": perf["max_dd"],
         "sum_d_ret_vs_base": float((run_rev["ret"] - base["ret"]).sum()),
         "w_diff_days": int(w_diff.sum())}
    )
p04_pe_revision = pd.DataFrame(rev_rows)
print("P0.4 PE 修订（换回修订前值）:")
print(p04_pe_revision.round(4).to_string(index=False))

# %% [markdown]
# 信号断档：A 的起点之后，缺信号的日子仓位不动，报告这些天里冻住的仓位带来的收益。

# %%

def nan_run(mask: pd.Series) -> tuple[int, str, str]:
    """最长连续 True 区间的长度与起止日；没有 True 时返回 (0, "", "")。"""
    best, cur, start = 0, 0, None
    best_start = best_end = ""
    for d, flag in mask.items():
        if flag:
            if cur == 0:
                start = d
            cur += 1
            if cur > best:
                best, best_start, best_end = cur, str(start.date()), str(d.date())
        else:
            cur = 0
    return best, best_start, best_end


miss_rows = []
for tag, sig, run in (("M", M, RUN_A), ("V", V, RUN_B), ("U", U, RUN_C)):
    nan_mask = sig.reindex(IDX5).isna()
    contrib = (run["w"].shift(1) * (RET5 - CASH5))[nan_mask]
    length, first, last = nan_run(nan_mask)
    miss_rows.append(
        {"signal": tag, "nan_days": int(nan_mask.sum()), "longest_run_days": length,
         "run_start": first, "run_end": last, "sum_contrib": float(contrib.sum())}
    )
# r_us 的 7 天过期规则：过期即缺失，U、M 随之缺失。
us_nan = r_us.reindex(IDX5).isna()
length, first, last = nan_run(us_nan)
miss_rows.append(
    {"signal": "r_us(stale>7d)", "nan_days": int(us_nan.sum()), "longest_run_days": length,
     "run_start": first, "run_end": last, "sum_contrib": np.nan}
)
p04_missing = pd.DataFrame(miss_rows)
log(f"r_us 全样本（{open_idx[0].date()} 起）按 7 天过期规则缺失 {int(r_us.isna().sum())} 天")
print("P0.4 信号断档（A 的起点之后）:")
print(p04_missing.round(4).to_string(index=False))

# %% [markdown]
# ## P0.5 策略层安慰剂
#
# `V`、`ret`、`cash`（10Y）、起点、B 的基线结果都不动，只把 G 换成与 A 股无关的序列，
# 再走完整流程：`M_sim = V − max(G_sim, 0)`、`U_sim = V − G_sim` → 5 年分位 → ratchet。
# 统计量 `stat = sharpe_excess(X) − sharpe_excess(B)`。

# %%
# AR(1)：相邻两日都非 NaN 的样本 OLS，σ 为残差标准差（ddof=2）。
_fit_mask = G.notna() & G.shift(1).notna()
_y = G[_fit_mask].to_numpy(dtype=float)
_x = G.shift(1)[_fit_mask].to_numpy(dtype=float)
_xm = np.column_stack([np.ones_like(_x), _x])
_beta = np.linalg.lstsq(_xm, _y, rcond=None)[0]
AR1_C, AR1_PHI = float(_beta[0]), float(_beta[1])
_resid = _y - _xm @ _beta
AR1_SIGMA = float(np.sqrt(_resid @ _resid / (len(_y) - 2)))
log(f"AR(1) 拟合: n={len(_y)} c={AR1_C:.6f} phi={AR1_PHI:.6f} sigma={AR1_SIGMA:.6f}")

G_SEG = G.loc[G.first_valid_index() :]
SEG_IDX = G_SEG.index
SEG_NAN = G_SEG.isna().to_numpy()
POST = np.asarray(SEG_IDX >= START5)
V_SEG = V.reindex(SEG_IDX)


def placebo_stats(gs: pd.Series) -> dict[str, float]:
    """一条 G 路径跑完分位 → ratchet → 统计量，返回 M/U 的 stat 与 Σd（相对基线 B）。"""
    out: dict[str, float] = {}
    for tag, spread in (("M", V_SEG - np.maximum(gs, 0.0)), ("U", V_SEG - gs)):
        run = ratchet(
            rolling_percentile(spread, PCT_YEARS).loc[START5:], RET5, lag=1, cash=CASH5
        )
        out[f"stat_{tag}"] = perf_daily(run["ret"], run, rf=CASH5)["sharpe_excess"] - STAT_B
        out[f"sumd_{tag}"] = float((run["ret"].reindex(IDX5) - RUN_B["ret"].reindex(IDX5)).sum())
    return out


def g_extras(g_vals: np.ndarray) -> tuple[int, int]:
    """起点之后 G > 0 的天数、符号穿越次数（相邻两日都非缺失才算）。"""
    post = g_vals[POST]
    sign = np.sign(post)
    ok = ~np.isnan(sign)
    flips = int(np.sum((sign[1:] != sign[:-1]) & ok[1:] & ok[:-1]))
    return int((post > 0).sum()), flips


# 真实 G 走同一条流水线必须与基线一致，否则安慰剂的对照组就不成立。
real = placebo_stats(G_SEG)
_sha_a = perf_daily(RUN_A["ret"], RUN_A, rf=CASH5)["sharpe_excess"] - STAT_B
if not abs(real["stat_M"] - _sha_a) < 1e-12 or not abs(real["sumd_M"] - BASE_SUM_AB) < 1e-12:
    raise RuntimeError(f"真实 G 复算与基线不一致：{real} vs stat={_sha_a} sumd={BASE_SUM_AB}")
_sha_c = perf_daily(RUN_C["ret"], RUN_C, rf=CASH5)["sharpe_excess"] - STAT_B
if not abs(real["stat_U"] - _sha_c) < 1e-12:
    raise RuntimeError(f"真实 G 的 U 复算与基线不一致：{real['stat_U']} vs {_sha_c}")
log(f"真实 stat（相对 B）: M={real['stat_M']:.6f} U={real['stat_U']:.6f}")
p05_real = dict(real) | {"stat_B": STAT_B, "sharpe_A": _sha_a + STAT_B, "sharpe_C": _sha_c + STAT_B}

# 主安慰剂：AR(1) 模拟。递归走完整个区间，再把真实 G 缺失的日子置 NaN。
_rng = np.random.default_rng(SEED)
_eps = _rng.standard_normal((PLACEBO_N, len(SEG_IDX))) * AR1_SIGMA
_sim = np.empty((PLACEBO_N, len(SEG_IDX)))
_sim[:, 0] = float(G_SEG.to_numpy()[0])
for _t in range(1, len(SEG_IDX)):
    _sim[:, _t] = AR1_C + AR1_PHI * _sim[:, _t - 1] + _eps[:, _t]
_sim[:, SEG_NAN] = np.nan

_t0 = time.monotonic()
ar1_rows = []
for i in range(PLACEBO_N):
    stats = placebo_stats(pd.Series(_sim[i], index=SEG_IDX))
    pos, flips = g_extras(_sim[i])
    ar1_rows.append({"sim": i} | stats | {"days_g_pos": pos, "sign_changes": flips})
p05_ar1 = pd.DataFrame(ar1_rows)
ar1_elapsed = time.monotonic() - _t0
log(f"AR(1) 安慰剂 {PLACEBO_N} 条耗时 {ar1_elapsed:.1f}s")

# 辅助安慰剂：时间平移。真实 G 的非 NaN 值按日期顺序循环移动 k 个位置，
# 放回原来的非 NaN 位置；循环拼接处有一个跳点。
_g_vals = G.dropna().to_numpy(dtype=float)
_g_pos = np.flatnonzero(~SEG_NAN)  # 相对 SEG_IDX 的位置
_t0 = time.monotonic()
shift_rows = []
for k in range(SHIFT_MIN, len(_g_vals) - SHIFT_MIN + 1, SHIFT_STEP):
    path = np.full(len(SEG_IDX), np.nan)
    path[_g_pos] = np.roll(_g_vals, k)
    stats = placebo_stats(pd.Series(path, index=SEG_IDX))
    pos, flips = g_extras(path)
    shift_rows.append({"k": k} | stats | {"days_g_pos": pos, "sign_changes": flips})
shift_elapsed = time.monotonic() - _t0
p05_shift = pd.DataFrame(shift_rows)
log(f"时间平移安慰剂 {len(p05_shift)} 条耗时 {shift_elapsed:.1f}s")


def summary_row(placebo: str, tag: str, stats: pd.Series) -> dict[str, float]:
    arr = stats.to_numpy(dtype=float)
    real_stat = real[f"stat_{tag}"]
    return {"strategy": tag, "placebo": placebo, "real_stat": real_stat, "n_sims": len(arr),
            "sim_mean": float(arr.mean()), "sim_p05": float(np.percentile(arr, 5)),
            "sim_p50": float(np.percentile(arr, 50)), "sim_p95": float(np.percentile(arr, 95)),
            "p_value": float(np.mean(arr >= real_stat)),
            "ar1_c": AR1_C, "ar1_phi": AR1_PHI, "ar1_sigma": AR1_SIGMA}


p05_summary = pd.DataFrame(
    [summary_row("ar1", tag, p05_ar1[f"stat_{tag}"]) for tag in ("M", "U")]
    + [summary_row("time_shift", tag, p05_shift[f"stat_{tag}"]) for tag in ("M", "U")]
)
_zero_pos = float((p05_ar1["days_g_pos"] == 0).mean())
log(f"AR(1) 模拟路径中起点后 G>0 天数为 0 的占比 {_zero_pos:.4f}")
print("P0.5 安慰剂汇总（p = 模拟 stat ≥ 真实 stat 的占比）:")
print(p05_summary.round(4).to_string(index=False))

# %% [markdown]
# ## 落盘：结果表、pit_report、run log

# %%
bundle = load_bundle()
datasets = (
    "src.wind.aindexvaluation",
    "src.wind.cbondcurvecnbd",
    "src.tushare.us_treasury_yield",
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
        "美债名义利率严格早于信号日可见（契约 2026-11-23 改为 strict）：T 日信号只用 T 日之前的观测。",
        "美国序列按 as-of 取最近一期，超过 7 个自然日视为缺失。",
        "τ = 2022-04-12 是看过数据后确定的（2022 年首个 G > 0 日），D 实验只作诊断，不作判读依据。",
        "现金按上一交易日 10Y 国债收益率 act/365 计息，不含久期损益。",
        "Wind 源镜像跟随源端修订，估值与中债为当前版本，不是当时版本。",
        "PE 修订回写用的 wx2 值来自 tests/golden/market_data/erp_000985_wx2.json（修订前的值）。",
        "cn_ibo_7d 日频单版本、发布当天可见，as_of=AS_OF 整段读一次与逐日读等价。",
    ],
}

daily_out = daily.reset_index(names="trade_dt")
input_digest = digest_json(
    {"params": PARAMS, "daily": json.loads(daily_out.to_json(orient="records", date_format="iso"))}
)
results = {
    "repro": repro,
    "p01_daily": p01_daily,
    "p01_summary": p01_summary,
    "p01_by_year": p01_by_year,
    "p01_by_state": p01_by_state,
    "p01_by_segment": p01_by_segment,
    "p01_events": p01_events_out,
    "p01_trades": p01_trades,
    "p02_experiments": p02_experiments,
    "p03_timing": p03_timing,
    "p03_benchmarks": p03_benchmarks,
    "p04_costs": p04_costs,
    "p04_cash": p04_cash,
    "p04_pe_revision": p04_pe_revision,
    "p04_missing": p04_missing,
    "p05_summary": p05_summary,
    "p05_ar1": p05_ar1,
    "p05_shift": p05_shift,
}
output_digest = digest_json({k: json.loads(v.to_json(orient="records")) for k, v in results.items()})

run_id = new_run_id()
out_dir = paths.root / "research" / "erp_max_attribution" / run_id
out_dir.mkdir(parents=True, exist_ok=False)
daily_out.to_csv(out_dir / "daily.csv", index=False)
for name, frame in results.items():
    frame.to_csv(out_dir / f"{name}.csv", index=False)
(out_dir / "summary.json").write_text(
    json.dumps(
        {"params": PARAMS, "pit_report": pit_report,
         "input_digest": input_digest, "output_digest": output_digest, "research_only": True,
         "no_database_write": True, "production_qualified": False},
        ensure_ascii=False, indent=2, default=str,
    ),
    encoding="utf-8",
)
log_path = persist_run_log(
    RunLog(
        run_id=run_id,
        action="research.erp_max_attribution",
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
