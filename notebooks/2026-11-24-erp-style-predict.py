# %% [markdown]
# # A 股股债利差第五阶段 C 节：实际利率能否预测下个月的风格价差
#
# 方案与判读标准见 `docs/research/erp-phase5-plan.md`（看结果前写定，本脚本不改口径）。
#
# - 断言：用同月价差复现报告五 B2（`spread ~ d_rus + d_rcn`，NW 滞后 3），系数与 t 值逐值一致。
# - C1：`fwd_spread_{t+1} ~ x_t` 单变量预测回归（ΔTIPS、Δr_US、Δln 中间价），单边 p 做 Holm 校正。
# - C2：扩张窗口样本外（R²_OS 与 Clark–West），只对 ΔTIPS 与 Δr_US。
# - C3：`ΔTIPS < 0` 持 300 成长、否则持 300 价值的轮动规则，对比 50/50 与两个买入持有。
#
# 读取、月末取值、TIPS 逐日 as_of、中间价、NW、Holm、平稳自助的写法全部照
# `2026-11-24-erp-dividend-growth.py`（逐段复制，不 import 那个脚本），
# 因此共同口径与报告五逐值可比。方向取自报告五同一样本，所有结论最高第 2 类。
#
# 只读：数据库只 SELECT；结果写到 `var/research/erp_style_predict/<run_id>/`，落 run log。

# %%
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from arch.bootstrap import StationaryBootstrap
from erp_lib import (
    TRADING_DAYS,
    asof_lookup,
    clark_west_np,
    forward_sum,
    nw_ols,
    oos_expanding,
    perf_daily,
    r2_os,
)
from scipy.stats import norm
from statsmodels.stats.multitest import multipletests

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.index_returns import PostgresIndexReturnRepository
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

G_TR = "h00918.CSI"  # 沪深 300 成长全收益
V_TR = "h00919.CSI"  # 沪深 300 价值全收益
CY_TR = "399606.SZ"  # 创业板全收益
ALL_TR = "h00985.CSI"  # 中证全指全收益（创业板的市场对照）
TR_CODES = (G_TR, V_TR, CY_TR, ALL_TR)

SPREAD_300 = "hs300_growth_minus_value"
SPREAD_CYB = "cyb_minus_allshare"
# 样本起点由「同月价差第一个非 NaN 月」决定，与报告五的 b23_reg 起点逐字一致
EXPECTED_START = {SPREAD_300: "2011-09", SPREAD_CYB: "2010-06"}

NW_LAGS = 3  # 主口径（h=1）的 Newey-West 滞后
H_MAIN = 1
H_SUPP = 3  # 补充：未来 3 个月价差之和
MIN_TRAIN = 36  # 扩张窗口 OOS 的最少训练月数
POST_FX = date(2015, 8, 1)  # 汇改以后的样本（计划 C1：Δln 中间价只用此段）
COST_BPS = 5  # 单边成本，bp
SEED = 20261124
BOOT_BLOCK = 63  # 交易日，C3 超额均值的平稳自助平均块长
N_BOOT = 2000
US_STALE_DAYS = 7  # 美债/TIPS 超过 7 个自然日未更新视为缺失
B2_REF_RUN = "428f1c1e4b334c54af0b8d664464a628"  # 报告五的运行号
REF_TOL = 1e-10  # 与报告五逐值比对的阈值

PARAMS = {
    "as_of": AS_OF.isoformat(),
    "start": START.isoformat(),
    "total_return_codes": {
        "growth_300": G_TR,
        "value_300": V_TR,
        "growth_cyb": CY_TR,
        "allshare": ALL_TR,
    },
    "spread_definition": "100 * [sum log1p(r_left) - sum log1p(r_right)] over the window, "
                         "NaN if any daily return in the window is missing",
    "spread_same_month": "(previous signal day, this signal day] in daily total returns",
    "fwd_spread": "from the close of T+1 (first open day after the signal day) to the close of "
                  "T'+1 (first open day after the next signal day), i.e. daily returns "
                  "(T+1, T'+1]; NaN if any day missing or T'+1 beyond as_of",
    "signal_day": "last open A-share day of the natural month; the last month is truncated at "
                  "as_of",
    "sample_start": "first month where the same-month spread is available: "
                    f"{EXPECTED_START[SPREAD_300]} (300) / {EXPECTED_START[SPREAD_CYB]} (cyb)",
    "rates_at_signal_day": {
        "r_us": "latest observation strictly before T-1 (7 calendar days stale limit)",
        "tips": "ALFRED vintage read per signal day as_of=T, strictly before T, 7 day stale limit",
        "be": "r_us - tips (identity split, not T10YIE)",
        "r_cn": "same day close",
        "fx": "cn_usdcny_fix same day value; d_fx = 100 * dln(fx)",
    },
    "deltas": "level(T) - level(previous signal day)",
    "nw_lags": {"h=1": NW_LAGS, "h=3": H_SUPP + 2, "rule": "max(nw_lags_h1, h + 2)"},
    "p_one_sided_rule": "Phi(t_nw), direction expected negative",
    "holm_tests_c1": ["d_tips full", "d_rus full", "d_fx T>=2015-08-01"],
    "post_fx_start": POST_FX.isoformat(),
    "h_main": H_MAIN,
    "h_supp": H_SUPP,
    "h_supp_target": "fwd_spread_t + fwd_spread_{t+1} + fwd_spread_{t+2}; NaN if any term NaN",
    "min_train_months": MIN_TRAIN,
    "c2_train_rule": "prediction for month i uses month j only if the fwd spread of j is already "
                     "realized by the signal day T_i, i.e. date(T'_j + 1) <= date(T_i) "
                     "(equivalently j <= i-2); baseline = mean of training fwd",
    "c2_cw_lags": "h + 2 = 3 (erp_lib.clark_west_np uses maxlags=max(h,1), so pass 3)",
    "cost_bps_one_way": COST_BPS,
    "cost_rule": "5bp * (|dw_growth| + |dw_value|) charged on the rebalance day T+1",
    "c3_rule": "d_tips(T) < 0 -> hold 300 growth next month, else (including ==0) hold 300 value; "
               "NaN d_tips -> no signal, carry the previous holding",
    "c3_execution": "holdings take effect at the close of T+1, so daily returns start at T+2; "
                    "the daily series starts on the first T+1 with a cash position (0 return "
                    "minus the entry cost)",
    "bench_5050": "rebalanced to 0.5/0.5 at every same rebalance day T+1, weights drift inside "
                  "the day, rebalance cost from drifted weights",
    "bh": "100% in h00918.CSI / h00919.CSI from the first T+1, no cost, first day in cash",
    "seed": SEED,
    "boot_block_days": BOOT_BLOCK,
    "n_boot": N_BOOT,
    "c3_bootstrap": {"class": "arch.bootstrap.StationaryBootstrap", "block_size": BOOT_BLOCK,
                     "reps": N_BOOT, "seed": SEED, "statistic": "mean of resampled centred "
                     "daily excess", "p_rule": "mean(boot_mean >= real_mean), one sided"},
    "us_stale_days": US_STALE_DAYS,
    "ann_excess": "mean(daily excess) * 244",
    "excess_sharpe": "mean(daily excess) / std(daily excess) * sqrt(244)",
    "hit_rate_month": "share of months with same-month-window excess > 0",
    "c_predict_holds": "Holm p of d_tips < 0.05 and C2 CW p of d_tips < 0.05",
    "c_rotation_holds": "ann_excess > 0 and p_boot < 0.10 and both half-sample ann_excess > 0, "
                        "adjudicated for tips_sign only",
    "research_class": "direction taken from the same sample as report five; class at most 2",
    "ref_b2_run": f"research/erp_dividend_growth/{B2_REF_RUN}",
}

