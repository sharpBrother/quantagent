# %% [markdown]
# # A 股股债利差：仓位映射与风格指数复核（P4）
#
# 方案固定于 `docs/research/erp-p4-plan.md` 的第二节，判读标准看结果前已写定。
# 本脚本按该节实现，不改口径：
#
# - 三个指数各用自己的 PE_TTM 算 EY，利率与第二阶段相同；信号 V（主）、EY、M、U。
# - 五种事先固定的仓位映射 R0–R4；R4 只对 V 与 EY 做。
# - 主口径现金为同业拆借 7 天、单边成本 5 bp；敏感性现金为 10 年期国债、成本 0/10 bp。
# - 先断言：中证全指上 V、M 的 R0（10Y 现金、成本 0）与报告一 `p01_daily.csv` 逐位相等。
#
# 只读：数据库只 SELECT；结果写到 `var/research/erp_position_mapping/<run_id>/`，落 run log。

# %%
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
from arch.bootstrap import SPA
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

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 80)
pd.set_option("display.max_rows", 300)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def hdr(title: str) -> None:
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}", flush=True)


def show(title: str, frame: pd.DataFrame) -> None:
    print(f"\n--- {title} ---", flush=True)
    out = frame.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = out[col].round(4)
    print(out.to_string(index=False), flush=True)


# %% [markdown]
# ## 固定参数

# %%
AS_OF = date(2026, 11, 20)  # 研究截止日，固定以便复现
START = date(2002, 1, 1)
MAIN = "000985.CSI"
# 估值代码 -> 全收益指数代码
INDICES = {
    "000985.CSI": "h00985.CSI",  # 中证全指（主口径）
    "000922.CSI": "h00922.CSI",  # 中证红利（价值）
    "399006.SZ": "399606.SZ",  # 创业板指（成长）
}
SIGNALS = ("V", "EY", "M", "U")
# 信号名 -> PANELS 里的日频水平序列键
LEVEL_KEY = {"EY": "ey", "V": "V", "U": "U", "M": "M"}
MAPPINGS = ("R0", "R1", "R2", "R3", "R4")
R4_SIGNALS = ("V", "EY")  # 计划：R4 只对 V 和 EY 做
US_STALE_DAYS = 7
PCT_YEARS = 5
BAND = 0.10
SIGMA_WINDOW = 60
R4_GAMMA = 3.0
R4_VAR_WINDOW = 60
TAU = pd.Timestamp("2022-04-12")  # 报告一的切换日，Q2a 用它算占比
CASH_MAIN = "cash_ibo7d"
CASH_LEGS = ("cash_ibo7d", "cash_10y")
COST_MAIN = 5
PERF_SPECS = (
    (CASH_MAIN, COST_MAIN),
    (CASH_MAIN, 0),
    (CASH_MAIN, 10),
    ("cash_10y", 0),
    ("cash_10y", 5),
    ("cash_10y", 10),
)
SEED = 20261124
HORIZONS = (1, 3, 6, 12)
MIN_HISTORY = 60
N_BOOT = 2000
BOOT_BLOCK = 12  # 月频零假设自助法的平均块长（月），同报告二
SPA_BLOCK = 63  # 交易日
SPA_REPS = 2000
NW_LAGS = 3  # 月频择时回归的 Newey-West 滞后
Q2D_INDICES = ("000922.CSI", "399006.SZ")  # 000985 不重算，见报告二
Q2D_MODELS = ("EY", "V", "U", "M")
# 复现基准：报告一（口径与本脚本的断言段一致）
P01_RUN = "ae2a020e869945bc87294275e9e14580"

