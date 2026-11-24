# %% [markdown]
# # A 股股债利差第四阶段：红利的股息率口径与成长风格的全球利率敏感度（P5）
#
# 方案与判读标准见 `docs/research/erp-phase4-plan.md`（看结果前写定，本脚本不改口径）。
#
# - A：中证红利改用股息率（Dv = DY − r_CN，对照 Du = DY − r_US、DY、V = EY − r_CN）。
# - B1：300 成长、300 价值分别跑 U、V，检验「U 相对 V 的优势只出现在成长端」。
# - B2/B3：风格价差（成长全收益 − 价值全收益）对 Δr_US、ΔTIPS、ΔBE、ΔFX、Δr_CN 的月度回归。
#
# 主口径同报告四：5 年滚动分位、T+1 收盘成交、现金为同业拆借 7 天、单边成本 5 bp；
# 美债 10 年取信号日前一天截止（7 天过期），TIPS 按 ALFRED 版本严格早于信号日。
#
# 只读：数据库只 SELECT；结果写到 `var/research/erp_dividend_growth/<run_id>/`，落 run log。

# %%
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from arch.bootstrap import SPA, StationaryBootstrap
from erp_lib import (
    TRADING_DAYS,
    asof_lookup,
    cash_accrual,
    clark_west_np,
    forward_sum,
    ivx_wald,
    null_bootstrap_draw,
    nw_ols,
    oos_expanding,
    perf_daily,
    r2_os,
    ratchet,
    rolling_percentile,
    stationary_indices,
)
from scipy.stats import norm
from statsmodels.stats.multitest import multipletests

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

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 120)
pd.set_option("display.max_rows", 400)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def hdr(title: str) -> None:
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}", flush=True)


def show(title: str, frame: pd.DataFrame) -> None:
    print(f"\n--- {title} ---", flush=True)
    out = frame.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]) and out[col].dtype != bool:
            out[col] = out[col].round(4)
    print(out.to_string(index=False), flush=True)


# %% [markdown]
# ## 固定参数

# %%
AS_OF = date(2026, 11, 20)  # 研究截止日，固定以便复现
START = date(2002, 1, 1)

A_INDEX = "000922.CSI"  # 中证红利
A_TR = "h00922.CSI"
B_GROWTH = "000918.CSI"  # 沪深 300 成长
B_GROWTH_TR = "h00918.CSI"
B_VALUE = "000919.CSI"  # 沪深 300 价值
B_VALUE_TR = "h00919.CSI"
CY_INDEX = "399006.SZ"  # 创业板指（补充）
CY_TR = "399606.SZ"
ALLSHARE_INDEX = "000985.CSI"  # 中证全指（创业板的市场对照）
ALLSHARE_TR = "h00985.CSI"

# 估值代码 -> 全收益指数代码
INDICES = {
    A_INDEX: A_TR,
    B_GROWTH: B_GROWTH_TR,
    B_VALUE: B_VALUE_TR,
    CY_INDEX: CY_TR,
    ALLSHARE_INDEX: ALLSHARE_TR,
}
SIGNALS_A = ("Dv", "Du", "DY", "V")
MAPPINGS = ("R0", "R1", "R3")  # R3 只报告
A3_MODELS = ("Dv", "Du", "DY", "V")
B1_SIGNALS = ("U", "V")

PCT_YEARS = 5
BAND = 0.10
SIGMA_WINDOW = 60
US_STALE_DAYS = 7
CASH_MAIN = "cash_ibo7d"
CASH_LEGS = ("cash_ibo7d", "cash_10y")
COST_MAIN = 5
COST_BPS = (0, 5, 10)
PERF_SPECS = (
    (CASH_MAIN, COST_MAIN),  # 主口径
    (CASH_MAIN, 0),
    (CASH_MAIN, 10),
    ("cash_10y", 0),
    ("cash_10y", COST_MAIN),
    ("cash_10y", 10),
)

SEED = 20261124
HORIZONS = (1, 3, 6, 12)
MIN_HISTORY = 60
N_BOOT = 2000
BOOT_BLOCK = 12  # 月频零假设自助法的平均块长（月），同报告四
SPA_BLOCK = 63  # 交易日
SPA_REPS = 2000
B1_BLOCK = 63  # 交易日
NW_LAGS = 3  # 月频择时回归的 Newey-West 滞后
POST_FX = date(2015, 8, 1)  # 汇改以后的样本，ΔFX 以这段判读（计划 B3）
A_REF_RUN = "3d64f8c559a549ebaf02fe3510084d25"  # 报告四
A_START_EXPECTED = pd.Timestamp("2013-05-27")  # 报告四中 000922 的起点