started = time.monotonic()
settings = get_settings()
paths = resolve_var_paths(settings, repo_root=detect_repo_root())
conn = connect(settings, "src")
conn.read_only = True
macro = PostgresMacroRepository(conn)
index_returns = PostgresIndexReturnRepository(conn)
calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")

# %% [markdown]
# ## 读取
#
# 中债、中间价是日频单版本、发布当天可见，以研究截止日整段读一次再按信号日对齐，
# 与逐日读等价。美债按契约严格早于信号日（`观测日 < 信号日`，7 天过期）。
# TIPS 有版本，按逐日 as_of 读取（与报告五逐日读法相同，保证 ΔTIPS 逐值可比）。
# 本脚本不需要估值表（PE、股息率）。

# %%
open_days = [
    d.cal_dt
    for d in calendar.list_days(as_of=AS_OF, exchange="SSE", start=START, end=AS_OF)
    if d.is_open
]
open_idx = pd.DatetimeIndex(open_days)
log(f"交易日 {len(open_days)}")


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
fx_raw = point_series("cn_usdcny_fix")
log(
    f"中债 {len(r_cn_raw)} 美债 {len(r_us_raw)} 中间价 {int(fx_raw.notna().sum())}"
)

ret_rows = index_returns.list_returns(
    as_of=AS_OF, start=START, end=AS_OF, wind_codes=TR_CODES
)
ret_map = {
    code: pd.Series(
        {
            pd.Timestamp(r.trade_dt): (np.nan if r.pct_change is None else float(r.pct_change))
            for r in ret_rows
            if r.wind_code == code
        }
    ).sort_index()
    for code in TR_CODES
}
log(f"全收益行 {len(ret_rows)}")

# %% [markdown]
# ## 日频面板
#
# r_US 取观测日严格早于信号日的最近一期（信号日的前一天为截止），过期超过 7 天即缺失。
# TIPS 逐日读：每个信号日 as_of 下的最近一期（契约严格早于 as_of），同样 7 天过期。

# %%
r_cn = r_cn_raw.reindex(open_idx)
us_cut = open_idx - pd.Timedelta(days=1)
vals_us, obs_us = asof_lookup(r_us_raw, us_cut)
stale_us = (us_cut - pd.DatetimeIndex(obs_us)) > pd.Timedelta(days=US_STALE_DAYS)
r_us = pd.Series(np.where(stale_us | pd.isna(obs_us), np.nan, vals_us), index=open_idx)
assert (pd.DatetimeIndex(obs_us)[r_us.notna().to_numpy()] < open_idx[r_us.notna().to_numpy()]).all()

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
log(
    f"有效天数: r_cn {int(r_cn.notna().sum())} r_us {int(r_us.notna().sum())} "
    f"tips {int(tips.notna().sum())} fx {int(fx.notna().sum())}"
)

# 日收益换成小数，后续收益率区间一律用小数累乘
RG = (ret_map[G_TR].reindex(open_idx) / 100.0).to_numpy(dtype=float)
RV = (ret_map[V_TR].reindex(open_idx) / 100.0).to_numpy(dtype=float)
RCY = (ret_map[CY_TR].reindex(open_idx) / 100.0).to_numpy(dtype=float)
RALL = (ret_map[ALL_TR].reindex(open_idx) / 100.0).to_numpy(dtype=float)
for _name, _arr in (("growth", RG), ("value", RV), ("cyb", RCY), ("allshare", RALL)):
    _first = np.flatnonzero(np.isfinite(_arr))
    log(f"{_name} 全收益首个有效日 {open_idx[_first[0]].date()}，有效 {len(_first)} 天")

# %% [markdown]
# ## 月度面板
#
# 信号日 = 每月最后一个 A 股开市日（`SIGNAL_DATES`）。`ENTRY` 是信号日之后第一个开市日
# T+1 的位置，即「T+1 收盘成交」的成交日。`month_log_sum` 给出同月价差用的自然月对数
# 收益（窗口 = (上月信号日, 本月信号日]），与报告五逐值相同。

# %%
MONTH = open_idx.to_period("M")
LAST_OF_MONTH = pd.Series(open_idx, index=MONTH).groupby(level=0).max()
SIGNAL_DATES = pd.DatetimeIndex(LAST_OF_MONTH.to_numpy())
END_POS = np.array([open_idx.get_loc(d) for d in SIGNAL_DATES])
ENTRY = open_idx.searchsorted(SIGNAL_DATES, side="right")
N_M = len(SIGNAL_DATES)
log(f"月末交易日 {N_M} 天，{SIGNAL_DATES[0].date()}..{SIGNAL_DATES[-1].date()}")


def month_log_sum(ret: np.ndarray) -> np.ndarray:
    """自然月对数收益之和（百分点）：窗口 = (上月月末交易日, 本月月末交易日]，缺一天即 NaN。"""
    out = np.full(N_M, np.nan)
    for i in range(1, N_M):
        a, b = END_POS[i - 1] + 1, END_POS[i]
        if b < a:
            continue
        w = ret[a : b + 1]
        if len(w) and not np.isnan(w).any():
            out[i] = float(np.log1p(w).sum() * 100.0)
    return out