PARAMS = {
    "as_of": AS_OF.isoformat(),
    "start": START.isoformat(),
    "main_index": MAIN,
    "indices": dict(INDICES),
    "signals": list(SIGNALS),
    "mappings": {
        "R0": "target=pct, ratchet one_way=True, band 0.10, lag 1",
        "R1": "target=pct, ratchet one_way=False, band 0.10, lag 1",
        "R2": "target=pct only on last trading day of month, others NaN, one_way=False, band 0.10",
        "R3": "target=pct * min(1, sigma_bar/sigma60), one_way=False, band 0.10",
        "R4": "monthly mean-variance, gamma=3, w=clip(100*f/(gamma*var),0,1), one_way=False",
    },
    "r4_signals": list(R4_SIGNALS),
    "r4_detail": {
        "panel": "signal day = last trading day of month; fwd1 = log return (pct) from next day "
        "after signal to next month's next-day-after-signal close",
        "cash_m": "sum(log1p(cash_accrual(cn_ibo_7d))) over the same interval, pct",
        "ex": "fwd1 - cash_m",
        "predictor": "signal level (EY / V) at the signal day, as in report two P1.1/P1.3",
        "forecast": "oos_expanding(ex, level, 1, train_start=first valid month, "
        "oos_start=first month with >=60 training months, min_history=60)",
        "var": "variance (ddof=1) of the last 60 valid training ex months with q <= i-2",
        "weight": "clip(100*f/(3*var), 0, 1); units as in report two P1.3",
    },
    "r3_detail": "sigma60 = ret.rolling(60).std()*sqrt(244) and expanding median use the full "
    "available daily return history of the index (backward looking only)",
    "band": BAND,
    "sigma_window": SIGMA_WINDOW,
    "tau": str(TAU.date()),
    "cash_main": CASH_MAIN,
    "cash_legs": list(CASH_LEGS),
    "cost_main_bps": COST_MAIN,
    "cost_bps": sorted({c for _, c in PERF_SPECS}),
    "perf_specs": [{"cash_leg": leg, "cost_bps": c} for leg, c in PERF_SPECS],
    "net_ret": "ret - cost_bps/1e4 * turnover",
    "seed": SEED,
    "horizons": list(HORIZONS),
    "min_history": MIN_HISTORY,
    "n_boot": N_BOOT,
    "boot_block": BOOT_BLOCK,
    "spa": {
        "block_size": SPA_BLOCK,
        "reps": SPA_REPS,
        "bootstrap": "stationary",
        "studentize": True,
        "seed": SEED,
        "loss": "-net_ret",
    },
    "nw_lags": NW_LAGS,
    "q2d": {
        "predictor": "signal level (EY / V / U / M) at the signal day, as in report two P1.1",
        "train_start": "first valid month of the index",
        "seed_rule": "SeedSequence(20261124).spawn(2)[index].spawn(4)[model]",
    },
    "p01_run": f"research/erp_max_attribution/{P01_RUN}",
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
# 与报告一同口径：估值、中债、全收益指数是 `same_day_close`；美债严格早于信号日（7 天过期）；
# 同业拆借 7 天整段读一次、按信号日 as-of 对齐（日频单版本，等价于逐日读）。

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
pe_map = {
    code: pd.Series(
        {
            pd.Timestamp(r.trade_dt): (np.nan if r.pe_ttm is None else float(r.pe_ttm))
            for r in val_rows
            if r.wind_code == code
        }
    ).sort_index()
    for code in INDICES
}
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
log(f"中债 {len(r_cn_raw)} 美债 {len(r_us_raw)} 同业拆借 {len(ibo_raw)}")

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
# `M = EY − max(r_US, r_CN)`、`U = EY − r_US`：任一利率缺失即缺失（np.maximum 传播 NaN）。

# %%
r_cn = r_cn_raw.reindex(open_idx)
us_cut = open_idx - pd.Timedelta(days=1)
vals, obs = asof_lookup(r_us_raw, us_cut)
stale = (us_cut - pd.DatetimeIndex(obs)) > pd.Timedelta(days=US_STALE_DAYS)
r_us = pd.Series(np.where(stale | pd.isna(obs), np.nan, vals), index=open_idx)
assert (pd.DatetimeIndex(obs)[r_us.notna().to_numpy()] < open_idx[r_us.notna().to_numpy()]).all()

vals_ibo, obs_ibo = asof_lookup(ibo_raw.dropna(), open_idx)
stale_ibo = (open_idx - pd.DatetimeIndex(obs_ibo)) > pd.Timedelta(days=US_STALE_DAYS)
ibo = pd.Series(np.where(stale_ibo | pd.isna(obs_ibo), np.nan, vals_ibo), index=open_idx)

CASH_10Y = cash_accrual(r_cn)
CASH_IBO = cash_accrual(ibo)
CASH_BY_LEG = {"cash_10y": CASH_10Y, "cash_ibo7d": CASH_IBO}
log(f"有效天数: r_cn {r_cn.notna().sum()} r_us {r_us.notna().sum()} ibo {ibo.notna().sum()}")

# 每月最后一个交易日：R2 的目标只在这些日子更新
_month = open_idx.to_period("M")
_last_of_month = pd.Series(open_idx, index=_month).groupby(level=0).max()
KEEP = pd.Series(
    open_idx.isin(pd.DatetimeIndex(_last_of_month.to_numpy())), index=open_idx, name="last_of_month"
)
log(f"月末交易日 {int(KEEP.sum())} 天")


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

    训练月 q 必须满足 ``q + h + 1 <= i``（h 期收益在 i 的信号日之前已实现），
    与 `erp_lib.oos_expanding` 的上界一致；这里只是把首个可用月份显式算出来。
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


def build_panel(code: str) -> dict[str, object]:
    """一个指数的日频面板：EY / V / U / M、四个 5 年分位、全收益日收益。"""
    tr = INDICES[code]
    pe = pe_map[code].reindex(open_idx)
    ey = pd.Series(np.where(pe > 0, 100.0 / pe, np.nan), index=open_idx)
    v = ey - r_cn
    u = ey - r_us
    m = ey - np.maximum(r_us, r_cn)
    pcts = {
        k: rolling_percentile(s, PCT_YEARS) for k, s in (("EY", ey), ("V", v), ("U", u), ("M", m))
    }
    ok = pd.concat(pcts, axis=1).notna().all(axis=1)
    if not ok.any():
        raise RuntimeError(f"{code} 四个 5 年分位没有共同有效日，停止")
    own_start = ok[ok].index[0]
    if not ok.loc[own_start:].all():
        raise RuntimeError(f"{code} 起点之后有分位缺失，停止")
    ret = ret_map[tr].reindex(open_idx) / 100.0
    return {
        "code": code,
        "tr": tr,
        "ey": ey,
        "V": v,
        "U": u,
        "M": m,
        "pct": pcts,
        "own_start": own_start,
        "ret": ret,
    }


PANELS = {code: build_panel(code) for code in INDICES}
OWN_START = {code: p["own_start"] for code, p in PANELS.items()}
hdr("各指数起点（V、EY、M、U 四个 5 年分位都有值的第一天）")
print(
    pd.DataFrame(
        [
            {"index": code, "total_return": p["tr"], "own_start": str(p["own_start"].date())}
            for code, p in PANELS.items()
        ]
    ).to_string(index=False),
    flush=True,
)
for code, p in PANELS.items():
    print(
        f"  {code}: EY {int(p['ey'].notna().sum())} 天，"
        f"V/U/M 分位起点 {p['own_start'].date()}，"
        f"全收益起点 {p['ret'].first_valid_index().date()}",
        flush=True,
    )

# %% [markdown]
# ## 第一步：复现断言
#
# 中证全指上，V、M 的 R0（10Y 现金、成本 0）必须与报告一的 `p01_daily.csv` 逐位相等。
# 断言窗口直接取该文件的第一行日期（报告一的共同起点 2010-10-13 由 5 个信号含 TIPS 决定，
# 与本脚本四信号起点不同，所以断言只在这个窗口上做）。

# %%
p01_path = paths.root / "research" / "erp_max_attribution" / P01_RUN / "p01_daily.csv"
if not p01_path.is_file():
    raise RuntimeError(f"报告一的 p01_daily.csv 不存在：{p01_path}")
p01 = pd.read_csv(p01_path, index_col=0, parse_dates=True, float_precision="round_trip")
START_P01 = p01.index[0]


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


_p985 = PANELS[MAIN]
repro_rows = []
for tag, sig, w_col, r_col in (("V", "V", "b_w", "b_ret"), ("M", "M", "a_w", "a_ret")):
    run = ratchet(
        _p985["pct"][sig].loc[START_P01:],
        _p985["ret"].loc[START_P01:],
        lag=1,
        cash=CASH_10Y.loc[START_P01:],
    )
    n_w = assert_identical(run["w"], p01[w_col], f"{tag} w")
    n_r = assert_identical(run["ret"], p01[r_col], f"{tag} ret")
    repro_rows.append(
        {
            "signal": tag,
            "mapping": "R0",
            "window": str(START_P01.date()),
            "points": n_w,
            "equal_w": True,
            "equal_ret": True,
        }
    )
    log(f"断言 {tag}: w/ret 与 p01_daily 逐位相等（{n_r} 个交易日）")
repro = pd.DataFrame(repro_rows)
print(repro.to_string(index=False), flush=True)

# %% [markdown]
# ## 月度面板（R4 与 Q2d 共用）
#
# 信号日 = 每月最后一个交易日；`fwd1` 是从信号日次一交易日收盘到下月信号日次一交易日收盘的
# 全收益对数收益（百分点），与报告二 P1.3 同口径。月现金用同业拆借 7 天在同一区间累计。
# 先断言此口径下 000985 的 `fwd1` 与报告二上游 `monthly.csv` 的 `fwd1|000985.CSI` 一致。


# %%
def build_monthly(
    open_idx: pd.DatetimeIndex, ret: pd.Series, cash_daily: pd.Series
) -> pd.DataFrame:
    """月频面板：period、signal_dt、fwd1（百分点，对数）、cash_m（百分点，对数）。"""
    month = open_idx.to_period("M")
    last = pd.Series(open_idx, index=month).groupby(level=0).max()
    sig_dt = pd.DatetimeIndex(last.to_numpy())
    entry = open_idx.searchsorted(sig_dt, side="right")
    n = len(sig_dt)
    ret_arr = ret.to_numpy(dtype=float)
    cash_arr = cash_daily.to_numpy(dtype=float)
    fwd1 = np.full(n, np.nan)
    cash_m = np.full(n, np.nan)
    for i in range(n - 1):
        a, b = entry[i] + 1, entry[i + 1]
        if b >= len(open_idx) or a > b:
            continue
        wr = ret_arr[a : b + 1]
        wc = cash_arr[a : b + 1]
        if len(wr) and not np.isnan(wr).any():
            fwd1[i] = float(np.log1p(wr).sum() * 100.0)
        if len(wc) and not np.isnan(wc).any():
            cash_m[i] = float(np.log1p(wc).sum() * 100.0)
    return pd.DataFrame(
        {
            "period": last.index.astype(str).to_numpy(),
            "signal_dt": sig_dt,
            "fwd1": fwd1,
            "cash_m": cash_m,
        }
    )


for code, p in PANELS.items():
    mp = build_monthly(open_idx, p["ret"], CASH_IBO)
    for sig in SIGNALS:
        mp[f"pct|{sig}"] = p["pct"][sig].reindex(pd.DatetimeIndex(mp["signal_dt"])).to_numpy()
        mp[f"level|{sig}"] = p[LEVEL_KEY[sig]].reindex(pd.DatetimeIndex(mp["signal_dt"])).to_numpy()
    p["monthly"] = mp
    log(f"{code} 月频面板 {len(mp)} 个月 {mp['period'].iloc[0]}..{mp['period'].iloc[-1]}")

# 断言：000985 的 fwd1 与报告二上游 monthly.csv 逐值一致（阈值 1e-9）
UP_ROBUST = paths.root / "research" / "erp_rate_anchor" / "05cf3475b6354fa8be2c4d3f7bab942f"
up_monthly = pd.read_csv(UP_ROBUST / "monthly.csv", float_precision="round_trip")
up_period = up_monthly["period"].to_numpy()
up_fwd = up_monthly["fwd1|000985.CSI"].to_numpy()
mp985 = PANELS[MAIN]["monthly"]
cmp_df = pd.DataFrame({"period": mp985["period"], "ours": mp985["fwd1"]}).merge(
    pd.DataFrame({"period": up_period, "up": up_fwd}), on="period", how="inner"
)
if not np.array_equal(np.isnan(cmp_df["ours"]), np.isnan(cmp_df["up"])):
    raise RuntimeError("000985 的 fwd1 NaN 位置与上游 monthly.csv 不一致，停止")
_both = ~np.isnan(cmp_df["ours"])
_diff = float(np.max(np.abs(cmp_df.loc[_both, "ours"] - cmp_df.loc[_both, "up"])))
print(f"fwd1 断言: {int(_both.sum())} 个月对齐，最大绝对差 {_diff:.3e}（阈值 1e-9）", flush=True)
if _diff >= 1e-9:
    raise RuntimeError(f"000985 的 fwd1 与上游不一致（{_diff:.3e}），停止")
log("fwd1 断言通过")

# %% [markdown]
# ## R4 目标序列（月频均值-方差）
#
# 对每个指数、V 与 EY 各做一次：扩张窗口回归预测下月超额收益 f（预测变量是信号的水平值
# V / EY，与报告二 P1.1/P1.3 相同，不是分位），方差取最近 60 个训练月的 ex 方差，`w = clip(100·f/(3·var), 0, 1)`。w 放在该月信号日作为目标，其余日 NaN；
# ``ratchet`` 在目标出现前不持仓，所以 R4 的绩效从首个有仓位的日子单独算。

# %%
r4_info: dict[str, dict[str, object]] = {}
for code, p in PANELS.items():
    mp = p["monthly"]
    ex = (mp["fwd1"] - mp["cash_m"]).to_numpy(dtype=float)
    targets: dict[str, pd.Series] = {}
    info: dict[str, object] = {}
    for sig in R4_SIGNALS:
        x = mp[f"level|{sig}"].to_numpy(dtype=float)
        valid = ~np.isnan(ex) & ~np.isnan(x)
        if not valid.any():
            raise RuntimeError(f"{code} {sig} 没有可用的月频样本，停止")
        first = int(np.flatnonzero(valid)[0])
        oos_start = first_oos_month(ex, 1, first, MIN_HISTORY)
        fc = oos_expanding(
            ex, x, 1, train_start=first, oos_start=oos_start, min_history=MIN_HISTORY
        )
        tgt = pd.Series(np.nan, index=open_idx)
        n_use = 0
        first_dt = None
        w_hist: list[float] = []
        for i, row in fc.iterrows():
            f = float(row["model"])
            if np.isnan(f):
                continue
            hist = np.arange(first, int(i) - 1)  # 训练月 q <= i-2
            hist = hist[~np.isnan(ex[hist])]
            if len(hist) < MIN_HISTORY:
                continue
            var = float(np.var(ex[hist[-R4_VAR_WINDOW:]], ddof=1))
            if not var > 0:
                continue
            w = float(np.clip(100.0 * f / (R4_GAMMA * var), 0.0, 1.0))
            d = mp["signal_dt"].iloc[int(i)]
            if first_dt is None:
                first_dt = d
            tgt.loc[d] = w
            w_hist.append(w)
            n_use += 1
        targets[sig] = tgt
        info[sig] = {
            "panel_first_month": str(mp["period"].iloc[first]),
            "oos_start_month": str(mp["period"].iloc[oos_start]),
            "n_predictions": n_use,
            "w_min": float(np.min(w_hist)) if w_hist else None,
            "w_max": float(np.max(w_hist)) if w_hist else None,
            "w_mean": float(np.mean(w_hist)) if w_hist else None,
            "n_nonzero": int(np.sum(np.asarray(w_hist) > 0)) if w_hist else 0,
            "first_target_dt": None if first_dt is None else str(first_dt.date()),
        }
    p["r4_target"] = targets
    r4_info[code] = info
    log(f"{code} R4: V {info['V']} | EY {info['EY']}")

# %% [markdown]
# ## 五种映射与两条现金腿
#
# 每条现金腿都要重跑 ``ratchet``：现金同时进入当日收益和仓位漂移，不能只换 rf。
# R2 的 NaN 目标不需要前向填充：``ratchet`` 只在目标非 NaN 时调仓，NaN 等价于「目标不变」，
# 仓位既不重置也不被误当成 0，只是按当日收益漂移。

# %%
RUNS: dict[str, dict[str, dict[tuple[str, str], pd.DataFrame]]] = {}
for leg in CASH_LEGS:
    cash_leg = CASH_BY_LEG[leg]
    per_index: dict[str, dict[tuple[str, str], pd.DataFrame]] = {}
    for code, p in PANELS.items():
        own = p["own_start"]
        rr = p["ret"].loc[own:]
        cc = cash_leg.loc[own:]
        sigma60 = p["ret"].rolling(SIGMA_WINDOW).std() * np.sqrt(TRADING_DAYS)
        sigma_bar = sigma60.expanding().median()
        runs: dict[tuple[str, str], pd.DataFrame] = {}
        for sig in SIGNALS:
            base = p["pct"][sig]
            pp = base.loc[own:]
            runs[(sig, "R0")] = ratchet(pp, rr, lag=1, cash=cc)
            runs[(sig, "R1")] = ratchet(pp, rr, lag=1, cash=cc, one_way=False)
            runs[(sig, "R2")] = ratchet(pp.where(KEEP.loc[own:]), rr, lag=1, cash=cc, one_way=False)
            vol_target = base * np.minimum(1.0, sigma_bar / sigma60)
            runs[(sig, "R3")] = ratchet(vol_target.loc[own:], rr, lag=1, cash=cc, one_way=False)
            if sig in R4_SIGNALS:
                runs[(sig, "R4")] = ratchet(
                    p["r4_target"][sig].loc[own:], rr, lag=1, cash=cc, one_way=False
                )
        per_index[code] = runs
    RUNS[leg] = per_index
    log(f"现金腿 {leg} 完成：{sum(len(v) for v in per_index.values())} 条策略")


def net_of(leg: str, code: str, sig: str, mp: str, cost_bps: int) -> pd.Series:
    run = RUNS[leg][code][(sig, mp)]
    return run["ret"] - cost_bps / 1e4 * run["turnover"]


OWN_START_COMMON = max(OWN_START.values())
R4_START = {code: RUNS[CASH_MAIN][code][("V", "R4")]["ret"].dropna().index[0] for code in INDICES}
WINDOWS = {
    code: {
        "own": OWN_START[code],
        "r4_window": R4_START[code],
        "common": OWN_START_COMMON,
    }
    for code in INDICES
}
log(
    f"共同区间起点 {OWN_START_COMMON.date()}；R4 起点 "
    + " ".join(f"{k} {v.date()}" for k, v in R4_START.items())
)

BH_RUN = {
    code: pd.DataFrame({"w": 1.0, "turnover": 0.0, "ret": p["ret"]}) for code, p in PANELS.items()
}

# %% [markdown]
# ## p4_perf：绩效表
#
# 窗口口径：
# - `own`：该指数四个分位都有值的第一天到 AS_OF；
# - `r4_window`：该指数 R4 首次建仓后的第一个收益日（即 R4 的 ret 首个非 NaN 日）到 AS_OF；
#   这样同一区间内其余映射与 R4 的收益日完全一致（R4 建仓当日还没有持仓收益）。
# - `common`：三个指数共同区间（创业板起点）到 AS_OF。
#
# 成本按成交日扣：`ret_net = ret − c/1e4 × turnover`，不影响仓位路径。

# %%
perf_rows: list[dict[str, object]] = []
for code, p in PANELS.items():
    for wname, wstart in WINDOWS[code].items():
        for leg, cost in PERF_SPECS:
            cash_leg = CASH_BY_LEG[leg]
            for sig in SIGNALS:
                for mp in MAPPINGS:
                    if (sig, mp) not in RUNS[leg][code]:
                        continue
                    run = RUNS[leg][code][(sig, mp)]
                    r = run["ret"].loc[wstart:AS_OF]
                    net = net_of(leg, code, sig, mp, cost).loc[wstart:AS_OF]
                    # 仓位恒为 0（或回撤为 0）时，erp_lib 里的 calmar / 夏普分母为 0，结果本身
                    # 是 NaN，这里只压掉 numpy 告警，不改任何数值。
                    with np.errstate(divide="ignore", invalid="ignore"):
                        perf = perf_daily(net, run.loc[r.index], rf=cash_leg)
                    used = net.dropna().index
                    perf_rows.append(
                        {
                            "index": code,
                            "window": wname,
                            "cash_leg": leg,
                            "cost_bps": cost,
                            "signal": sig,
                            "mapping": mp,
                            "start": str(used[0].date()),
                            "end": str(used[-1].date()),
                        }
                        | perf
                    )
            # 买入持有：满仓全收益指数，首日无收益（与报告一同口径），不计成本
            bh = p["ret"].loc[wstart:AS_OF].copy()
            bh.iloc[0] = np.nan
            bh_run = BH_RUN[code].reindex(bh.index)
            with np.errstate(divide="ignore", invalid="ignore"):
                perf = perf_daily(bh, bh_run, rf=cash_leg)
            used = bh.dropna().index
            perf_rows.append(
                {
                    "index": code,
                    "window": wname,
                    "cash_leg": leg,
                    "cost_bps": cost,
                    "signal": "BH",
                    "mapping": "BH",
                    "start": str(used[0].date()),
                    "end": str(used[-1].date()),
                }
                | perf
            )
p4_perf = pd.DataFrame(perf_rows)
perf_cols = [
    "index",
    "window",
    "cash_leg",
    "cost_bps",
    "signal",
    "mapping",
    "start",
    "end",
    "ann_return",
    "ann_vol",
    "sharpe_excess",
    "max_dd",
    "avg_w",
    "turnover_per_year",
]
p4_perf = p4_perf[perf_cols]
log(f"p4_perf {len(p4_perf)} 行")
show(
    "p4_perf 主口径（ibo、5bp）own window 全部行",
    p4_perf[
        (p4_perf["window"] == "own")
        & (p4_perf["cash_leg"] == CASH_MAIN)
        & (p4_perf["cost_bps"] == COST_MAIN)
    ],
)

# %% [markdown]
# ## SPA 工具


# %%
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
# ## Q1：V 用哪种映射？
#
# 主指标是主口径（ibo、5 bp、own window）下 V 的超额夏普。某个映射在三个指数上都高于 R0，
# 才判为「优于原规则」。R4 在 own window 里从它首次有仓位的那天起算（其余映射同区间另见
# `r4_window` 行）。

# %%
q1_src = p4_perf[
    (p4_perf["window"] == "own")
    & (p4_perf["cash_leg"] == CASH_MAIN)
    & (p4_perf["cost_bps"] == COST_MAIN)
    & (p4_perf["signal"] == "V")
]
q1 = q1_src.pivot(index="mapping", columns="index", values="sharpe_excess").reindex(list(MAPPINGS))
r0_sharpe = q1.loc["R0", list(INDICES)]
q1["beats_r0_all"] = [bool((q1.loc[m, list(INDICES)] > r0_sharpe).all()) for m in MAPPINGS]
p4_q1 = q1.reset_index()[["mapping", *INDICES, "beats_r0_all"]]
show("p4_q1 主口径 V 的五种映射超额夏普（own window）", p4_q1)
log(
    f"p4_q1 中优于 R0 的映射（三个指数都高）：{p4_q1.loc[p4_q1['beats_r0_all'], 'mapping'].tolist()}"
)

# %% [markdown]
# ## Q2：前两阶段的结论在价值、成长指数上是否成立？
#
# - a：R0 下 Σ(M−V)（10Y、成本 0，与报告一同口径；另列主口径）为正，且 2022-04-12 以后占比 ≥ 80%。
# - b：R1 下 Σ(M−V) 不到 R0 的 50%；R0 的 Σ ≤ 0 时 a 已不成立，b 记 NaN。
# - c：每种映射（R0–R3）下 V 为基准、EY/M/U 为候选的 SPA `p_consistent` ≥ 0.10。
# - 三条都成立判为「同样的结论成立」。

# %%
q2_rows: list[dict[str, object]] = []
for code in INDICES:
    own = OWN_START[code]
    # a：报告一同口径（10Y、0bp）
    mv_r0_10 = (
        net_of("cash_10y", code, "M", "R0", 0) - net_of("cash_10y", code, "V", "R0", 0)
    ).loc[own:]
    sum_r0_10 = float(mv_r0_10.sum())
    post = float(mv_r0_10.loc[TAU:].sum())
    share = post / sum_r0_10 if sum_r0_10 != 0 else np.nan
    a_holds = bool(sum_r0_10 > 0 and not np.isnan(share) and share >= 0.80)
    # 主口径（ibo、5bp）
    mv_r0_main = (
        net_of(CASH_MAIN, code, "M", "R0", COST_MAIN)
        - net_of(CASH_MAIN, code, "V", "R0", COST_MAIN)
    ).loc[own:]
    sum_r0_main = float(mv_r0_main.sum())
    # b：与 a 同一现金腿与成本
    mv_r1_10 = (
        net_of("cash_10y", code, "M", "R1", 0) - net_of("cash_10y", code, "V", "R1", 0)
    ).loc[own:]
    sum_r1_10 = float(mv_r1_10.sum())
    if sum_r0_10 > 0:
        ratio = sum_r1_10 / sum_r0_10
        b_holds: object = bool(ratio < 0.5)
    else:
        ratio = np.nan
        b_holds = np.nan
    # c：每种映射下 V 为基准、EY/M/U 为候选
    p_by_mapping = {}
    for mp in MAPPINGS:
        if mp == "R4":
            continue  # c 只覆盖 R0–R3
        bench = net_of(CASH_MAIN, code, "V", mp, COST_MAIN).loc[own:]
        cands = {
            f"{sig}+{mp}": net_of(CASH_MAIN, code, sig, mp, COST_MAIN).loc[own:]
            for sig in ("EY", "M", "U")
        }
        p_by_mapping[mp] = float(run_spa(bench, cands)["p_consistent"])
    min_mp = min(p_by_mapping, key=lambda k: p_by_mapping[k])
    c_holds = bool(all(p >= 0.10 for p in p_by_mapping.values()))
    same = bool(a_holds and b_holds is True and c_holds)
    row = {
        "index": code,
        "sum_mv_r0_10y_0bp": sum_r0_10,
        "share_post_tau": share,
        "a_holds": a_holds,
        "sum_mv_r0_main": sum_r0_main,
        "sum_mv_r1_10y_0bp": sum_r1_10,
        "ratio_r1_over_r0": ratio,
        "b_holds": b_holds,
        "min_p_consistent": p_by_mapping[min_mp],
        "min_p_mapping": min_mp,
        "c_holds": c_holds,
        "same_conclusion": same,
    }
    row |= {f"p_consistent_{mp}": v for mp, v in p_by_mapping.items()}
    q2_rows.append(row)
p4_q2 = pd.DataFrame(q2_rows)
p4_q2 = p4_q2[
    [
        "index",
        "sum_mv_r0_10y_0bp",
        "share_post_tau",
        "a_holds",
        "sum_mv_r0_main",
        "sum_mv_r1_10y_0bp",
        "ratio_r1_over_r0",
        "b_holds",
        "p_consistent_R0",
        "p_consistent_R1",
        "p_consistent_R2",
        "p_consistent_R3",
        "min_p_consistent",
        "min_p_mapping",
        "c_holds",
        "same_conclusion",
    ]
]
show("p4_q2 逐条判定（a/b/c）", p4_q2)

# %% [markdown]
# ## p4_spa：每个指数两组 SPA
#
# 候选是所有「信号 × 映射」组合（含 R4），主口径净收益，取公共非 NaN 日期。

# %%
spa_rows: list[dict[str, object]] = []
for code in INDICES:
    own = OWN_START[code]
    combos = [(sig, mp) for sig in SIGNALS for mp in MAPPINGS if (sig, mp) in RUNS[CASH_MAIN][code]]
    all_cands = {
        f"{sig}+{mp}": net_of(CASH_MAIN, code, sig, mp, COST_MAIN).loc[own:] for sig, mp in combos
    }
    bh = PANELS[code]["ret"].loc[own:].copy()
    bh.iloc[0] = np.nan
    groups = {
        "V+R0": (all_cands["V+R0"], {k: v for k, v in all_cands.items() if k != "V+R0"}),
        "BH": (bh, all_cands),
    }
    for bench_name, (bench, cands) in groups.items():
        res = run_spa(bench, cands)
        spa_rows.append({"index": code, "benchmark": bench_name} | res)
        log(
            f"SPA {code} 基准 {bench_name}: n={res['n_days']} "
            f"{res['start']}..{res['end']} p_consistent={res['p_consistent']:.4f}"
        )
p4_spa = pd.DataFrame(spa_rows)
p4_spa = p4_spa[
    [
        "index",
        "benchmark",
        "n_days",
        "start",
        "end",
        "n_models",
        "p_lower",
        "p_consistent",
        "p_upper",
        "best_model",
        "best_mean_diff_bp",
    ]
]
show("p4_spa", p4_spa)

# %% [markdown]
# ## p4_q2d：V 在中证红利、创业板上的月频推断
#
# 复用报告二的做法：NW t、IVX 单边 p、零假设平稳块自助单边 p、样本外 R²_OS 与 CW p，
# 四个模型 × 四个期限做 Holm。预测变量用信号的水平值（EY / V / U / M），同报告二 P1.1。
# 评级按计划的 P1.5 规则，「训练起点网格」这一条按不满足计，
# 所以最高第 2 类。000985 不重算，直接记为「见报告二」。


# %%
def nw_hac(y: np.ndarray, x: np.ndarray, h: int) -> tuple[np.ndarray, np.ndarray]:
    """``y ~ 1 + x`` 的 Newey-West 系数与 t 值（Bartlett，滞后 max(h,1)），同报告二。

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


q2d_rows: list[dict[str, object]] = []
q2d_grade_rows: list[dict[str, object]] = []
idx_seqs = np.random.SeedSequence(SEED).spawn(len(Q2D_INDICES))
for pos, code in enumerate(Q2D_INDICES):
    p = PANELS[code]
    mp = p["monthly"]
    y1 = mp["fwd1"].to_numpy(dtype=float)
    x_all = {k: mp[f"level|{k}"].to_numpy(dtype=float) for k in Q2D_MODELS}
    a, b = longest_valid_run([y1, *x_all.values()], 0)
    y1c = y1[a : b + 1]
    log(f"{code} 月频样本 {mp['period'].iloc[a]}..{mp['period'].iloc[b]}（{b - a + 1} 个月）")
    model_seqs = idx_seqs[pos].spawn(len(Q2D_MODELS))
    rows_m: dict[tuple[str, int], dict[str, object]] = {}
    for j, model in enumerate(Q2D_MODELS):
        xc = x_all[model][a : b + 1]
        rng = np.random.default_rng(model_seqs[j])
        real: dict[int, dict[str, float]] = {}
        for h in HORIZONS:
            yh = forward_sum(y1c, h)
            ok = ~np.isnan(yh)
            fit = nw_ols(pd.Series(yh[ok], name="y"), pd.DataFrame({"x": xc[ok]}), h)[0]
            ivx = ivx_wald(y1c, xc, h)
            o_start = first_oos_month(yh, h, 0, MIN_HISTORY)
            fc = oos_expanding(
                yh, xc, h, train_start=0, oos_start=o_start, min_history=MIN_HISTORY
            ).dropna()
            cw_t, cw_p = clark_west_np(fc["y"], fc["M0"], fc["model"], h)
            real[h] = {
                "t": float(fit.tvalues["x"]),
                "coef": float(fit.params["x"]),
                "n": int(ok.sum()),
                "ivx_p_pos": float(ivx["p_one_sided_pos"]),
                "r2_os": r2_os(fc["y"], fc["model"], fc["M0"]),
                "cw_t": cw_t,
                "cw_p": cw_p,
                "oos_start": str(mp["period"].iloc[a + o_start]),
            }
        boot_t = {h: np.empty(N_BOOT) for h in HORIZONS}
        for bi in range(N_BOOT):
            idx = stationary_indices(len(y1c) - 1, BOOT_BLOCK, rng)
            y_star, x_star = null_bootstrap_draw(y1c, xc, [], idx)
            for h in HORIZONS:
                yh_star = forward_sum(y_star, h)
                ok_s = ~np.isnan(yh_star)
                _, t_star = nw_hac(yh_star[ok_s], x_star[ok_s], h)
                boot_t[h][bi] = t_star[1]
        for h in HORIZONS:
            rows_m[(model, h)] = {
                "index": code,
                "model": model,
                "h": h,
                "n": real[h]["n"],
                "coef": real[h]["coef"],
                "t_nw": real[h]["t"],
                "ivx_p_one_sided": real[h]["ivx_p_pos"],
                "p_boot_one_sided": float(np.mean(boot_t[h] >= real[h]["t"])),
                "r2_os": real[h]["r2_os"],
                "cw_t": real[h]["cw_t"],
                "cw_p": real[h]["cw_p"],
                "oos_start": real[h]["oos_start"],
            }
        log(f"  {model}: 预测起点 {real[1]['oos_start']}，自助 {N_BOOT} 次完成")
    keys = [(m, h) for m in Q2D_MODELS for h in HORIZONS]
    p_holm = multipletests([float(rows_m[k]["cw_p"]) for k in keys], method="holm")[1]
    for k, ph in zip(keys, p_holm, strict=True):
        rows_m[k]["p_holm"] = float(ph)
    for model in Q2D_MODELS:
        c1_h = [h for h in HORIZONS if float(rows_m[(model, h)]["p_holm"]) < 0.05]
        c1 = len(c1_h) >= 2
        c3_h = [
            h
            for h in HORIZONS
            if float(rows_m[(model, h)]["ivx_p_one_sided"]) < 0.05
            or float(rows_m[(model, h)]["p_boot_one_sided"]) < 0.05
        ]
        c3_on_c1 = all(h in c3_h for h in c1_h)
        # 条件 2（训练起点网格）按计划记为不满足，所以第 3 类不可达
        grade = "2" if (c1 or len(c3_h) >= 2) else "5"
        q2d_grade_rows.append(
            {
                "index": code,
                "model": model,
                "c1_horizons": ",".join(map(str, c1_h)),
                "c1": c1,
                "c2": False,
                "c3_horizons": ",".join(map(str, c3_h)),
                "c3_on_c1": c3_on_c1,
                "grade": grade,
                "note": "条件 2（训练起点网格）按计划记为不满足，最高第 2 类",
            }
        )
    q2d_rows.extend(rows_m[k] for k in keys)
p4_q2d = pd.DataFrame(q2d_rows)
p4_q2d = p4_q2d[
    [
        "index",
        "model",
        "h",
        "n",
        "coef",
        "t_nw",
        "ivx_p_one_sided",
        "p_boot_one_sided",
        "r2_os",
        "cw_t",
        "cw_p",
        "p_holm",
        "oos_start",
    ]
]
p4_q2d_grade = pd.DataFrame(q2d_grade_rows)
# 000985 不重算，直接标注
p4_q2d_000985 = pd.DataFrame(
    [{"index": MAIN, "model": m, "note": "见报告二（erp_rate_anchor P1）"} for m in Q2D_MODELS]
)
show("p4_q2d 月频推断（000922 / 399006）", p4_q2d)
show("p4_q2d 评级", p4_q2d_grade)
show("p4_q2d 000985（不重算）", p4_q2d_000985)

# %% [markdown]
# ## p4_timing：R1 与 R0 的 CAPM α
#
# 做法同报告一 P0.3：月度超额收益对指数月度超额收益回归，Newey-West 滞后 3 个月。

# %%
timing_rows: list[dict[str, object]] = []
for code in INDICES:
    p = PANELS[code]
    own = OWN_START[code]
    cash_leg = CASH_BY_LEG[CASH_MAIN]
    r_cash = cash_leg.loc[own:].dropna()
    m_cash = (1 + r_cash).groupby(r_cash.index.to_period("M")).prod() - 1
    bh = p["ret"].loc[own:].copy()
    bh.iloc[0] = np.nan
    b = bh.dropna()
    m_bh = (1 + b).groupby(b.index.to_period("M")).prod() - 1
    for sig in SIGNALS:
        for mp in ("R0", "R1"):
            net = net_of(CASH_MAIN, code, sig, mp, COST_MAIN).dropna()
            m_s = (1 + net).groupby(net.index.to_period("M")).prod() - 1
            frame = pd.concat({"s": m_s, "m": m_bh, "c": m_cash}, axis=1).dropna()
            ex_s = frame["s"] - frame["c"]
            ex_m = frame["m"] - frame["c"]
            fit = nw_ols(ex_s, pd.DataFrame({"ex_m": ex_m}), NW_LAGS)[0]
            timing_rows.append(
                {
                    "index": code,
                    "signal": sig,
                    "mapping": mp,
                    "n": len(frame),
                    "beta": float(fit.params["ex_m"]),
                    "alpha_ann": float(fit.params["const"]) * 12,
                    "t_alpha": float(fit.tvalues["const"]),
                }
            )
p4_timing = pd.DataFrame(timing_rows)
show("p4_timing R0/R1 的 CAPM α（年化）与 t", p4_timing)

# %% [markdown]
# ## p4_q3：价值与成长的差别（只作描述）
#
# 共同区间内三个指数 EY、V 的日度水平与 5 年分位的相关矩阵（12 个序列，长表）；
# 2022-04-12 以后各指数 R0 下 M 与 V 的平均仓位与平均差。

# %%
corr_series: dict[str, pd.Series] = {}
for code in INDICES:
    p = PANELS[code]
    lo = OWN_START_COMMON
    corr_series[f"{code}|EY|level"] = p["ey"].loc[lo:AS_OF]
    corr_series[f"{code}|V|level"] = p["V"].loc[lo:AS_OF]
    corr_series[f"{code}|EY|pct"] = p["pct"]["EY"].loc[lo:AS_OF]
    corr_series[f"{code}|V|pct"] = p["pct"]["V"].loc[lo:AS_OF]
corr_frame = pd.DataFrame(corr_series)
corr_matrix = corr_frame.corr()
corr_rows = []
for ca in corr_frame.columns:
    for cb in corr_frame.columns:
        pair = corr_frame[[ca, cb]].dropna()
        corr_rows.append(
            {
                "series_a": ca,
                "series_b": cb,
                "corr": float(corr_matrix.loc[ca, cb]),
                "n_days": len(pair),
            }
        )
p4_q3_corr = pd.DataFrame(corr_rows)
log(
    f"p4_q3 相关矩阵：共同区间 {OWN_START_COMMON.date()}..{AS_OF.isoformat()}，"
    f"{len(corr_frame)} 个交易日"
)

q3_rows = []
for code in INDICES:
    w_m = RUNS[CASH_MAIN][code][("M", "R0")]["w"].loc[TAU:]
    w_v = RUNS[CASH_MAIN][code][("V", "R0")]["w"].loc[TAU:]
    diff = w_m - w_v
    q3_rows.append(
        {
            "index": code,
            "from": str(TAU.date()),
            "days": int(diff.notna().sum()),
            "avg_w_M": float(w_m.mean()),
            "avg_w_V": float(w_v.mean()),
            "avg_diff_M_minus_V": float(diff.mean()),
        }
    )
p4_q3_position = pd.DataFrame(q3_rows)
show("p4_q3 2022-04-12 以后 R0 下 M 与 V 的平均仓位", p4_q3_position)

# %% [markdown]
# ## 落盘：结果表、pit_report、run log

# %%
bundle = load_bundle()
datasets = (
    "src.wind.aindexvaluation",
    "src.wind.aindexeodprices",
    "src.wind.cbondcurvecnbd",
    "src.tushare.us_treasury_yield",
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
        "cn_ibo_7d 日频单版本、发布当天可见，as_of=AS_OF 整段读一次与逐日读等价。",
        "Wind 源镜像跟随源端修订，估值、中债与指数收益都是当前版本，不是当时版本。",
        "所有样本都是已观察样本，结论最高第 2 类。",
        "R3 的 sigma60 与扩张中位数用该指数全部可得日收益历史，只含当日及以前的数据。",
    ],
}

panel_records = {}
for code, p in PANELS.items():
    frame = pd.DataFrame(
        {
            "trade_dt": open_idx,
            "ey": p["ey"],
            "V": p["V"],
            "U": p["U"],
            "M": p["M"],
            "ret": p["ret"],
        }
    )
    for k in SIGNALS:
        frame[f"pct_{k}"] = p["pct"][k]
    panel_records[code] = json.loads(frame.to_json(orient="records", date_format="iso"))
input_digest = digest_json(
    {
        "params": PARAMS,
        "panels": panel_records,
        "r4_info": r4_info,
        "windows": {c: {k: str(v.date()) for k, v in w.items()} for c, w in WINDOWS.items()},
    }
)

results = {
    "p4_repro": repro,
    "p4_perf": p4_perf,
    "p4_q1": p4_q1,
    "p4_q2": p4_q2,
    "p4_spa": p4_spa,
    "p4_q2d": p4_q2d,
    "p4_q2d_grade": p4_q2d_grade,
    "p4_q2d_000985": p4_q2d_000985,
    "p4_timing": p4_timing,
    "p4_q3_corr": p4_q3_corr,
    "p4_q3_position": p4_q3_position,
}
output_digest = digest_json(
    {k: json.loads(v.to_json(orient="records")) for k, v in results.items()}
)

run_id = new_run_id()
out_dir = paths.root / "research" / "erp_position_mapping" / run_id
out_dir.mkdir(parents=True, exist_ok=False)
for name, frame in results.items():
    frame.to_csv(out_dir / f"{name}.csv", index=False)
summary = {
    "params": PARAMS,
    "windows": {c: {k: str(v.date()) for k, v in w.items()} for c, w in WINDOWS.items()},
    "r4_info": r4_info,
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
        action="research.erp_position_mapping",
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