PARAMS = {
    "as_of": AS_OF.isoformat(),
    "start": START.isoformat(),
    "indices": dict(INDICES),
    "a_index": A_INDEX,
    "b_growth": B_GROWTH,
    "b_value": B_VALUE,
    "cy_index": CY_INDEX,
    "allshare_index": ALLSHARE_INDEX,
    "signals_a": list(SIGNALS_A),
    "signals_a_definition": {
        "Dv": "dividend_yield - r_cn",
        "Du": "dividend_yield - r_us",
        "DY": "dividend_yield",
        "V": "100/PE_TTM - r_cn (report four baseline)",
    },
    "dividend_yield_rule": "Wind AINDEXVALUATION.DIVIDEND_YIELD in percent; uses value only when > 0, "
                           "otherwise NaN; no fill",
    "b1_signals": {
        "U": "100/PE_TTM - r_us",
        "V": "100/PE_TTM - r_cn",
    },
    "mappings": {
        "R0": "target=pct, ratchet one_way=True, band 0.10, lag 1",
        "R1": "target=pct, ratchet one_way=False, band 0.10, lag 1",
        "R3": "target=pct * min(1, sigma_bar/sigma60), one_way=False, band 0.10",
    },
    "r3_detail": "sigma60 = ret.rolling(60).std()*sqrt(244); sigma_bar = expanding median; "
                 "both use the full available daily return history of the index (backward looking)",
    "pct_years": PCT_YEARS,
    "band": BAND,
    "sigma_window": SIGMA_WINDOW,
    "us_stale_days": US_STALE_DAYS,
    "cash_main": CASH_MAIN,
    "cash_legs": list(CASH_LEGS),
    "cost_main_bps": COST_MAIN,
    "perf_specs": [{"cash_leg": leg, "cost_bps": c} for leg, c in PERF_SPECS],
    "net_ret": "ret - cost_bps/1e4 * turnover",
    "buy_hold": "full position in the total-return index, first day of the window has no return",
    "seed": SEED,
    "horizons": list(HORIZONS),
    "min_history": MIN_HISTORY,
    "n_boot": N_BOOT,
    "boot_block": BOOT_BLOCK,
    "a3_seed_rule": "SeedSequence(20261124).spawn(1)[0].spawn(4)[model] -> default_rng",
    "spa": {"block_size": SPA_BLOCK, "reps": SPA_REPS, "bootstrap": "stationary",
            "studentize": True, "seed": SEED, "loss": "-net_ret"},
    "b1_bootstrap": {"class": "arch.bootstrap.StationaryBootstrap", "block_size": B1_BLOCK,
                     "reps": N_BOOT, "seed": SEED, "statistic": "mean of resampled centred d",
                     "p_rule": "mean(boot_mean >= real_mean), one sided"},
    "nw_lags": NW_LAGS,
    "monthly_definition": "month = natural month, month end = its last trading day; "
                          "monthly log return = sum log1p(daily total return) over "
                          "(previous month-end, this month-end], NaN if any daily return missing",
    "spread_definition": "100 * [sum log1p(r_growth) - sum log1p(r_value)] (percent points)",
    "post_fx_start": POST_FX.isoformat(),
    "a3_predictor": "signal level at the signal day (last trading day of month), as in report four Q2d",
    "a_ref_run": f"research/erp_position_mapping/{A_REF_RUN}",
    "research_class": "samples already observed; conclusions at most class 2",
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
# 估值（PE_TTM 与 DIVIDEND_YIELD）、中债、全收益指数是 `same_day_close`，以研究截止日整段读一次。
# 美债按契约严格早于信号日（`观测日 < 信号日`，7 天过期）。TIPS 有版本，按每个信号日的
# as_of 单独读取（同 `2026-11-23-erp-rate-anchor.py` 的 TIPS 段）。同业拆借 7 天与美元兑人民币
# 中间价是日频单版本、发布当天可见，整段读一次再按信号日对齐即可，与逐日读等价。

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


def valuation_series(attr: str) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for code in INDICES:
        s = pd.Series(
            {
                pd.Timestamp(r.trade_dt): (
                    np.nan if getattr(r, attr) is None else float(getattr(r, attr))
                )
                for r in val_rows
                if r.wind_code == code
            }
        ).sort_index()
        out[code] = s.reindex(open_idx)
    return out


pe_map = valuation_series("pe_ttm")
dy_map = valuation_series("dividend_yield")
log(f"估值行 {len(val_rows)}")


def point_series(series_id: str) -> pd.Series:
    rows = macro.list_observations(as_of=AS_OF, start=START, end=AS_OF, series_ids=(series_id,))
    s = pd.Series(
        {
            pd.Timestamp(r.observation_date): (np.nan if r.value is None else float(r.value))
            for r in rows
        }
    )
    return s.sort_index()


r_cn_raw = point_series("cn_cgb_10y")
r_us_raw = point_series("us_ust_10y").dropna()
ibo_raw = point_series("cn_ibo_7d")
fx_raw = point_series("cn_usdcny_fix")
log(
    f"中债 {len(r_cn_raw)} 美债 {len(r_us_raw)} 同业拆借 {int(ibo_raw.notna().sum())} "
    f"中间价 {int(fx_raw.notna().sum())}"
)

ret_rows = index_returns.list_returns(
    as_of=AS_OF, start=START, end=AS_OF, wind_codes=tuple(INDICES.values())
)
ret_map = {
    code: pd.Series(
        {
            pd.Timestamp(r.trade_dt): (np.nan if r.pct_change is None else float(r.pct_change))
            for r in ret_rows
            if r.wind_code == code
        }
    ).sort_index()
    for code in INDICES.values()
}
log(f"全收益行 {len(ret_rows)}")

# %% [markdown]
# ## 日频面板
#
# EY 与 r_CN 同日对齐；r_US 取观测日严格早于信号日的最近一期，过期超过 7 天即缺失。
# TIPS 逐日读：每个信号日 as_of 下的最近一期（契约严格早于 as_of），同样 7 天过期。

# %%
r_cn = r_cn_raw.reindex(open_idx)
us_cut = open_idx - pd.Timedelta(days=1)
vals_us, obs_us = asof_lookup(r_us_raw, us_cut)
stale_us = (us_cut - pd.DatetimeIndex(obs_us)) > pd.Timedelta(days=US_STALE_DAYS)
r_us = pd.Series(np.where(stale_us | pd.isna(obs_us), np.nan, vals_us), index=open_idx)
assert (pd.DatetimeIndex(obs_us)[r_us.notna().to_numpy()] < open_idx[r_us.notna().to_numpy()]).all()

vals_ibo, obs_ibo = asof_lookup(ibo_raw.dropna(), open_idx)
stale_ibo = (open_idx - pd.DatetimeIndex(obs_ibo)) > pd.Timedelta(days=US_STALE_DAYS)
ibo = pd.Series(np.where(stale_ibo | pd.isna(obs_ibo), np.nan, vals_ibo), index=open_idx)

# 中间价：日频单版本，发布当天可见，所以信号日当天取值（不取前值）与逐日 as_of 读等价。
fx = fx_raw.reindex(open_idx)

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
tips = pd.Series(tips_val, index=open_idx, name="tips")
log(f"TIPS 完成，有效 {int(tips.notna().sum())} 天")

CASH_10Y = cash_accrual(r_cn)
CASH_IBO = cash_accrual(ibo)
CASH_BY_LEG = {"cash_10y": CASH_10Y, "cash_ibo7d": CASH_IBO}
log(
    f"有效天数: r_cn {int(r_cn.notna().sum())} r_us {int(r_us.notna().sum())} "
    f"ibo {int(ibo.notna().sum())} tips {int(tips.notna().sum())} fx {int(fx.notna().sum())}"
)

# %% [markdown]
# ## 指数面板
#
# A 的中证红利：DY 只取 > 0 的值，Dv / Du / DY / V 各算 5 年滚动分位；
# B1 的两只风格指数：U = EY − r_US、V = EY − r_CN 的分位。
# 起点取「四个分位都有值的第一天」，之后不允许再有缺失。

# %%
def build_percentiles(levels: dict[str, pd.Series]) -> dict[str, pd.Series]:
    return {k: rolling_percentile(s, PCT_YEARS) for k, s in levels.items()}


def common_start(pcts: dict[str, pd.Series]) -> pd.Timestamp:
    ok = pd.concat(pcts, axis=1).notna().all(axis=1)
    if not ok.any():
        raise RuntimeError(f"分位没有共同有效日，停止：{list(pcts)}")
    return ok[ok].index[0]


PANELS: dict[str, dict[str, Any]] = {}
for code, tr in INDICES.items():
    pe = pe_map[code]
    dy = dy_map[code]
    PANELS[code] = {
        "code": code,
        "tr": tr,
        "pe": pe,
        "dy": dy,
        "ey": pd.Series(np.where(pe > 0, 100.0 / pe, np.nan), index=open_idx),
        "ret": ret_map[tr].reindex(open_idx) / 100.0,
    }

_a = PANELS[A_INDEX]
_a["DY"] = _a["dy"].where(_a["dy"] > 0)
_a["Dv"] = _a["DY"] - r_cn
_a["Du"] = _a["DY"] - r_us
_a["V"] = _a["ey"] - r_cn
_a["pct"] = build_percentiles({k: _a[k] for k in SIGNALS_A})
_pct: dict[str, pd.Series] = _a["pct"]
A_START = common_start(_pct)
if not pd.concat(_pct, axis=1).loc[A_START:].notna().all(axis=1).all():
    raise RuntimeError(f"{A_INDEX} 起点之后有分位缺失，停止")
if A_START != A_START_EXPECTED:
    raise RuntimeError(
        f"中证红利四个信号的共同起点 {A_START.date()} 与报告四的 "
        f"{A_START_EXPECTED.date()} 不一致，停止"
    )

for code in (B_GROWTH, B_VALUE):
    p = PANELS[code]
    p["U"] = p["ey"] - r_us
    p["V"] = p["ey"] - r_cn
    p["pct"] = build_percentiles({"U": p["U"], "V": p["V"]})
    _pp: dict[str, pd.Series] = p["pct"]
    p["own_start"] = common_start(_pp)
    if not pd.concat(_pp, axis=1).loc[p["own_start"]:].notna().all(axis=1).all():
        raise RuntimeError(f"{code} 起点之后有分位缺失，停止")

B1_START = pd.Timestamp(max(PANELS[B_GROWTH]["own_start"], PANELS[B_VALUE]["own_start"]))

hdr("起点")
print(
    pd.DataFrame(
        [
            {"index": A_INDEX, "total_return": A_TR, "signals": "Dv/Du/DY/V",
             "start": str(A_START.date()),
             "first_ret": str(_a["ret"].first_valid_index().date())},
            {"index": B_GROWTH, "total_return": B_GROWTH_TR, "signals": "U/V",
             "start": str(PANELS[B_GROWTH]["own_start"].date()),
             "first_ret": str(PANELS[B_GROWTH]["ret"].first_valid_index().date())},
            {"index": B_VALUE, "total_return": B_VALUE_TR, "signals": "U/V",
             "start": str(PANELS[B_VALUE]["own_start"].date()),
             "first_ret": str(PANELS[B_VALUE]["ret"].first_valid_index().date())},
            {"index": "B1 common", "total_return": f"{B_GROWTH_TR}+{B_VALUE_TR}",
             "signals": "U/V x2", "start": str(B1_START.date()), "first_ret": ""},
        ]
    ).to_string(index=False),
    flush=True,
)
for code in (A_INDEX, B_GROWTH, B_VALUE):
    print(
        f"  {code}: DY 有效 {int(PANELS[code]['dy'].notna().sum())} 天，"
        f"PE 有效 {int(PANELS[code]['pe'].notna().sum())} 天，"
        f"全收益起点 {PANELS[code]['ret'].first_valid_index().date()}",
        flush=True,
    )

# %% [markdown]
# ## 先过的断言：中证红利 V + R0 与报告四一致
#
# 主口径（ibo 现金、5 bp）下 `sharpe_excess`、`ann_return` 与 `start` 都必须与报告四的
# `p4_perf.csv` 一致（数值阈值 1e-12）。不一致说明读取或分位口径已经偏离，直接停下。

# %%
a_ref_path = paths.root / "research" / "erp_position_mapping" / A_REF_RUN / "p4_perf.csv"
if not a_ref_path.is_file():
    raise RuntimeError(f"报告四的 p4_perf.csv 不存在：{a_ref_path}")
a_ref = pd.read_csv(a_ref_path, float_precision="round_trip")
a_ref_row = a_ref[
    (a_ref["index"] == A_INDEX)
    & (a_ref["window"] == "own")
    & (a_ref["cash_leg"] == CASH_MAIN)
    & (a_ref["cost_bps"] == COST_MAIN)
    & (a_ref["signal"] == "V")
    & (a_ref["mapping"] == "R0")
]
if len(a_ref_row) != 1:
    raise RuntimeError(f"报告四的基准行不是唯一一行：{len(a_ref_row)}")
a_ref_row = a_ref_row.iloc[0]


def run_mapping(
    pct: pd.Series,
    ret: pd.Series,
    cash: pd.Series,
    start: pd.Timestamp,
    mapping: str,
    *,
    base: pd.Series,
) -> pd.DataFrame:
    """按 R0/R1/R3 在 ``start`` 之后跑 ``ratchet``；R3 的波动约束用该指数全部可得日收益。"""
    rr = ret.loc[start:]
    cc = cash.loc[start:]
    pp = pct.loc[start:]
    if mapping == "R0":
        return ratchet(pp, rr, lag=1, cash=cc)
    if mapping == "R1":
        return ratchet(pp, rr, lag=1, cash=cc, one_way=False)
    sigma60 = ret.rolling(SIGMA_WINDOW).std() * np.sqrt(TRADING_DAYS)
    sigma_bar = sigma60.expanding().median()
    vol_target = base * np.minimum(1.0, sigma_bar / sigma60)
    return ratchet(vol_target.loc[start:], rr, lag=1, cash=cc, one_way=False)


_a_pct: dict[str, pd.Series] = PANELS[A_INDEX]["pct"]
_a_ret: pd.Series = PANELS[A_INDEX]["ret"]
RUN_A: dict[str, dict[tuple[str, str], pd.DataFrame]] = {}
for leg in CASH_LEGS:
    runs: dict[tuple[str, str], pd.DataFrame] = {}
    for sig in SIGNALS_A:
        for mp in MAPPINGS:
            runs[(sig, mp)] = run_mapping(
                _a_pct[sig], _a_ret, CASH_BY_LEG[leg], A_START, mp, base=_a_pct[sig]
            )
    RUN_A[leg] = runs


def net_ret(run: pd.DataFrame, cost_bps: int) -> pd.Series:
    return run["ret"] - cost_bps / 1e4 * run["turnover"]


_a_check = net_ret(RUN_A[CASH_MAIN][("V", "R0")], COST_MAIN)
with np.errstate(divide="ignore", invalid="ignore"):
    _a_perf = perf_daily(_a_check, RUN_A[CASH_MAIN][("V", "R0")], rf=CASH_BY_LEG[CASH_MAIN])
_a_used = _a_check.dropna().index
for field, ours, ref in (
    ("sharpe_excess", _a_perf["sharpe_excess"], float(a_ref_row["sharpe_excess"])),
    ("ann_return", _a_perf["ann_return"], float(a_ref_row["ann_return"])),
):
    if not abs(ours - ref) <= 1e-12:
        raise RuntimeError(f"断言失败：{field} 新 {ours!r} 与报告四 {ref!r} 不一致，停止")
assert str(_a_used[0].date()) == str(a_ref_row["start"]), (
    f"断言失败：起点 {_a_used[0].date()} 与报告四 {a_ref_row['start']} 不一致，停止"
)
hdr("断言：中证红利 V + R0（主口径）与报告四一致")
a_repro = pd.DataFrame(
    [
        {"field": "start", "ours": str(_a_used[0].date()), "report4": str(a_ref_row["start"]),
         "equal": True},
        {"field": "sharpe_excess", "ours": _a_perf["sharpe_excess"],
         "report4": float(a_ref_row["sharpe_excess"]),
         "equal": abs(_a_perf["sharpe_excess"] - float(a_ref_row["sharpe_excess"])) <= 1e-12},
        {"field": "ann_return", "ours": _a_perf["ann_return"],
         "report4": float(a_ref_row["ann_return"]),
         "equal": abs(_a_perf["ann_return"] - float(a_ref_row["ann_return"])) <= 1e-12},
    ]
)
show("a_repro 断言（中证红利 V+R0，主口径）", a_repro)
log(f"断言通过：中证红利 V+R0 与报告四一致，样本 {_a_used[0].date()}..{_a_used[-1].date()}")


# %% [markdown]
# ## 绩效表工具
#
# 成本按成交日扣：`ret_net = ret − c/1e4 × turnover`，不影响仓位路径。
# 买入持有满仓全收益指数，窗口首日无收益（与报告一同口径），不计成本。

# %%
def perf_rows(
    label: str,
    runs_by_leg: dict[str, dict[tuple[str, str], pd.DataFrame]],
    ret: pd.Series,
    start: pd.Timestamp,
    signals: tuple[str, ...],
    *,
    specs: tuple[tuple[str, int], ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for leg, cost in specs:
        cash_leg = CASH_BY_LEG[leg]
        for sig in signals:
            for mp in MAPPINGS:
                run = runs_by_leg[leg][(sig, mp)]
                net = net_ret(run, cost)
                with np.errstate(divide="ignore", invalid="ignore"):
                    perf = perf_daily(net, run, rf=cash_leg)
                used = net.dropna().index
                rows.append(
                    {"index": label, "signal": sig, "mapping": mp, "cash_leg": leg,
                     "cost_bps": cost, "start": str(used[0].date()),
                     "end": str(used[-1].date())} | perf
                )
    for leg in {leg for leg, _ in specs}:
        cash_leg = CASH_BY_LEG[leg]
        bh = ret.loc[start:].copy()
        bh.iloc[0] = np.nan
        bh_run = pd.DataFrame({"w": 1.0, "turnover": 0.0, "ret": bh})
        with np.errstate(divide="ignore", invalid="ignore"):
            perf = perf_daily(bh, bh_run, rf=cash_leg)
        used = bh.dropna().index
        rows.append(
            {"index": label, "signal": "BH", "mapping": "BH", "cash_leg": leg,
             "cost_bps": 0, "start": str(used[0].date()), "end": str(used[-1].date())} | perf
        )
    return rows


PERF_COLS = [
    "index", "signal", "mapping", "cash_leg", "cost_bps", "start", "end",
    "ann_return", "ann_vol", "sharpe_excess", "max_dd", "avg_w", "turnover_per_year",
]


def main_cell(perf: pd.DataFrame, sig: str, mp: str) -> float:
    sel = perf[
        (perf["signal"] == sig)
        & (perf["mapping"] == mp)
        & (perf["cash_leg"] == CASH_MAIN)
        & (perf["cost_bps"] == COST_MAIN)
    ]
    if len(sel) != 1:
        raise RuntimeError(f"主口径行不唯一：{sig}+{mp} -> {len(sel)}")
    return float(sel["sharpe_excess"].iloc[0])


def run_spa(bench: pd.Series, cands: dict[str, pd.Series]) -> dict[str, object]:
    """Hansen SPA：损失 = 净收益的相反数，平稳自助法，块长 63 个交易日，2000 次。"""
    names = list(cands)
    frame = pd.concat(
        [bench.rename("__bench"), *[cands[k].rename(k) for k in names]], axis=1
    ).dropna()
    if len(frame) < 2 * SPA_BLOCK:
        raise RuntimeError(f"SPA 的公共非 NaN 日期太少：{len(frame)}")
    b_loss = -frame["__bench"].to_numpy(dtype=float)
    m_loss = -frame[names].to_numpy(dtype=float)
    mean_loss = m_loss.mean(axis=0)
    best_j = int(np.argmin(mean_loss))
    spa = SPA(
        b_loss,
        m_loss,
        block_size=SPA_BLOCK,
        reps=SPA_REPS,
        bootstrap="stationary",
        studentize=True,
        seed=SEED,
    )
    spa.compute()
    pv = spa.pvalues
    return {
        "n_days": len(frame),
        "start": str(frame.index[0].date()),
        "end": str(frame.index[-1].date()),
        "n_models": len(names),
        "p_lower": float(pv["lower"]),
        "p_consistent": float(pv["consistent"]),
        "p_upper": float(pv["upper"]),
        "best_model": names[best_j],
        "best_mean_diff_bp": float(b_loss.mean() - mean_loss[best_j]) * 1e4,
    }


# %% [markdown]
# ## A：中证红利的股息率口径
#
# ### a_perf：Dv / Du / DY / V 在 R0、R1、R3 下的绩效（主口径 + 敏感性）

# %%
a_perf = pd.DataFrame(
    perf_rows(A_INDEX, RUN_A, _a_ret, A_START, SIGNALS_A, specs=PERF_SPECS)
)[PERF_COLS]
log(f"a_perf {len(a_perf)} 行")
show(
    "a_perf 主口径（ibo、5bp）",
    a_perf[(a_perf["cash_leg"] == CASH_MAIN) & (a_perf["cost_bps"] == COST_MAIN)],
)
show(
    "a_perf 敏感性（cash_10y 或成本 0/10，只报告）",
    a_perf[~((a_perf["cash_leg"] == CASH_MAIN) & (a_perf["cost_bps"] == COST_MAIN))][
        ["signal", "mapping", "cash_leg", "cost_bps", "ann_return", "sharpe_excess", "max_dd"]
    ],
)

# %% [markdown]
# ### a1：股息率口径是否优于盈利收益率口径
#
# 主口径下 Dv 的超额夏普在 R0 与 R1 下都高于 V，才判为「股息率口径更好」（第 2 类）。

# %%
_a1_rows = []
for mp in ("R0", "R1"):
    dv = main_cell(a_perf, "Dv", mp)
    v = main_cell(a_perf, "V", mp)
    _a1_rows.append({"mapping": mp, "sharpe_Dv": dv, "sharpe_V": v, "dv_gt_v": bool(dv > v)})
a1 = pd.DataFrame(_a1_rows)
_a1_all = bool(a1["dv_gt_v"].all())
a1["dv_beats_v"] = _a1_all
show("a1 股息率口径 vs 盈利收益率口径（主口径，超额夏普）", a1)
log(f"a1 dv_beats_v = {_a1_all}")

# %% [markdown]
# ### a2_spa：该减哪种利率？
#
# 基准 V + R0，候选 {Dv, Du, DY} × {R0, R1} 共 6 个，主口径净日收益，取公共非 NaN 日期。

# %%
a_bench = net_ret(RUN_A[CASH_MAIN][("V", "R0")], COST_MAIN)
a_cands = {
    f"{sig}+{mp}": net_ret(RUN_A[CASH_MAIN][(sig, mp)], COST_MAIN)
    for sig in ("Dv", "Du", "DY")
    for mp in ("R0", "R1")
}
a2_spa = pd.DataFrame([{"benchmark": "V+R0"} | run_spa(a_bench, a_cands)])
a2_spa = a2_spa[
    ["benchmark", "n_days", "start", "end", "n_models", "p_lower", "p_consistent",
     "p_upper", "best_model", "best_mean_diff_bp"]
]
show("a2_spa（基准 V+R0，6 个候选）", a2_spa)
log(f"a2_spa p_consistent={a2_spa['p_consistent'].iloc[0]:.4f} best={a2_spa['best_model'].iloc[0]}")

# %% [markdown]
# ### 月度面板（A3 与 B2/B3 共用）
#
# 信号日 = 每月最后一个交易日。`fwd1` 是从信号日次一交易日收盘到下月信号日次一交易日收盘的
# 全收益对数收益（百分点），与报告四 `build_monthly` 同口径；月现金用同业拆借 7 天在同一区间累计。

# %%
MONTH = open_idx.to_period("M")
LAST_OF_MONTH = pd.Series(open_idx, index=MONTH).groupby(level=0).max()
SIGNAL_DATES = pd.DatetimeIndex(LAST_OF_MONTH.to_numpy())
END_POS = np.array([open_idx.get_loc(d) for d in SIGNAL_DATES])
ENTRY = open_idx.searchsorted(SIGNAL_DATES, side="right")
log(f"月末交易日 {len(SIGNAL_DATES)} 天")


def build_monthly(ret: pd.Series, cash_daily: pd.Series) -> pd.DataFrame:
    """月频面板：period、signal_dt、fwd1（百分点，对数）、cash_m（百分点，对数）。"""
    n = len(SIGNAL_DATES)
    ret_arr = ret.to_numpy(dtype=float)
    cash_arr = cash_daily.to_numpy(dtype=float)
    fwd1 = np.full(n, np.nan)
    cash_m = np.full(n, np.nan)
    for i in range(n - 1):
        a, b = ENTRY[i] + 1, ENTRY[i + 1]
        if b >= len(open_idx) or a > b:
            continue
        wr = ret_arr[a : b + 1]
        wc = cash_arr[a : b + 1]
        if len(wr) and not np.isnan(wr).any():
            fwd1[i] = float(np.log1p(wr).sum() * 100.0)
        if len(wc) and not np.isnan(wc).any():
            cash_m[i] = float(np.log1p(wc).sum() * 100.0)
    return pd.DataFrame(
        {"period": LAST_OF_MONTH.index.astype(str).to_numpy(), "signal_dt": SIGNAL_DATES,
         "fwd1": fwd1, "cash_m": cash_m}
    )


def month_log_sum(ret: pd.Series) -> np.ndarray:
    """自然月对数收益之和（百分点）：窗口 = (上月月末交易日, 本月月末交易日]，缺一天即 NaN。"""
    arr = ret.to_numpy(dtype=float)
    out = np.full(len(END_POS), np.nan)
    for i in range(1, len(END_POS)):
        a, b = END_POS[i - 1] + 1, END_POS[i]
        if b < a:
            continue
        w = arr[a : b + 1]
        if len(w) and not np.isnan(w).any():
            out[i] = float(np.log1p(w).sum() * 100.0)
    return out


def at_month_end(series: pd.Series) -> np.ndarray:
    return series.reindex(SIGNAL_DATES).to_numpy(dtype=float)


def longest_valid_run(arrays: list[np.ndarray], first: int) -> tuple[int, int]:
    """``first`` 之后各数组都非 NaN 的最长连续区间的起止位置（含）。"""
    ok = ~np.isnan(np.column_stack(arrays)).any(axis=1)
    ok[:first] = False
    best = (0, -1)
    begin = None
    for i, flag in enumerate(ok):
        if flag and begin is None:
            begin = i
        elif not flag and begin is not None:
            if i - 1 - begin > best[1] - best[0]:
                best = (begin, i - 1)
            begin = None
    if begin is not None and len(ok) - 1 - begin > best[1] - best[0]:
        best = (begin, len(ok) - 1)
    if best[1] < best[0]:
        raise RuntimeError("没有可用样本，停止")
    return best


def first_oos_month(y: np.ndarray, h: int, first: int, min_history: int) -> int:
    """``oos_expanding`` 意义下首个「训练样本足够」的预测月位置。

    训练月 q 必须满足 ``q + h + 1 <= i``（h 期收益在 i 的信号日之前已实现），与
    `erp_lib.oos_expanding` 的上界一致。
    """
    for i in range(first, len(y)):
        last = i - h - 1
        if last < first:
            continue
        span = np.arange(first, last + 1)
        base = span[~np.isnan(y[span])]
        if len(base) >= min_history:
            return i
    raise RuntimeError(f"没有满足训练样本 ≥ {min_history} 的预测月，停止")


def nw_hac(y: np.ndarray, x: np.ndarray, h: int) -> tuple[np.ndarray, np.ndarray]:
    """``y ~ 1 + x`` 的 Newey-West 系数与 t 值（Bartlett，滞后 max(h,1)），同报告四。

    只用于零假设自助法里重抽 2000 次；与 `erp_lib.nw_ols` 等价但快得多。
    """
    matrix = np.column_stack([np.ones(y.shape[0]), x])
    xtx = matrix.T @ matrix
    coef = np.linalg.solve(xtx, matrix.T @ y)
    resid = y - matrix @ coef
    xe = matrix * resid[:, None]
    sigma = xe.T @ xe
    lags = max(int(h), 1)
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        cross = xe[lag:].T @ xe[:-lag]
        sigma += weight * (cross + cross.T)
    cov = np.linalg.solve(xtx, sigma) @ np.linalg.inv(xtx)
    return coef, coef / np.sqrt(np.diag(cov))


# %% [markdown]
# ### a3：股息率信号的月频预测
#
# 对 Dv、Du、DY、V 各做：NW t（h ∈ 1/3/6/12，因变量 = 未来 h 个月对数全收益之和）、
# IVX 单边 p、零假设平稳块自助单边 p（2000 次、块长 12 月，种子
# `SeedSequence(20261124).spawn(1)[0].spawn(4)[model]`）、样本外 R²_OS 与 CW p
# （训练从首个有效月起，预测从首个训练 ≥ 60 个月的月份起）。4 模型 × 4 期限做 Holm。
# 评级规则同报告四：条件 2（训练起点网格）按不满足计，所以最高第 2 类。

# %%
A_MONTHLY = build_monthly(_a_ret, CASH_IBO)
for sig in SIGNALS_A:
    A_MONTHLY[f"level|{sig}"] = _a[sig].reindex(SIGNAL_DATES).to_numpy()
    A_MONTHLY[f"pct|{sig}"] = _pct[sig].reindex(SIGNAL_DATES).to_numpy()
log(f"{A_INDEX} 月频面板 {len(A_MONTHLY)} 个月 "
    f"{A_MONTHLY['period'].iloc[0]}..{A_MONTHLY['period'].iloc[-1]}")

_y1 = A_MONTHLY["fwd1"].to_numpy(dtype=float)
_x_all = {k: A_MONTHLY[f"level|{k}"].to_numpy(dtype=float) for k in A3_MODELS}
_A3_A, _A3_B = longest_valid_run([_y1, *_x_all.values()], 0)
_y1c = _y1[_A3_A : _A3_B + 1]
log(f"{A_INDEX} 月频推断样本 {A_MONTHLY['period'].iloc[_A3_A]}.."
    f"{A_MONTHLY['period'].iloc[_A3_B]}（{_A3_B - _A3_A + 1} 个月）")

a3_rows: list[dict[str, object]] = []
a3_grade_rows: list[dict[str, object]] = []
_A3_SEQS = np.random.SeedSequence(SEED).spawn(1)[0].spawn(len(A3_MODELS))
_A3_KEYS = [(m, h) for m in A3_MODELS for h in HORIZONS]
for j, model in enumerate(A3_MODELS):
    _xc = _x_all[model][_A3_A : _A3_B + 1]
    rng = np.random.default_rng(_A3_SEQS[j])
    real: dict[int, dict[str, float]] = {}
    for h in HORIZONS:
        yh = forward_sum(_y1c, h)
        ok = ~np.isnan(yh)
        fit = nw_ols(pd.Series(yh[ok], name="y"), pd.DataFrame({"x": _xc[ok]}), h)[0]
        ivx = ivx_wald(_y1c, _xc, h)
        o_start = first_oos_month(yh, h, 0, MIN_HISTORY)
        fc = oos_expanding(
            yh, _xc, h, train_start=0, oos_start=o_start, min_history=MIN_HISTORY
        ).dropna()
        cw_t, cw_p = clark_west_np(fc["y"], fc["M0"], fc["model"], h)
        real[h] = {"t": float(fit.tvalues["x"]), "coef": float(fit.params["x"]),
                   "n": int(ok.sum()), "ivx_p_pos": float(ivx["p_one_sided_pos"]),
                   "r2_os": r2_os(fc["y"], fc["model"], fc["M0"]),
                   "cw_t": cw_t, "cw_p": cw_p,
                   "oos_start": str(A_MONTHLY["period"].iloc[_A3_A + o_start])}
    boot_t = {h: np.empty(N_BOOT) for h in HORIZONS}
    for bi in range(N_BOOT):
        idx = stationary_indices(len(_y1c) - 1, BOOT_BLOCK, rng)
        y_star, x_star = null_bootstrap_draw(_y1c, _xc, [], idx)
        for h in HORIZONS:
            yh_star = forward_sum(y_star, h)
            ok_s = ~np.isnan(yh_star)
            _, t_star = nw_hac(yh_star[ok_s], x_star[ok_s], h)
            boot_t[h][bi] = t_star[1]
    for h in HORIZONS:
        a3_rows.append(
            {"index": A_INDEX, "model": model, "h": h, "n": real[h]["n"],
             "coef": real[h]["coef"], "t_nw": real[h]["t"],
             "ivx_p_one_sided": real[h]["ivx_p_pos"],
             "p_boot_one_sided": float(np.mean(boot_t[h] >= real[h]["t"])),
             "r2_os": real[h]["r2_os"], "cw_t": real[h]["cw_t"], "cw_p": real[h]["cw_p"],
             "oos_start": real[h]["oos_start"]}
        )
    log(f"  {model}: 预测起点 {real[1]['oos_start']}，自助 {N_BOOT} 次完成")

p_holm = multipletests(
    [float(a3_rows[_A3_KEYS.index(k)]["cw_p"]) for k in _A3_KEYS], method="holm"
)[1]
for k, ph in zip(_A3_KEYS, p_holm, strict=True):
    a3_rows[_A3_KEYS.index(k)]["p_holm"] = float(ph)

for model in A3_MODELS:
    _rows = {r["h"]: r for r in a3_rows if r["model"] == model}
    c1_h = [h for h in HORIZONS if float(_rows[h]["p_holm"]) < 0.05]
    c1 = len(c1_h) >= 2
    c3_h = [
        h for h in HORIZONS
        if float(_rows[h]["ivx_p_one_sided"]) < 0.05
        or float(_rows[h]["p_boot_one_sided"]) < 0.05
    ]
    c3_on_c1 = all(h in c3_h for h in c1_h)
    # 条件 2（训练起点网格）按计划记为不满足，所以第 3 类不可达
    grade = "2" if (c1 or len(c3_h) >= 2) else "5"
    a3_grade_rows.append(
        {"index": A_INDEX, "model": model, "c1_horizons": ",".join(map(str, c1_h)),
         "c1": c1, "c2": False, "c3_horizons": ",".join(map(str, c3_h)),
         "c3_on_c1": c3_on_c1, "grade": grade,
         "note": "条件 2（训练起点网格）按计划记为不满足，最高第 2 类"}
    )

a3_inference = pd.DataFrame(a3_rows)[
    ["index", "model", "h", "n", "coef", "t_nw", "ivx_p_one_sided", "p_boot_one_sided",
     "r2_os", "cw_t", "cw_p", "p_holm", "oos_start"]
]
a3_grade = pd.DataFrame(a3_grade_rows)
show("a3_inference 月频推断（中证红利）", a3_inference)
show("a3_grade 评级", a3_grade)

# %% [markdown]
# ### a_corr：DY、EY、Dv、V 的相关矩阵
#
# 起点之后的日度水平值与 5 年分位，各自的相关矩阵（长表）。

# %%
_a_corr_series: dict[str, pd.Series] = {}
for name, s in (("DY", _a["DY"]), ("EY", _a["ey"]), ("Dv", _a["Dv"]), ("V", _a["V"])):
    _a_corr_series[f"{name}|level"] = s.loc[A_START:AS_OF]
for name in ("DY", "Dv", "V"):
    _a_corr_series[f"{name}|pct"] = _pct[name].loc[A_START:AS_OF]
_a_corr_series["EY|pct"] = rolling_percentile(_a["ey"], PCT_YEARS).loc[A_START:AS_OF]
a_corr_rows: list[dict[str, object]] = []
for kind in ("level", "pct"):
    cols = [f"{name}|{kind}" for name in ("DY", "EY", "Dv", "V")]
    frame = pd.DataFrame({c: _a_corr_series[c] for c in cols})
    matrix = frame.corr()
    for ca in cols:
        for cb in cols:
            pair = frame[[ca, cb]].dropna()
            a_corr_rows.append(
                {"kind": kind, "series_a": ca.split("|")[0], "series_b": cb.split("|")[0],
                 "corr": float(matrix.loc[ca, cb]), "n_days": len(pair)}
            )
a_corr = pd.DataFrame(a_corr_rows)
show("a_corr 相关矩阵（长表）", a_corr)

# %% [markdown]
# ## B1：成长端的 U 相对 V 是否更有利
#
# 300 成长与 300 价值各跑 U、V 的 R0 与 R1（主口径），区间取两者共同起点。
# `d_t = (U − V)_成长 − (U − V)_价值`，用净日收益；平稳自助（块长 63 个交易日、2000 次、
# 种子 20261124）在零均值化后的 d 上重抽，单边 p = mean(boot_mean ≥ real_mean)。
# 判读：R0 与 R1 下都满足「成长端 Σ(U−V) > 0 且 p < 0.10」才算支持。

# %%
RUN_B1: dict[str, dict[tuple[str, str], pd.DataFrame]] = {}
for code in (B_GROWTH, B_VALUE):
    p = PANELS[code]
    pcts: dict[str, pd.Series] = p["pct"]
    ret: pd.Series = p["ret"]
    runs: dict[tuple[str, str], pd.DataFrame] = {}
    for sig in B1_SIGNALS:
        for mp in ("R0", "R1"):
            runs[(sig, mp)] = run_mapping(
                pcts[sig], ret, CASH_IBO, B1_START, mp, base=pcts[sig]
            )
    RUN_B1[code] = runs

b1_perf_rows: list[dict[str, object]] = []
for code in (B_GROWTH, B_VALUE):
    ret: pd.Series = PANELS[code]["ret"]
    for sig in B1_SIGNALS:
        for mp in ("R0", "R1"):
            run = RUN_B1[code][(sig, mp)]
            net = net_ret(run, COST_MAIN)
            with np.errstate(divide="ignore", invalid="ignore"):
                perf = perf_daily(net, run, rf=CASH_IBO)
            used = net.dropna().index
            b1_perf_rows.append(
                {"index": code, "signal": sig, "mapping": mp,
                 "ann_return": perf["ann_return"], "sharpe_excess": perf["sharpe_excess"],
                 "max_dd": perf["max_dd"], "avg_w": perf["avg_w"],
                 "start": str(used[0].date()), "end": str(used[-1].date())}
            )
    bh = ret.loc[B1_START:].copy()
    bh.iloc[0] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        perf = perf_daily(bh, pd.DataFrame({"w": 1.0, "turnover": 0.0, "ret": bh}), rf=CASH_IBO)
    used = bh.dropna().index
    b1_perf_rows.append(
        {"index": code, "signal": "BH", "mapping": "BH",
         "ann_return": perf["ann_return"], "sharpe_excess": perf["sharpe_excess"],
         "max_dd": perf["max_dd"], "avg_w": 1.0,
         "start": str(used[0].date()), "end": str(used[-1].date())}
    )
b1_perf = pd.DataFrame(b1_perf_rows)[
    ["index", "signal", "mapping", "ann_return", "sharpe_excess", "max_dd", "avg_w", "start", "end"]
]
show("b1_perf 主口径（ibo、5bp）", b1_perf)


def stationary_boot_mean_p(series: pd.Series) -> float:
    """单边平稳自助：p = mean(自助样本均值 ≥ 真实均值)，在零均值化后的序列上重抽。"""
    x = series.to_numpy(dtype=float)
    real = float(x.mean())
    centered = x - real
    bs = StationaryBootstrap(B1_BLOCK, centered, seed=SEED)
    means = np.array([float(pos[0].mean()) for pos, _kw in bs.bootstrap(N_BOOT)])
    return float(np.mean(means >= real))


b1_test_rows: list[dict[str, object]] = []
for mp in ("R0", "R1"):
    g_u = net_ret(RUN_B1[B_GROWTH][("U", mp)], COST_MAIN)
    g_v = net_ret(RUN_B1[B_GROWTH][("V", mp)], COST_MAIN)
    v_u = net_ret(RUN_B1[B_VALUE][("U", mp)], COST_MAIN)
    v_v = net_ret(RUN_B1[B_VALUE][("V", mp)], COST_MAIN)
    frame = pd.concat(
        {"g_u": g_u, "g_v": g_v, "v_u": v_u, "v_v": v_v}, axis=1
    ).dropna()
    d_growth = frame["g_u"] - frame["g_v"]
    d_value = frame["v_u"] - frame["v_v"]
    d = d_growth - d_value
    sum_g = float(d_growth.sum())
    sum_v = float(d_value.sum())
    p_boot = stationary_boot_mean_p(d)
    b1_test_rows.append(
        {"mapping": mp, "n_days": len(frame), "start": str(frame.index[0].date()),
         "end": str(frame.index[-1].date()),
         "sum_uv_growth": sum_g, "sum_uv_value": sum_v,
         "mean_d_bp": float(d.mean()) * 1e4, "p_boot": p_boot,
         "supports": bool(sum_g > 0 and p_boot < 0.10)}
    )
b1_test = pd.DataFrame(b1_test_rows)
b1_supports_all = bool(b1_test["supports"].all() and set(b1_test["mapping"]) == {"R0", "R1"})
b1_test["b1_supports_all"] = b1_supports_all
show("b1_test 成长端 U−V 是否更强", b1_test)
log(f"b1_supports_all = {b1_supports_all}")

# %% [markdown]
# ## B2/B3：风格价差对利率变动与汇率变动的同期敏感度
#
# 月度样本：月份 = 自然月，月末 = 该月最后一个交易日。风格价差
# `spread = 100 × [Σln(1+r_成长) − Σln(1+r_价值)]`，窗口是上月月末交易日之后到本月月末
# 交易日（含），任一日缺失则该月 NaN，不填。Δr_US、Δr_CN 取月末交易日的值相对上月月末的变化
# （百分点）；TIPS 取逐日 as_of 读法得到的日序列在月末的值；BE = r_US − TIPS 是恒等式拆分，
# 不用 T10YIE；ΔFX = 100 × Δln(美元兑人民币中间价月末值)。

# %%
spread_growth = month_log_sum(PANELS[B_GROWTH]["ret"])
spread_value = month_log_sum(PANELS[B_VALUE]["ret"])
spread_cy = month_log_sum(PANELS[CY_INDEX]["ret"])
spread_allshare = month_log_sum(PANELS[ALLSHARE_INDEX]["ret"])

rus_m = pd.Series(at_month_end(r_us), index=LAST_OF_MONTH.index)
rcn_m = pd.Series(at_month_end(r_cn), index=LAST_OF_MONTH.index)
tips_m = pd.Series(at_month_end(tips), index=LAST_OF_MONTH.index)
fx_m = pd.Series(at_month_end(fx), index=LAST_OF_MONTH.index)
be_m = rus_m - tips_m


def monthly_frame(growth: np.ndarray, value: np.ndarray) -> pd.DataFrame:
    """风格价差与 B2/B3 的自变量；所有差分相对上一个月末（百分点）。"""
    df = pd.DataFrame(
        {
            "spread": growth - value,
            "r_us": rus_m,
            "r_cn": rcn_m,
            "tips": tips_m,
            "be": be_m,
            "fx": fx_m,
        },
        index=LAST_OF_MONTH.index,
    )
    df["d_rus"] = df["r_us"].diff()
    df["d_rcn"] = df["r_cn"].diff()
    df["d_tips"] = df["tips"].diff()
    df["d_be"] = df["be"].diff()
    df["d_fx"] = 100.0 * np.log(df["fx"]).diff()
    df["signal_dt"] = SIGNAL_DATES
    return df


B23_MAIN = monthly_frame(spread_growth, spread_value)
B23_CY = monthly_frame(spread_cy, spread_allshare)

# 恒等式拆分：ΔTIPS + ΔBE 必须等于 Δr_US
for name, df in (("300价差", B23_MAIN), ("创业板价差", B23_CY)):
    both = df[["d_tips", "d_be", "d_rus"]].dropna()
    gap = float(np.max(np.abs(both["d_tips"] + both["d_be"] - both["d_rus"])))
    print(f"{name} 恒等式 |ΔTIPS + ΔBE − Δr_US| 最大 {gap:.3e}，n={len(both)}（阈值 1e-12）", flush=True)
    if gap > 1e-12:
        raise RuntimeError(f"{name} 的 ΔTIPS + ΔBE 与 Δr_US 不一致（{gap:.3e}），停止")

_main_ok = B23_MAIN["spread"].notna()
B23_MAIN_START = B23_MAIN.index[_main_ok][0]
B23_MAIN_END = B23_MAIN.index[_main_ok][-1]
log(f"300 风格价差样本 {B23_MAIN_START}..{B23_MAIN_END}，{int(_main_ok.sum())} 个月")
_cy_ok = B23_CY["spread"].notna()
B23_CY_START = B23_CY.index[_cy_ok][0]
B23_CY_END = B23_CY.index[_cy_ok][-1]
log(f"创业板价差样本 {B23_CY_START}..{B23_CY_END}，{int(_cy_ok.sum())} 个月")

B2_VARS = ("d_rus", "d_rcn")
B3_VARS = ("d_tips", "d_be", "d_fx", "d_rcn")
SAMPLES = {"full": None, "post_2015_08": pd.Period(POST_FX, "M")}


def regress(
    df: pd.DataFrame, spread_name: str, model: str, sample: str, x_cols: tuple[str, ...]
) -> list[dict[str, object]]:
    data = df[["spread", *x_cols]].dropna()
    lo = SAMPLES[sample]
    if lo is not None:
        data = data[data.index >= lo]
    if len(data) < 12:
        raise RuntimeError(f"{spread_name} {model} {sample} 样本太短：{len(data)}")
    fit, n = nw_ols(data["spread"], data[list(x_cols)], NW_LAGS)
    return [
        {"spread_name": spread_name, "model": model, "sample": sample, "var": col,
         "coef": float(fit.params[col]), "t_nw": float(fit.tvalues[col]), "n": n,
         "r2": float(fit.rsquared),
         "start": str(data.index[0]), "end": str(data.index[-1])}
        for col in x_cols
    ]


b23_rows: list[dict[str, object]] = []
for spread_name, df in (("hs300_growth_minus_value", B23_MAIN), ("cyb_minus_allshare", B23_CY)):
    b23_rows += regress(df, spread_name, "B2", "full", B2_VARS)
    b23_rows += regress(df, spread_name, "B3", "full", B3_VARS)
    b23_rows += regress(df, spread_name, "B3", "post_2015_08", B3_VARS)
b23_reg = pd.DataFrame(b23_rows)[
    ["spread_name", "model", "sample", "var", "coef", "t_nw", "n", "r2", "start", "end"]
]
show("b23_reg", b23_reg)


def pick(rows: pd.DataFrame, spread: str, model: str, sample: str, var: str) -> dict[str, object]:
    sel = rows[
        (rows["spread_name"] == spread) & (rows["model"] == model)
        & (rows["sample"] == sample) & (rows["var"] == var)
    ]
    if len(sel) != 1:
        raise RuntimeError(f"b23 行不唯一：{spread} {model} {sample} {var} -> {len(sel)}")
    return dict(sel.iloc[0])


# Holm：B2 的 Δr_US、B3 全样本的 ΔTIPS、B3（2015-08 起）的 ΔFX，三个单边 p（预期为负）
_HOLM_TESTS = (
    ("b2_rus", "hs300_growth_minus_value", "B2", "full", "d_rus"),
    ("b3_tips", "hs300_growth_minus_value", "B3", "full", "d_tips"),
    ("b3_fx", "hs300_growth_minus_value", "B3", "post_2015_08", "d_fx"),
)
_holm_rows = [pick(b23_reg, *t[1:]) for t in _HOLM_TESTS]
_p_one = [float(norm.cdf(float(r["t_nw"]))) for r in _holm_rows]
_p_holm = multipletests(_p_one, method="holm")[1]
_holm_cells: dict[str, object] = {}
for (name, *_), row, p1, ph in zip(_HOLM_TESTS, _holm_rows, _p_one, _p_holm, strict=True):
    neg = bool(float(row["coef"]) < 0 and float(row["t_nw"]) <= -2)
    _holm_cells |= {
        f"{name}_spread": row["spread_name"],
        f"{name}_model": f"{row['model']}/{row['sample']}",
        f"{name}_coef": row["coef"],
        f"{name}_t_nw": row["t_nw"],
        f"{name}_p_one_sided": p1,
        f"{name}_p_holm": ph,
        f"{name}_holm_lt_0.05": bool(ph < 0.05),
        f"{name}_neg": neg,
    }
b23_holm = pd.DataFrame([_holm_cells])
show("b23_holm 三个单边检验的 Holm 校正（判读列负号方向为预期方向）", b23_holm)
log(
    "b23 判读:"
    f" b2_rus_neg={_holm_cells['b2_rus_neg']}"
    f" b3_tips_neg={_holm_cells['b3_tips_neg']}"
    f" b3_fx_neg={_holm_cells['b3_fx_neg']}"
    f" | Holm 后 p<0.05:"
    f" b2_rus={_holm_cells['b2_rus_holm_lt_0.05']}"
    f" b3_tips={_holm_cells['b3_tips_holm_lt_0.05']}"
    f" b3_fx={_holm_cells['b3_fx_holm_lt_0.05']}"
)

# %% [markdown]
# ## 落盘：结果表、pit_report、run log

# %%
bundle = load_bundle()
datasets = (
    "src.wind.aindexvaluation",
    "src.wind.aindexeodprices",
    "src.wind.cbondcurvecnbd",
    "src.tushare.us_treasury_yield",
    "src.macro.fred_observation_vintage",
    "src.jydb.c_ed_macroindicatordata",
    "std.trade_calendar",
)
inputs = [
    {
        "dataset": ds,
        "grade": bundle.visibilities[ds].visibility.grade,
        "pit_from": None
        if bundle.visibilities[ds].pit_from is None
        else bundle.visibilities[ds].pit_from.isoformat(),
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
        "美债次日可见：T 日信号只用观测日严格早于 T 日的最近一期，超过 7 个自然日视为缺失。",
        "TIPS 按 ALFRED 版本逐信号日读 as_of，契约严格早于信号日，同样 7 天过期；不用当期修订值。",
        "BE = r_US − TIPS 是同一日的恒等式拆分，不是 T10YIE（不用市场通胀预期序列）。",
        "cn_ibo_7d 与 cn_usdcny_fix 是日频单版本、发布当天可见，as_of=AS_OF 整段读一次再按信号日"
        "对齐，与逐日读等价（中间价取信号日当天值，不取前值）。",
        "Wind 源镜像跟随源端修订，估值（PE_TTM、DIVIDEND_YIELD）、中债与指数收益都是当前版本，"
        "不是当时版本。",
        "所有样本都是已观察样本，结论最高第 2 类。",
    ],
}

panel_records = {}
_panel = pd.DataFrame(
    {"trade_dt": open_idx, "r_cn": r_cn, "r_us": r_us, "ibo": ibo, "tips": tips, "fx": fx}
)
for code in INDICES:
    p = PANELS[code]
    _panel[f"ret|{code}"] = p["ret"]
    _panel[f"pe|{code}"] = p["pe"]
    _panel[f"dy|{code}"] = p["dy"]
panel_records["daily"] = json.loads(_panel.to_json(orient="records", date_format="iso"))
_a_panel = pd.DataFrame({"trade_dt": open_idx, "DY": _a["DY"], "Dv": _a["Dv"],
                         "Du": _a["Du"], "V": _a["V"]})
for k in SIGNALS_A:
    _a_panel[f"pct_{k}"] = _pct[k]
panel_records["a_panel"] = json.loads(_a_panel.to_json(orient="records", date_format="iso"))
for code in (B_GROWTH, B_VALUE):
    p = PANELS[code]
    pcts: dict[str, pd.Series] = p["pct"]
    _b = pd.DataFrame({"trade_dt": open_idx, "U": p["U"], "V": p["V"],
                       "pct_U": pcts["U"], "pct_V": pcts["V"]})
    panel_records[f"b1_panel_{code}"] = json.loads(
        _b.to_json(orient="records", date_format="iso")
    )
panel_records["monthly"] = json.loads(
    A_MONTHLY.to_json(orient="records", date_format="iso")
)

input_digest = digest_json(
    {"params": PARAMS, "panels": panel_records,
     "starts": {"a": str(A_START.date()), "b1": str(B1_START.date()),
                "b23_main": str(B23_MAIN_START), "b23_cy": str(B23_CY_START)}}
)

results = {
    "a_repro": a_repro,
    "a_perf": a_perf,
    "a1": a1,
    "a2_spa": a2_spa,
    "a3_inference": a3_inference,
    "a3_grade": a3_grade,
    "a_corr": a_corr,
    "b1_perf": b1_perf,
    "b1_test": b1_test,
    "b23_reg": b23_reg,
    "b23_holm": b23_holm,
}
output_digest = digest_json(
    {k: json.loads(v.to_json(orient="records")) for k, v in results.items()}
)

run_id = new_run_id()
out_dir = paths.root / "research" / "erp_dividend_growth" / run_id
out_dir.mkdir(parents=True, exist_ok=False)
for name, frame in results.items():
    frame.to_csv(out_dir / f"{name}.csv", index=False)
summary = {
    "params": PARAMS,
    "starts": {"a": str(A_START.date()), "b1": str(B1_START.date()),
               "b23_main": str(B23_MAIN_START), "b23_cy": str(B23_CY_START)},
    "pit_report": pit_report,
    "input_digest": input_digest,
    "output_digest": output_digest,
    "research_only": True,
    "no_database_write": True,
    "production_qualified": False,
}
(out_dir / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
row_count = int(sum(len(frame) for frame in results.values()))
run_log_path = persist_run_log(
    RunLog(
        run_id=run_id,
        action="research.erp_dividend_growth",
        status="success",
        finished_at=datetime.now(UTC),
        elapsed_ms=int((time.monotonic() - started) * 1000),
        input_digest=input_digest,
        output_digest=output_digest,
        row_count=row_count,
        dml_count=0,
    ),
    paths,
)
conn.close()
hdr("落盘")
log(f"输出目录 {out_dir}")
log(f"run log {run_log_path}")
log(f"input_digest  {input_digest}")
log(f"output_digest {output_digest}")
log(f"总行数 {row_count}，总耗时 {time.monotonic() - started:.1f}s")
sys.stdout.flush()