def fwd_spread(ret_left: np.ndarray, ret_right: np.ndarray) -> np.ndarray:
    """下月价差（百分点）：日收益区间 (T+1, T'+1]，即位置 ENTRY[i]+1 .. ENTRY[i+1]。

    T+1 收盘成交，所以 T+1 当日的收益不属于这个持仓；区间从 T+2 当日的收益开始，
    到下一信号日的 T'+1 当日收益为止。任一天缺失、或 T'+1 超出数据即为 NaN。
    """
    out = np.full(N_M, np.nan)
    for i in range(N_M - 1):
        a = int(ENTRY[i]) + 1
        b = int(ENTRY[i + 1])
        if b >= len(open_idx) or a > b:
            continue
        wl = ret_left[a : b + 1]
        wr = ret_right[a : b + 1]
        if len(wl) != b - a + 1 or np.isnan(wl).any() or np.isnan(wr).any():
            continue
        out[i] = float(np.log1p(wl).sum() * 100.0 - np.log1p(wr).sum() * 100.0)
    return out


def at_month_end(series: pd.Series) -> np.ndarray:
    return series.reindex(SIGNAL_DATES).to_numpy(dtype=float)


RUS_M = at_month_end(r_us)
RCN_M = at_month_end(r_cn)
TIPS_M = at_month_end(tips)
FX_M = at_month_end(fx)
BE_M = RUS_M - TIPS_M

SPREAD_ARR = {
    SPREAD_300: month_log_sum(RG) - month_log_sum(RV),
    SPREAD_CYB: month_log_sum(RCY) - month_log_sum(RALL),
}
FWD = {
    SPREAD_300: fwd_spread(RG, RV),
    SPREAD_CYB: fwd_spread(RCY, RALL),
}
FWD3 = {k: forward_sum(v, H_SUPP) for k, v in FWD.items()}

monthly = pd.DataFrame(
    {
        "period": LAST_OF_MONTH.index.astype(str).to_numpy(),
        "signal_dt": SIGNAL_DATES,
        "r_us": RUS_M,
        "r_cn": RCN_M,
        "tips": TIPS_M,
        "be": BE_M,
        "fx": FX_M,
    }
)
monthly["spread_300"] = SPREAD_ARR[SPREAD_300]
monthly["spread_cyb"] = SPREAD_ARR[SPREAD_CYB]
monthly["fwd_300"] = FWD[SPREAD_300]
monthly["fwd_cyb"] = FWD[SPREAD_CYB]
monthly["d_rus"] = monthly["r_us"].diff()
monthly["d_rcn"] = monthly["r_cn"].diff()
monthly["d_tips"] = monthly["tips"].diff()
monthly["d_be"] = monthly["be"].diff()
monthly["d_fx"] = 100.0 * np.log(monthly["fx"]).diff()
MONTH_DT = pd.DatetimeIndex(monthly["signal_dt"])
POST_FX_MASK = np.asarray(pd.Timestamp(POST_FX) <= MONTH_DT, dtype=bool)

# 恒等式拆分：ΔTIPS + ΔBE 必须等于 Δr_US（同一份数据上的代数恒等，不是拟合）
_both = monthly[["d_tips", "d_be", "d_rus"]].dropna()
_gap = float(np.max(np.abs(_both["d_tips"] + _both["d_be"] - _both["d_rus"])))
print(f"恒等式 |ΔTIPS + ΔBE − Δr_US| 最大 {_gap:.3e}，n={len(_both)}（阈值 1e-12）", flush=True)
if _gap > 1e-12:
    raise RuntimeError(f"ΔTIPS + ΔBE 与 Δr_US 不一致（{_gap:.3e}），停止")

# 样本起点：同月价差第一个非 NaN 月；之后的推断一律从该月起（计划「共同口径」）
SPREAD_START_POS: dict[str, int] = {}
for _key, _arr in SPREAD_ARR.items():
    _ok = np.flatnonzero(np.isfinite(_arr))
    if not len(_ok):
        raise RuntimeError(f"{_key} 没有非 NaN 月，停止")
    SPREAD_START_POS[_key] = int(_ok[0])
    _got = str(monthly["period"].iloc[SPREAD_START_POS[_key]])
    if _got != EXPECTED_START[_key]:
        raise RuntimeError(f"{_key} 样本起点 {_got} 与计划 {EXPECTED_START[_key]} 不一致，停止")
    _fwd_ok = np.flatnonzero(np.isfinite(FWD[_key]))
    log(
        f"{_key} 同月价差 {_got}..{monthly['period'].iloc[_ok[-1]]}，"
        f"{len(_ok)} 个月；下月价差 {monthly['period'].iloc[_fwd_ok[0]]}.."
        f"{monthly['period'].iloc[_fwd_ok[-1]]}，{len(_fwd_ok)} 个月"
    )

# %% [markdown]
# ## 先过的断言：同月价差复现报告五 B2
#
# `spread ~ d_rus + d_rcn`，Newey-West 滞后 3。系数、t 值与 n 必须与报告五
# `b23_reg.csv` 的 `hs300_growth_minus_value / B2 / full` 两行一致（阈值 1e-10）。
# 不一致说明读取、月末取值或差分口径已偏离，直接停下。

# %%
b2_ref_path = paths.root / "research" / "erp_dividend_growth" / B2_REF_RUN / "b23_reg.csv"
if not b2_ref_path.is_file():
    raise RuntimeError(f"报告五的 b23_reg.csv 不存在：{b2_ref_path}")
b2_ref = pd.read_csv(b2_ref_path, float_precision="round_trip")
b2_ref_rows = b2_ref[
    (b2_ref["spread_name"] == SPREAD_300) & (b2_ref["model"] == "B2")
    & (b2_ref["sample"] == "full")
].set_index("var")
if set(b2_ref_rows.index) != {"d_rus", "d_rcn"}:
    raise RuntimeError(f"报告五 B2 full 行不是 d_rus/d_rcn：{list(b2_ref_rows.index)}")
_b2_fit, _b2_n = nw_ols(monthly["spread_300"], monthly[["d_rus", "d_rcn"]], NW_LAGS)
_b2_idx = monthly[["spread_300", "d_rus", "d_rcn"]].dropna().index
if len(_b2_idx) != _b2_n:
    raise RuntimeError(f"B2 的有效行数 {len(_b2_idx)} 与 nw_ols 的 n={_b2_n} 不一致，停止")
_b2_first = str(monthly["period"].iloc[int(_b2_idx[0])])
_b2_last = str(monthly["period"].iloc[int(_b2_idx[-1])])
_repro_rows = []
for _var in ("d_rus", "d_rcn"):
    _c_ours = float(_b2_fit.params[_var])
    _t_ours = float(_b2_fit.tvalues[_var])
    _c_ref = float(b2_ref_rows.loc[_var, "coef"])
    _t_ref = float(b2_ref_rows.loc[_var, "t_nw"])
    _repro_rows.append(
        {"field": f"{_var}_coef", "ours": _c_ours, "report5": _c_ref,
         "diff": abs(_c_ours - _c_ref), "equal": bool(abs(_c_ours - _c_ref) <= REF_TOL)}
    )
    _repro_rows.append(
        {"field": f"{_var}_t_nw", "ours": _t_ours, "report5": _t_ref,
         "diff": abs(_t_ours - _t_ref), "equal": bool(abs(_t_ours - _t_ref) <= REF_TOL)}
    )
_repro_rows.append(
    {"field": "n", "ours": float(_b2_n), "report5": float(b2_ref_rows["n"].iloc[0]),
     "diff": abs(_b2_n - float(b2_ref_rows["n"].iloc[0])),
     "equal": bool(_b2_n == int(b2_ref_rows["n"].iloc[0]))}
)
_repro_rows.append(
    {"field": "start", "ours": _b2_first,
     "report5": str(b2_ref_rows["start"].iloc[0]), "diff": np.nan,
     "equal": bool(_b2_first == str(b2_ref_rows["start"].iloc[0]))}
)
_repro_rows.append(
    {"field": "end", "ours": _b2_last,
     "report5": str(b2_ref_rows["end"].iloc[0]), "diff": np.nan,
     "equal": bool(_b2_last == str(b2_ref_rows["end"].iloc[0]))}
)
b2_repro = pd.DataFrame(_repro_rows)[["field", "ours", "report5", "diff", "equal"]]
hdr("断言：同月价差复现报告五 B2（spread ~ d_rus + d_rcn，NW 滞后 3）")
show("b2_repro 断言（阈值 1e-10；n 与起止日期要求完全相等）", b2_repro)
if not bool(b2_repro["equal"].all()):
    raise RuntimeError("断言失败：B2 与报告五不一致，停止")
if _b2_n != 183:
    raise RuntimeError(f"断言失败：B2 样本数 {_b2_n} 不是 183，停止")
log(f"断言通过：B2 与报告五逐值一致，{_b2_first}..{_b2_last}，n={_b2_n}")

# %% [markdown]
# ## C1：单变量预测回归
#
# `fwd_spread_{t+1} ~ x_t`，Newey-West 滞后 3（h = 3 的补充用 h + 2 = 5）。
# 单边 p = Φ(t)，预期方向为负。三个主检验的单边 p 做 Holm 校正。
# 样本从该价差的第一个同月价差可用月开始（2011-09 / 2010-06），Δln 中间价只用
# T ≥ 2015-08-01 的月份。


# %%
def single_reg(
    spread: str,
    var: str,
    *,
    model: str = "M1",
    h: int = H_MAIN,
    sample: str = "full",
    extra: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    """未来价差（h=1 或 h=3 之和）对 ``var`` 的回归，``extra`` 为附加控制变量。

    列名沿用计划：spread_name、model、h、sample、var、coef、t_nw、p_one_sided、n、r2、
    start、end。同一回归的每个自变量各占一行，n 与 r2 相同。
    """
    y = FWD3[spread] if h == H_SUPP else FWD[spread]
    xs = {var: monthly[var].to_numpy(dtype=float)}
    for name in extra:
        xs[name] = monthly[name].to_numpy(dtype=float)
    lags = max(NW_LAGS, h + 2)
    mask = np.isfinite(y)
    for arr in xs.values():
        mask &= np.isfinite(arr)
    mask[: SPREAD_START_POS[spread]] = False
    if sample == "post_2015_08":
        mask &= POST_FX_MASK
    elif sample != "full":
        raise RuntimeError(f"未知样本标签 {sample}")
    idx = np.flatnonzero(mask)
    if len(idx) < MIN_TRAIN:
        raise RuntimeError(f"{spread} {model} {sample} {var} 样本太短：{len(idx)}")
    fit, n = nw_ols(
        pd.Series(y[idx], name="y"),
        pd.DataFrame({k: v[idx] for k, v in xs.items()}),
        lags,
    )
    r2 = float(fit.rsquared)
    out: list[dict[str, object]] = []
    for name in xs:
        coef = float(fit.params[name])
        t_nw = float(fit.tvalues[name])
        out.append(
            {"spread_name": spread, "model": model, "h": h, "sample": sample, "var": name,
             "coef": coef, "t_nw": t_nw, "p_one_sided": float(norm.cdf(t_nw)), "n": n,
             "r2": r2, "start": str(monthly["period"].iloc[idx[0]]),
             "end": str(monthly["period"].iloc[idx[-1]])}
        )
    _label = var + (f"+{extra[0]}" if len(extra) == 1 else "".join(f"+{e}" for e in extra))
    log(f"  {spread} {model} h={h} {sample} {_label}: n={n} lags={lags}")
    return out


C1_MAIN = (
    (SPREAD_300, "d_tips", "full"),
    (SPREAD_300, "d_rus", "full"),
    (SPREAD_300, "d_fx", "post_2015_08"),
)
main_rows: list[dict[str, object]] = []
for _spread, _var, _sample in C1_MAIN:
    main_rows += single_reg(_spread, _var, sample=_sample)

_p_main = [float(r["p_one_sided"]) for r in main_rows]
_p_holm = multipletests(_p_main, method="holm")[1]
c1_holm = pd.DataFrame(
    [
        {"spread_name": r["spread_name"], "var": r["var"], "sample": r["sample"],
         "coef": r["coef"], "t_nw": r["t_nw"], "p_one_sided": float(p1), "p_holm": float(ph),
         "n": r["n"], "start": r["start"], "end": r["end"],
         "holm_lt_0.05": bool(ph < 0.05), "neg_expected": bool(float(r["coef"]) < 0)}
        for r, p1, ph in zip(main_rows, _p_main, _p_holm, strict=True)
    ]
)
C1_TIPS_HOLM = float(c1_holm.loc[c1_holm["var"] == "d_tips", "p_holm"].iloc[0])

# 补充（只报告）：控制风格动量；h=3；ΔBE；创业板价差
supp_rows: list[dict[str, object]] = []
supp_rows += single_reg(SPREAD_300, "d_tips", extra=("spread_300",), model="M2")
supp_rows += single_reg(SPREAD_300, "d_tips", h=H_SUPP)
supp_rows += single_reg(SPREAD_300, "d_rus", h=H_SUPP)
supp_rows += single_reg(SPREAD_300, "d_be")
supp_rows += single_reg(SPREAD_CYB, "d_tips")
supp_rows += single_reg(SPREAD_CYB, "d_rus")
supp_rows += single_reg(SPREAD_CYB, "d_fx", sample="post_2015_08")

C1_COLS = ["spread_name", "model", "h", "sample", "var", "coef", "t_nw", "p_one_sided",
           "n", "r2", "start", "end"]
c1_reg = pd.DataFrame(main_rows + supp_rows)[C1_COLS]
show("c1_reg 预测回归（单边 p = Φ(t)；h=1 用 NW 滞后 3，h=3 用 5）", c1_reg)
show("c1_holm 三个主检验的单边 p 与 Holm 校正", c1_holm)
log(f"c1 判读: d_tips Holm p={C1_TIPS_HOLM:.4f}，<0.05 = {C1_TIPS_HOLM < 0.05}")

# %% [markdown]
# ### C1 补充：各预测变量的 AR(1)
#
# 计划要求报告变化量的一阶自相关，若大于 0.5 回头补 IVX。
# 配对用样本内相邻月（时间序列无缺月），两端都非 NaN 才进样本。

# %%
def ar1_rows(var: str, *, sample: str = "full", start: str = EXPECTED_START[SPREAD_300]) -> dict:
    x = monthly[var].to_numpy(dtype=float)
    lag = np.concatenate(([np.nan], x[:-1]))
    mask = np.isfinite(x) & np.isfinite(lag)
    mask[: int(np.flatnonzero(monthly["period"].to_numpy() >= start)[0])] = False
    if sample == "post_2015_08":
        mask &= POST_FX_MASK
    idx = np.flatnonzero(mask)
    fit, n = nw_ols(
        pd.Series(x[idx], name="y"), pd.DataFrame({"lag": lag[idx]}), 0
    )
    return {"var": var, "sample": sample, "ar1": float(fit.params["lag"]), "n": n,
            "start": str(monthly["period"].iloc[idx[0]]),
            "end": str(monthly["period"].iloc[idx[-1]]),
            "gt_0.5": bool(abs(float(fit.params["lag"])) > 0.5)}


c1_ar1 = pd.DataFrame(
    [
        ar1_rows("d_tips"),
        ar1_rows("d_rus"),
        ar1_rows("d_be"),
        ar1_rows("d_fx"),
        ar1_rows("d_fx", sample="post_2015_08"),
        ar1_rows("spread_300"),
        ar1_rows("spread_cyb", start=EXPECTED_START[SPREAD_CYB]),
    ]
)
show("c1_ar1 预测变量的一阶自相关（月度）", c1_ar1)

# %% [markdown]
# ## C2：扩张窗口样本外（只对 ΔTIPS 与 Δr_US）
#
# 第 i 个月的预测只用「下月价差在 T_i 已实现」的训练月 j：实现日是 T'_j 的下一开市日
# （第 j+1 个信号日之后的第一个开市日）的收盘，所以条件是 `date(T'_j+1) <= date(T_i)`。
# 该日期条件与 `erp_lib.oos_expanding` 的 `j <= i - h - 1`（h=1 时 `j <= i-2`）等价，
# 下面直接做全对全核对。训练行数 ≥ 36 才出预测；基准 = 训练段 fwd 的均值。
# Clark–West 用 `erp_lib.clark_west_np`，滞后按计划取 h + 2 = 3（该函数的滞后是
# `max(h,1)`，所以传 3）。

# %%
REALIZED_DT: dict[str, np.ndarray] = {}
for _key in SPREAD_ARR:
    _fwd = FWD[_key]
    _rdt = np.full(N_M, np.datetime64("NaT", "ns"))
    for _j in range(N_M - 1):
        _p = int(ENTRY[_j + 1])
        if _p < len(open_idx) and np.isfinite(_fwd[_j]):
            _rdt[_j] = open_idx[_p].to_datetime64()
    REALIZED_DT[_key] = _rdt

# 日期条件与索引条件的等价性核对（逐对，全部月份）
_tot_pairs = 0
for _key, _rdt in REALIZED_DT.items():
    _start = SPREAD_START_POS[_key]
    for _i in range(_start, N_M):
        _ti = MONTH_DT[_i].to_datetime64()
        for _j in range(_start, N_M):
            if np.isnat(_rdt[_j]):
                continue
            if bool(_rdt[_j] <= _ti) != bool(_j <= _i - 2):
                raise RuntimeError(f"{_key} 第 {_i} 月的日期规则与 j<=i-2 不等价，停止")
            _tot_pairs += 1
log(f"C2 训练窗口日期规则与 j<=i-2 等价，核对 {_tot_pairs} 对")


def oos_dated(spread: str, var: str) -> pd.DataFrame:
    """按日期规则做的扩张窗口样本外预测（逐月一行，含基准均值）。"""
    fwd = FWD[spread]
    x = monthly[var].to_numpy(dtype=float)
    rdt = REALIZED_DT[spread]
    start = SPREAD_START_POS[spread]
    rows: list[dict[str, object]] = []
    for i in range(start, N_M):
        if not np.isfinite(fwd[i]) or not np.isfinite(x[i]):
            continue
        ti = MONTH_DT[i].to_datetime64()
        train = np.flatnonzero(rdt <= ti)
        train = train[train >= start]
        if len(train) < MIN_TRAIN:
            continue
        if len(train) and int(train.max()) > i - 2:
            raise RuntimeError(f"{spread} 第 {i} 月用到了未实现的训练行，停止")
        m0 = float(fwd[train].mean())  # 基准：训练段均值（训练行已保证 fwd 非 NaN）
        ok = train[np.isfinite(x[train])]
        if len(ok) < MIN_TRAIN:
            continue
        design = np.column_stack([np.ones(len(ok)), x[ok]])
        coef = np.linalg.lstsq(design, fwd[ok], rcond=None)[0]
        rows.append(
            {"i": i, "period": str(monthly["period"].iloc[i]), "y": float(fwd[i]), "m0": m0,
             "model": float(coef[0] + x[i] * coef[1]), "n_train": len(train)}
        )
    if not rows:
        raise RuntimeError(f"{spread} {var} 没有样本外预测，停止")
    return pd.DataFrame(rows)


c2_rows: list[dict[str, object]] = []
for _var in ("d_tips", "d_rus"):
    fc = oos_dated(SPREAD_300, _var)
    # 与 erp_lib.oos_expanding 的样本口径核对：预测月集合、基准均值与模型预测必须一致
    _lib = oos_expanding(
        FWD[SPREAD_300],
        monthly[_var].to_numpy(dtype=float),
        H_MAIN,
        train_start=SPREAD_START_POS[SPREAD_300],
        oos_start=SPREAD_START_POS[SPREAD_300],
        min_history=MIN_TRAIN,
    )
    if list(_lib.index) != [int(v) for v in fc["i"]]:
        raise RuntimeError(f"{_var} 的样本外月份与 oos_expanding 不一致，停止")
    for _col, _mine in (("M0", fc["m0"]), ("model", fc["model"])):
        if not np.allclose(
            _lib[_col].to_numpy(dtype=float), _mine.to_numpy(dtype=float), rtol=0.0, atol=1e-12
        ):
            raise RuntimeError(f"{_var} 的 {_col} 与 oos_expanding 不一致，停止")
    cw_t, cw_p = clark_west_np(
        fc["y"].to_numpy(dtype=float),
        fc["m0"].to_numpy(dtype=float),
        fc["model"].to_numpy(dtype=float),
        3,
    )
    c2_rows.append(
        {"var": _var, "n_oos": len(fc), "oos_start": str(fc["period"].iloc[0]),
         "r2_os": r2_os(
             fc["y"].to_numpy(dtype=float),
             fc["model"].to_numpy(dtype=float),
             fc["m0"].to_numpy(dtype=float),
         ),
         "cw_t": cw_t, "cw_p": cw_p}
    )
c2_oos = pd.DataFrame(c2_rows)[["var", "n_oos", "oos_start", "r2_os", "cw_t", "cw_p"]]
show("c2_oos 扩张窗口样本外（基准 = 训练段均值）", c2_oos)
C2_TIPS_CW_P = float(c2_oos.loc[c2_oos["var"] == "d_tips", "cw_p"].iloc[0])
log(f"c2 判读: d_tips CW p={C2_TIPS_CW_P:.4f}，<0.05 = {C2_TIPS_CW_P < 0.05}")

# %% [markdown]
# ## C3：ΔTIPS 符号的轮动规则
#
# 规则：T 日 ΔTIPS < 0 → 下月持 300 成长；否则（含 = 0）持 300 价值。ΔTIPS 为 NaN 的月份
# 不出信号，沿用上月持仓（不外推、不用前值填 ΔTIPS）。
# 换仓在 T+1 收盘，所以日收益从 T+2 起计，与 `fwd_spread` 的区间 (T+1, T'+1] 一致。
# 成本 5 bp × (|Δw_成长| + |Δw_价值|)，在换仓日 T+1 从当日净收益里扣。
# 50/50 与轮动在同一换仓日再平衡，权重在日内随收益漂移，再平衡成本按漂移后权重算。
# 各序列都从同一个 T+1 开始（当天持现金、0 收益、只付建仓成本），到 AS_OF 止。

# %%
N_D = len(open_idx)
if open_idx[-1].date() != AS_OF:
    raise RuntimeError(f"最后一个开市日 {open_idx[-1].date()} 不是 as_of {AS_OF}，停止")


def first_usable_signal() -> tuple[int, int]:
    """第一个「信号与两条全收益都已就绪」的信号月及其 T+1 位置（fail-closed，不填）。"""
    for i in range(N_M):
        if not (np.isfinite(monthly["d_tips"].iloc[i]) and np.isfinite(monthly["d_rus"].iloc[i])):
            continue
        p = int(ENTRY[i])
        if p >= N_D:
            continue
        if np.isfinite(RG[p:]).all() and np.isfinite(RV[p:]).all():
            return i, p
    raise RuntimeError("没有同时满足 ΔTIPS/Δr_US 与全收益可用的信号日，停止")


C3_START_I, C3_START_POS = first_usable_signal()
END_POS_LAST = N_D - 1
log(
    f"C3 起点：信号月 {monthly['period'].iloc[C3_START_I]} 的 T+1 = "
    f"{open_idx[C3_START_POS].date()}，终点 {open_idx[-1].date()}"
    "（ΔTIPS 从 2003 年起就有，但 300 成长/价值全收益从 2011-08-15 起才有，"
    "所以起点被收益数据限制在这里）"
)


def rule_events(values: np.ndarray, start_i: int) -> tuple[dict[int, tuple[float, float]], int]:
    """每个月 T+1 的目标权重；NaN 信号不出事件（沿用上月），返回 (事件, NaN 月数)。"""
    events: dict[int, tuple[float, float]] = {}
    n_nan = 0
    for i in range(start_i, N_M):
        p = int(ENTRY[i])
        if p > END_POS_LAST:
            break
        d = float(values[i])
        if not np.isfinite(d):
            n_nan += 1
            continue
        events[p] = (1.0, 0.0) if d < 0 else (0.0, 1.0)
    return events, n_nan


def simulate(
    events: dict[int, tuple[float, float]], *, drift: bool, cost_bps: float
) -> pd.DataFrame:
    """逐日模拟：当日收益按昨日收盘持仓算，收盘换仓并扣成本，权重可选日内漂移。"""
    w_g = 0.0
    w_v = 0.0
    rec: list[tuple[float, float, float, float]] = []
    for p in range(C3_START_POS, N_D):
        rg = RG[p]
        rv = RV[p]
        if not (np.isfinite(rg) and np.isfinite(rv)):
            raise RuntimeError(f"持仓期间缺收益：{open_idx[p].date()}，停止")
        port = w_g * rg + w_v * rv
        if drift and (w_g > 0.0 or w_v > 0.0):
            gross = 1.0 + port
            w_g = w_g * (1.0 + rg) / gross
            w_v = w_v * (1.0 + rv) / gross
        turnover = 0.0
        if p in events:
            tg, tv = events[p]
            turnover = abs(tg - w_g) + abs(tv - w_v)
            w_g, w_v = tg, tv
        rec.append((w_g, w_v, turnover, port - cost_bps / 1e4 * turnover))
    return pd.DataFrame(
        rec, columns=["w", "w_value", "turnover", "ret"], index=open_idx[C3_START_POS:]
    )


EV_TIPS, NAN_TIPS = rule_events(monthly["d_tips"].to_numpy(dtype=float), C3_START_I)
EV_RUS, NAN_RUS = rule_events(monthly["d_rus"].to_numpy(dtype=float), C3_START_I)
log(f"C3 信号缺失月数：ΔTIPS {NAN_TIPS}，Δr_US {NAN_RUS}（缺失月沿用上月持仓，不外推）")
if NAN_TIPS > 0:
    print(f"警告：ΔTIPS 有 {NAN_TIPS} 个月为 NaN，这些月沿用上月持仓", flush=True)
if NAN_RUS > 0:
    print(f"警告：Δr_US 有 {NAN_RUS} 个月为 NaN，这些月沿用上月持仓", flush=True)

RUN_TIPS = simulate(EV_TIPS, drift=False, cost_bps=COST_BPS)
RUN_RUS = simulate(EV_RUS, drift=False, cost_bps=COST_BPS)
RUN_5050 = simulate(
    {int(ENTRY[i]): (0.5, 0.5) for i in range(C3_START_I, N_M) if int(ENTRY[i]) <= END_POS_LAST},
    drift=True,
    cost_bps=COST_BPS,
)
RUN_BH_G = simulate({C3_START_POS: (1.0, 0.0)}, drift=False, cost_bps=0.0)
RUN_BH_V = simulate({C3_START_POS: (0.0, 1.0)}, drift=False, cost_bps=0.0)

C3_RUNS = {
    "tips_sign": RUN_TIPS,
    "rus_sign": RUN_RUS,
    "bench_5050": RUN_5050,
    "bh_growth": RUN_BH_G,
    "bh_value": RUN_BH_V,
}


def perf_row(rule: str, frame: pd.DataFrame) -> dict[str, object]:
    perf = perf_daily(frame["ret"], frame[["w", "turnover"]])
    return {"rule": rule, "ann_return": perf["ann_return"], "ann_vol": perf["ann_vol"],
            "sharpe": perf["sharpe_rf0"], "max_dd": perf["max_dd"],
            "turnover_per_year": perf["turnover_per_year"]}


c3_perf = pd.DataFrame([perf_row(k, v) for k, v in C3_RUNS.items()])[
    ["rule", "ann_return", "ann_vol", "sharpe", "max_dd", "turnover_per_year"]
]
show("c3_perf（sharpe 用无风险利率 0）", c3_perf)


def stationary_boot_mean_p(series: pd.Series) -> float:
    """单边平稳自助：p = mean(自助样本均值 ≥ 真实均值)，在零均值化后的序列上重抽。"""
    x = series.to_numpy(dtype=float)
    real = float(x.mean())
    centered = x - real
    bs = StationaryBootstrap(BOOT_BLOCK, centered, seed=SEED)
    means = np.array([float(pos[0].mean()) for pos, _kw in bs.bootstrap(N_BOOT)])
    return float(np.mean(means >= real))


def monthly_windows() -> list[tuple[int, int, int]]:
    """每个月的（信号月位置, 窗口起始日位置, 窗口结束日位置），窗口 = 日位置 (T+1, T'+1]。"""
    out: list[tuple[int, int, int]] = []
    for i in range(C3_START_I, N_M - 1):
        a = int(ENTRY[i]) + 1
        b = int(ENTRY[i + 1])
        if b > END_POS_LAST or a > b:
            break
        out.append((i, a, b))
    return out


WINDOWS = monthly_windows()


def monthly_returns(frame: pd.DataFrame) -> np.ndarray:
    """每个窗口的净收益（百分点）：窗口内日净收益累乘后减 1。"""
    r = frame["ret"].to_numpy(dtype=float)
    return np.array(
        [
            100.0 * (float(np.prod(1.0 + r[a - C3_START_POS : b - C3_START_POS + 1])) - 1.0)
            for _i, a, b in WINDOWS
        ]
    )


B5050_M = monthly_returns(RUN_5050)


def c3_test_row(rule: str, frame: pd.DataFrame, monthly_excess: np.ndarray) -> dict[str, object]:
    excess = frame["ret"] - RUN_5050["ret"]
    ex = excess.to_numpy(dtype=float)
    half = len(ex) // 2
    real = float(ex.mean())
    p_boot = stationary_boot_mean_p(excess)
    ann_excess = real * TRADING_DAYS
    first_half = float(ex[:half].mean()) * TRADING_DAYS
    second_half = float(ex[half:].mean()) * TRADING_DAYS
    holds = ann_excess > 0 and p_boot < 0.10 and first_half > 0 and second_half > 0
    return {
        "rule": rule,
        "n_days": len(ex),
        "ann_excess_vs_5050": ann_excess,
        "excess_sharpe": float(ex.mean() / ex.std(ddof=1) * np.sqrt(TRADING_DAYS)),
        "hit_rate_month": float(np.mean(monthly_excess > 0)),
        "n_months": len(monthly_excess),
        "p_boot": p_boot,
        "first_half_ann_excess": first_half,
        "second_half_ann_excess": second_half,
        # 只在 tips_sign 上判读；rus_sign 按计划只报告，记 NaN
        "c_rotation_holds": bool(holds) if rule == "tips_sign" else np.nan,
    }


# %% [markdown]
# ### c3_monthly：每月的轮动与 50/50 收益
#
# 月度窗口与 `fwd_spread` 一致：(T+1, T'+1]，即日位置 ENTRY[i]+1 .. ENTRY[i+1]，取净收益
# 累乘。换仓日 T+1 的成本记在换仓日当天，因此落在上一个月的窗口里；两条规则换仓日相同，
# 超额的归属不受影响。

# %%
_c3m: list[dict[str, object]] = []
_hold: str | None = None
_rot_m = monthly_returns(RUN_TIPS)
for _k, (i, _a, _b) in enumerate(WINDOWS):
    signal = float(monthly["d_tips"].iloc[i])
    if np.isfinite(signal):
        _hold = "growth" if signal < 0 else "value"
    _c3m.append(
        {"period": str(monthly["period"].iloc[i]),
         "signal_dt": str(open_idx[int(END_POS[i])].date()), "signal_d_tips": signal,
         "hold": _hold if _hold is not None else "n/a",
         "rot_ret": float(_rot_m[_k]), "b5050_ret": float(B5050_M[_k]),
         "excess": float(_rot_m[_k] - B5050_M[_k])}
    )
c3_monthly = pd.DataFrame(_c3m)
show("c3_monthly 每月轮动 / 50-50 / 超额（百分点）", c3_monthly)

c3_test = pd.DataFrame(
    [
        c3_test_row("tips_sign", RUN_TIPS, monthly_returns(RUN_TIPS) - B5050_M),
        c3_test_row("rus_sign", RUN_RUS, monthly_returns(RUN_RUS) - B5050_M),
    ]
)
show("c3_test（日度超额与月度胜率；rus_sign 只报告）", c3_test)

# %% [markdown]
# ### 判读
#
# `c_predict_holds = (ΔTIPS 的 Holm p < 0.05) and (C2 的 ΔTIPS CW p < 0.05)`；
# `c_rotation_holds` 取自 tips_sign。两条都不成立时结论是「实际利率与风格价差只有同期关系」。

# %%
C_PREDICT_HOLDS = bool(C1_TIPS_HOLM < 0.05 and C2_TIPS_CW_P < 0.05)
C_ROTATION_HOLDS = bool(c3_test.loc[c3_test["rule"] == "tips_sign", "c_rotation_holds"].iloc[0])
hdr("判读")
print(
    pd.DataFrame(
        [
            {"rule": "c_predict_holds", "holds": C_PREDICT_HOLDS,
             "detail": f"d_tips Holm p={C1_TIPS_HOLM:.4f} (<0.05), "
                       f"C2 d_tips CW p={C2_TIPS_CW_P:.4f} (<0.05)"},
            {"rule": "c_rotation_holds", "holds": C_ROTATION_HOLDS,
             "detail": "ann_excess>0 and p_boot<0.10 and both halves>0 (tips_sign only)"},
        ]
    ).to_string(index=False),
    flush=True,
)

# %% [markdown]
# ## 落盘：结果表、pit_report、summary、run log

# %%
bundle = load_bundle()
datasets = (
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
        "cn_usdcny_fix 是日频单版本、发布当天可见，as_of=AS_OF 整段读一次再按信号日对齐，"
        "与逐日读等价（中间价取信号日当天值，不取前值）。",
        "Wind 源镜像跟随源端修订，指数收益都是当前版本，不是当时版本。",
        "下月价差从 T+1 收盘起算，到下一信号日的 T+1 收盘止，符合 T+1 成交：日收益区间 "
        "(T+1, T'+1]，任一天缺失即 NaN。",
        "方向取自报告五同一样本（同一段样本上 300 成长相对 300 价值的同期利率敏感度为负），"
        "结论最高第 2 类。",
        "所有样本都是已观察样本，结论最高第 2 类。",
    ],
}

panel_records: dict[str, object] = {}
_daily = pd.DataFrame(
    {"trade_dt": open_idx, "r_cn": r_cn, "r_us": r_us, "tips": tips, "fx": fx,
     "ret_growth": RG, "ret_value": RV, "ret_cyb": RCY, "ret_allshare": RALL}
)
panel_records["daily"] = json.loads(_daily.to_json(orient="records", date_format="iso"))
panel_records["monthly"] = json.loads(monthly.to_json(orient="records", date_format="iso"))

starts = {
    "spread_300": str(monthly["period"].iloc[SPREAD_START_POS[SPREAD_300]]),
    "spread_cyb": str(monthly["period"].iloc[SPREAD_START_POS[SPREAD_CYB]]),
    "b2_ref": f"{_b2_first}..{_b2_last}",
    "c3": f"{open_idx[C3_START_POS].date()}..{open_idx[-1].date()}",
    "c3_signal_month": str(monthly["period"].iloc[C3_START_I]),
    "c3_nan_months": {"d_tips": NAN_TIPS, "d_rus": NAN_RUS},
}
input_digest = digest_json({"params": PARAMS, "panels": panel_records, "starts": starts})

results = {
    "b2_repro": b2_repro,
    "c1_reg": c1_reg,
    "c1_holm": c1_holm,
    "c1_ar1": c1_ar1,
    "c2_oos": c2_oos,
    "c3_perf": c3_perf,
    "c3_test": c3_test,
    "c3_monthly": c3_monthly,
}
output_digest = digest_json(
    {k: json.loads(v.to_json(orient="records")) for k, v in results.items()}
)

judgement = {
    "c_predict_holds": C_PREDICT_HOLDS,
    "c_predict_detail": {
        "d_tips_holm_p": C1_TIPS_HOLM,
        "d_tips_holm_lt_0.05": bool(C1_TIPS_HOLM < 0.05),
        "c2_d_tips_cw_p": C2_TIPS_CW_P,
        "c2_d_tips_cw_lt_0.05": bool(C2_TIPS_CW_P < 0.05),
    },
    "c_rotation_holds": C_ROTATION_HOLDS,
    "c_rotation_detail": {
        "rule": "tips_sign",
        "ann_excess_vs_5050": float(
            c3_test.loc[c3_test["rule"] == "tips_sign", "ann_excess_vs_5050"].iloc[0]
        ),
        "p_boot": float(c3_test.loc[c3_test["rule"] == "tips_sign", "p_boot"].iloc[0]),
        "first_half_ann_excess": float(
            c3_test.loc[c3_test["rule"] == "tips_sign", "first_half_ann_excess"].iloc[0]
        ),
        "second_half_ann_excess": float(
            c3_test.loc[c3_test["rule"] == "tips_sign", "second_half_ann_excess"].iloc[0]
        ),
    },
    "rus_sign_note": "Δr_US 的同口径规则只报告，不参与判读",
    "research_class": "2 (direction taken from the already observed sample)",
}

run_id = new_run_id()
out_dir = paths.root / "research" / "erp_style_predict" / run_id
out_dir.mkdir(parents=True, exist_ok=False)
for name, frame in results.items():
    frame.to_csv(out_dir / f"{name}.csv", index=False)
summary = {
    "params": PARAMS,
    "starts": starts,
    "pit_report": pit_report,
    "judgement": judgement,
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
        action="research.erp_style_predict",
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
