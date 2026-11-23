# %% [markdown]
# # 冻结 ERP 候选口径：`frozen/erp_rate_anchor/candidates_2026-11-24/`
#
# 规格见 `docs/research/erp-p4-plan.md` 第一节。这是仓库里第一个冻结 bundle，
# 目的是让以后的前瞻记录能先逐日复现这份口径，再追加新数据。
#
# 只读：数据库仅 SELECT；产出写入 `frozen/`。写入前若目标目录已有任何文件即
# raise，冻结制品不覆盖（`frozen/README.md` 硬约束 1）。
#
# 复现门槛（任一不满足即停）：
#
# 1. M、V、U 的 R0 的 signal/pct/target/w/ret 与 run `ae2a020e…` 的
#    `p01_daily.csv` 逐位相等；
# 2. M、V、U 的 F3 年化收益与同一 run 的 `p02_experiments.csv` 一致到 1e-12；
# 3. EY 的 R0 的 w/ret 与 run `05cf3475…` 的 `strategy_EY_5y_lag1.csv` 逐位相等。

# %%
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
from erp_lib import asof_lookup, cash_accrual, perf_daily, ratchet, rolling_percentile

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.index_returns import PostgresIndexReturnRepository
from quantagent.adapters.postgres.index_valuation import PostgresIndexValuationRepository
from quantagent.adapters.postgres.macro import PostgresMacroRepository
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
#
# 全部写进 `config.json`，读取方不得回退到代码默认值。

# %%
AS_OF = date(2026, 11, 20)  # 研究截止日，固定以便复现
START = date(2002, 1, 1)  # 读取起点，只影响分位窗口的历史预热
MAIN = "000985.CSI"  # 估值：中证全指
TR = "h00985.CSI"  # 收益：中证全指全收益
US_STALE_DAYS = 7
IBO_STALE_DAYS = 7
PCT_YEARS = 5
PCT_WINDOW_DAYS = 365 * PCT_YEARS + PCT_YEARS // 4
BAND = 0.10
# 正好差 0.10 也调仓；留容差避免 0.7 - 0.6 < 0.1 的浮点误差。默认值即 erp_lib.ratchet 的默认。
BAND_TOL = 1e-9
LAG = 1
COST_BPS = (0, 5)
EXPECTED_START = "2010-10-13"  # 四个信号都出分位的第一天
LINE = "erp_rate_anchor"
BUNDLE = "candidates_2026-11-24"
CREATED = "2026-11-24"
# 复现基准：产出本 bundle 时依赖的两次运行
OLD_RUN_MAX = "ae2a020e869945bc87294275e9e14580"  # erp_max_attribution
OLD_RUN_ERP = "05cf3475b6354fa8be2c4d3f7bab942f"  # erp_rate_anchor
MAX_BUNDLE_BYTES = 4 * 1024 * 1024  # frozen/ 单文件上限

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
# 与 `2026-11-24-erp-max-attribution.py` 完全相同：估值、中债、全收益指数是
# `same_day_close`，美债严格早于信号日（7 天过期），`cn_ibo_7d` 日频单版本、
# 整段读一次再 asof 对齐（与逐日读等价，理由见配置里的可见时点说明）。

# %%
open_days = [
    d.cal_dt
    for d in calendar.list_days(as_of=AS_OF, exchange="SSE", start=START, end=AS_OF)
    if d.is_open
]
open_idx = pd.DatetimeIndex(open_days)
log(f"交易日 {len(open_days)}")

val_rows = valuations.list_valuations(as_of=AS_OF, start=START, end=AS_OF, wind_codes=(MAIN,))
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
        {
            pd.Timestamp(r.observation_date): (np.nan if r.value is None else float(r.value))
            for r in rows
        }
    )
    return s.sort_index()


r_cn_raw = point_series("cn_cgb_10y")
r_us_raw = point_series("us_ust_10y").dropna()
log(f"中债 {len(r_cn_raw)} 美债 {len(r_us_raw)}")

ret_rows = index_returns.list_returns(as_of=AS_OF, start=START, end=AS_OF, wind_codes=(TR,))
pct_change = pd.Series(
    {
        pd.Timestamp(r.trade_dt): (np.nan if r.pct_change is None else float(r.pct_change))
        for r in ret_rows
        if r.wind_code == TR
    }
).sort_index()
log(f"全收益行 {len(ret_rows)}")

ibo_rows = macro.list_observations(as_of=AS_OF, start=START, end=AS_OF, series_ids=("cn_ibo_7d",))
ibo = pd.Series(
    {
        pd.Timestamp(r.observation_date): (np.nan if r.value is None else float(r.value))
        for r in ibo_rows
    }
).sort_index()
log(f"ibo7d {len(ibo)} 行 {ibo.index[0].date()}..{ibo.index[-1].date()}")

# %% [markdown]
# ## 日频面板
#
# EY、r_CN 同日对齐；r_US 取观测日严格早于信号日的最近一期，过期超过 7 天即缺失
# （同时记下实际取到的观测日，供 web 前瞻展示核对）。`cn_ibo_7d` 是日频单版本，
# as_of 整段读一次再 asof 对齐，7 天过期。

# %%
p_main = pe.reindex(open_idx)
ey = pd.Series(np.where(p_main > 0, 100.0 / p_main, np.nan), index=open_idx)
r_cn = r_cn_raw.reindex(open_idx)

us_cut = open_idx - pd.Timedelta(days=1)
us_vals, us_obs = asof_lookup(r_us_raw, us_cut)
us_obs_idx = pd.DatetimeIndex(us_obs)
us_stale = (us_cut - us_obs_idx) > pd.Timedelta(days=US_STALE_DAYS)
r_us = pd.Series(np.where(us_stale | pd.isna(us_obs_idx), np.nan, us_vals), index=open_idx)
r_us_ok = r_us.notna().to_numpy()
assert (us_obs_idx[r_us_ok] < open_idx[r_us_ok]).all(), "美债观测日必须严格早于信号日"
r_us_obs = pd.Series(us_obs_idx, index=open_idx)

ibo_vals, ibo_obs = asof_lookup(ibo.dropna(), open_idx)
ibo_obs_idx = pd.DatetimeIndex(ibo_obs)
ibo_stale = (open_idx - ibo_obs_idx) > pd.Timedelta(days=IBO_STALE_DAYS)
ibo_7d = pd.Series(np.where(ibo_stale | pd.isna(ibo_obs_idx), np.nan, ibo_vals), index=open_idx)
assert (ibo_obs_idx[ibo_7d.notna().to_numpy()] <= open_idx[ibo_7d.notna().to_numpy()]).all()

V = ey - r_cn
U = ey - r_us
M = ey - np.maximum(r_us, r_cn)
ret_d = pct_change.reindex(open_idx) / 100.0
cash = cash_accrual(r_cn)
log(
    f"有效天数: EY {ey.notna().sum()} r_cn {r_cn.notna().sum()} r_us {r_us.notna().sum()} "
    f"ibo7d {ibo_7d.notna().sum()} ret {ret_d.notna().sum()}"
)

# %% [markdown]
# ## 复现基准的读取
#
# 起点不自己算：从上游结果文件的第一行日期读取，与 `2026-11-24-erp-max-attribution.py`
# 的做法一致。原因见下节。

# %%
old_max_dir = paths.root / "research" / "erp_max_attribution" / OLD_RUN_MAX
if not old_max_dir.is_dir():
    raise RuntimeError(f"旧 run 目录不存在：{old_max_dir}")
p01_ref = pd.read_csv(old_max_dir / "p01_daily.csv", float_precision="round_trip")
p01_ref["trade_dt"] = pd.DatetimeIndex(p01_ref["trade_dt"])
p02_ref = pd.read_csv(old_max_dir / "p02_experiments.csv", float_precision="round_trip").set_index(
    "experiment"
)
REF_TAGS = (("a", "M"), ("b", "V"), ("c", "U"))

# %% [markdown]
# ## 分位与起点
#
# 5 年滚动、`<= 当日值` 的比例，不满窗口不出信号。
#
# 起点有一处必须写清的差异：只看本 bundle 的四个信号（EY、V、U、M），首个分位日都是
# 2009-12-31；上游运行把 TIPS 实际利率 `Ur_tips` 也算进共同起点，而它的 5 年分位要到
# 2010-10-13 才出值，所以那次运行的共同起点是 2010-10-13，已发布的逐日结果都从这里切。
# `ratchet` 的单向约束依赖此前仓位历史，切片更早会改变仓位路径，因此冻结窗口必须与已
# 发布结果一致：起点取上游文件首行，并断言它等于 2010-10-13。

# %%
SPREADS = {"EY": ey, "V": V, "U": U, "M": M}
PCTS = {name: rolling_percentile(spread, PCT_YEARS) for name, spread in SPREADS.items()}
first_pct = {name: pct.first_valid_index() for name, pct in PCTS.items()}
START_SIGNAL = pd.Timestamp(p01_ref["trade_dt"].iloc[0])
log(f"各信号首个分位日: { {k: str(v.date()) for k, v in first_pct.items()} }")
if str(START_SIGNAL.date()) != EXPECTED_START:
    raise AssertionError(f"起点应为 {EXPECTED_START}，实际 {START_SIGNAL.date()}")
if max(first_pct.values()) > START_SIGNAL:
    raise AssertionError(f"起点 {START_SIGNAL.date()} 早于四个信号的首个分位日")
if pd.isna(PCTS["M"].loc[START_SIGNAL]):
    raise AssertionError("起点当天 M 的分位缺失")
_missing_pct = [n for n in SPREADS if pd.isna(PCTS[n].loc[START_SIGNAL])]
if _missing_pct:
    raise AssertionError(f"起点当天缺分位的信号：{_missing_pct}")
IDX = open_idx[open_idx >= START_SIGNAL]
if not IDX.equals(pd.DatetimeIndex(PCTS["M"].loc[START_SIGNAL:].index)):
    raise AssertionError("起点之后的分位索引与交易日索引不一致")
RET_W, CASH_W = ret_d.loc[START_SIGNAL:], cash.loc[START_SIGNAL:]
log(f"起点 {START_SIGNAL.date()}..{IDX[-1].date()}，{len(IDX)} 个交易日")

# %% [markdown]
# ## 两种映射
#
# `R0` 原规则（单向约束 + 0.10 阈值），`F3` 连续映射（目标即可成交仓位）。
# 两者都是 lag=1、现金 10 年期国债。

# %%
RUNS_R0 = {
    name: ratchet(PCTS[name].loc[START_SIGNAL:], RET_W, lag=LAG, cash=CASH_W, return_target=True)
    for name in SPREADS
}
RUNS_F3 = {
    name: ratchet(
        PCTS[name].loc[START_SIGNAL:], RET_W, lag=LAG, cash=CASH_W, one_way=False, band=0.0
    )
    for name in SPREADS
}

# %% [markdown]
# ## 复现断言一：M、V、U 的 R0 与 `p01_daily.csv` 逐位相等
#
# 比较 a_/b_/c_ 的 signal、pct、target、w、ret 五列；索引、NaN 位置、数值都要一致。

# %%


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


repro_rows = []
for tag, name in REF_TAGS:
    ref_signals = {
        "signal": SPREADS[name].reindex(IDX),
        "pct": PCTS[name].reindex(IDX),
        "target": RUNS_R0[name]["target"],
        "w": RUNS_R0[name]["w"],
        "ret": RUNS_R0[name]["ret"],
    }
    for col, series in ref_signals.items():
        ref = pd.Series(
            p01_ref[f"{tag}_{col}"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(p01_ref["trade_dt"]),
        )
        n = assert_identical(series, ref, f"{name}.R0.{col} vs p01_daily:{tag}_{col}")
        repro_rows.append(
            {
                "signal": name,
                "mapping": "R0",
                "column": col,
                "rows": n,
                "source": f"p01_daily:{tag}",
            }
        )
log("R0 复现通过：M/V/U 的 signal、pct、target、w、ret 与 p01_daily 逐位相等（atol=rtol=0）")

# %% [markdown]
# ## 复现断言二：M、V、U 的 F3 年化收益与 `p02_experiments.csv` 一致到 1e-12

# %%
for tag, name in REF_TAGS:
    label = f"F3_no_one_way_no_band_{tag.upper()}"
    if label not in p02_ref.index:
        raise AssertionError(f"p02_experiments.csv 缺 {label}")
    ann = perf_daily(RUNS_F3[name]["ret"])["ann_return"]
    old_ann = float(p02_ref.loc[label, "ann_return"])
    if abs(ann - old_ann) > 1e-12:
        raise AssertionError(f"{name}.F3 年化收益不一致：{ann!r} vs {old_ann!r}")
    repro_rows.append(
        {
            "signal": name,
            "mapping": "F3",
            "column": "ann_return",
            "rows": len(RUNS_F3[name]),
            "source": f"p02_experiments:{label}",
        }
    )
log("F3 复现通过：M/V/U 的年化收益与 p02_experiments 一致到 1e-12")

# %% [markdown]
# ## 复现断言三：EY 的 R0 与上游 `strategy_EY_5y_lag1.csv` 逐位相等
#
# EY 在 max 归因那次运行里没有单独落表，基准取第二阶段（`05cf3475…`）的同口径结果。

# %%
old_erp_dir = paths.root / "research" / "erp_rate_anchor" / OLD_RUN_ERP
ey_ref_path = old_erp_dir / "strategy_EY_5y_lag1.csv"
if not ey_ref_path.is_file():
    raise RuntimeError(f"EY 基准不存在：{ey_ref_path}")
ey_ref = pd.read_csv(ey_ref_path, index_col=0, parse_dates=True, float_precision="round_trip")
for col in ("w", "ret"):
    n = assert_identical(RUNS_R0["EY"][col], ey_ref[col], f"EY.R0.{col} vs strategy_EY_5y_lag1")
    repro_rows.append(
        {"signal": "EY", "mapping": "R0", "column": col, "rows": n, "source": "strategy_EY_5y_lag1"}
    )
log("EY 复现通过：R0 的 w、ret 与上游 strategy_EY_5y_lag1.csv 逐位相等")
print(pd.DataFrame(repro_rows).to_string(index=False))

# %% [markdown]
# ## `data/signals_daily.csv`
#
# 每个交易日一行：原始输入、四个信号、四个分位、两种映射的目标与实际仓位。

# %%
signals = pd.DataFrame(index=IDX)
signals["r_cn"] = r_cn.reindex(IDX)
signals["r_us"] = r_us.reindex(IDX)
# 实际取到的美债观测日；值因 7 天过期而缺失时仍保留 obs，便于 web 核对
signals["r_us_obs_dt"] = r_us_obs.reindex(IDX)
signals["ibo_7d"] = ibo_7d.reindex(IDX)
signals["ey"] = ey.reindex(IDX)
signals["V"] = V.reindex(IDX)
signals["U"] = U.reindex(IDX)
signals["M"] = M.reindex(IDX)
for name in SPREADS:
    signals[f"pct_{name}"] = PCTS[name].reindex(IDX)
    signals[f"r0_target_{name}"] = RUNS_R0[name]["target"].reindex(IDX)
    signals[f"r0_w_{name}"] = RUNS_R0[name]["w"].reindex(IDX)
    signals[f"f3_w_{name}"] = RUNS_F3[name]["w"].reindex(IDX)
signals = signals.reset_index(names="trade_dt")
signals["trade_dt"] = pd.DatetimeIndex(signals["trade_dt"]).strftime("%Y-%m-%d")
signals["r_us_obs_dt"] = pd.DatetimeIndex(signals["r_us_obs_dt"]).strftime("%Y-%m-%d")
log(f"signals_daily {len(signals)} 行 {len(signals.columns)} 列")

# %% [markdown]
# ## 落盘
#
# `config.json` 显式写出全部口径（键排序、结尾换行），`manifest.json` 记身份、
# 来源运行、冻结窗口、配置 digest 与每个文件的 digest。写入后立刻回读校验。

# %%
INPUTS: list[dict[str, Any]] = [
    {
        "key": "trade_calendar",
        "dataset": "std.trade_calendar",
        "series_id": "SSE",
        "wind_code": None,
        "visible": "交易所交易日历；as_of 及之前已确定的交易日可见（is_open=True）",
        "stale_days": None,
    },
    {
        "key": "pe_ttm",
        "dataset": "src.wind.aindexvaluation",
        "series_id": None,
        "wind_code": MAIN,
        "visible": "信号日 T 收盘后当日公开的 PE_TTM（same_day_close）；不得用 OPDATE 或 _ingested_at 当可见日",
        "stale_days": 0,
    },
    {
        "key": "r_cn",
        "dataset": "src.wind.cbondcurvecnbd",
        "series_id": "cn_cgb_10y",
        "wind_code": None,
        "visible": "信号日 T 收盘公布的 10 年期国债到期收益率（曲线 1232、类型 2、期限 10 年，same_day_close）",
        "stale_days": 0,
    },
    {
        "key": "r_us",
        "dataset": "src.tushare.us_treasury_yield",
        "series_id": "us_ust_10y",
        "wind_code": None,
        "visible": "观测日严格早于信号日 T 的最近一期；A 股 T 日收盘时 T 日美债尚未收盘",
        "stale_days": US_STALE_DAYS,
    },
    {
        "key": "ibo_7d",
        "dataset": "src.jydb.c_ed_macroindicatordata",
        "series_id": "cn_ibo_7d",
        "wind_code": None,
        "visible": (
            "银行间同业拆借加权利率 7 天（聚源指标 601230002）；日频单版本、发布当天可见，"
            "as_of=AS_OF 整段读一次再 asof 对齐与逐日读等价"
        ),
        "stale_days": IBO_STALE_DAYS,
    },
    {
        "key": "index_return",
        "dataset": "src.wind.aindexeodprices",
        "series_id": None,
        "wind_code": TR,
        "visible": "全收益指数当日收盘涨跌幅（same_day_close）；策略 T+1 收盘成交，收益口径与指数一致",
        "stale_days": 0,
    },
]

CONFIG: dict[str, Any] = {
    "as_of": AS_OF.isoformat(),
    "start": START_SIGNAL.strftime("%Y-%m-%d"),
    "index": {"name": "中证全指", "valuation_wind_code": MAIN, "return_wind_code": TR},
    "signals": {
        "definition": {
            "EY": "100 / PE_TTM（PE_TTM <= 0 视为无定义，不参与分位）",
            "V": "EY - r_CN",
            "U": "EY - r_US",
            "M": "EY - max(r_US, r_CN)",
        },
        "start_rule": (
            "2010-10-13 = 上游运行的共同起点。四个信号（EY/V/U/M）的首个 5 年分位日都是"
            "2009-12-31，但上游运行还把 TIPS 实际利率（Ur_tips）计入共同起点，它的首个分位日"
            "是 2010-10-13。冻结窗口必须与已发布结果一致：ratchet 的单向约束依赖此前仓位历史，"
            "切片更早会改变仓位路径。"
        ),
        "missing_rule": "任一输入缺失即该信号缺失，不填充、不补前值、不跨日池化",
        "unit": "利率与利差单位为百分点",
    },
    "inputs": INPUTS,
    "percentile": {
        "years": PCT_YEARS,
        "window_days": PCT_WINDOW_DAYS,
        "window_kind": "自然日滚动窗口，取信号日及之前窗口内的全部有效日值",
        "comparison": "<= 当日值",
        "statistic": "窗口内 <= 当日值的有效观测占比",
        "min_window": "不满窗口不出信号（NaN），不做短窗口替代",
    },
    "mappings": {
        "R0": {
            "name": "原规则（单向约束 + 阈值）",
            "target": "分位",
            "one_way": True,
            "band": BAND,
            "band_tol": BAND_TOL,
            "one_way_rule": "分位 >= 0.5 只加仓、< 0.5 只减仓（目标越界时取当前仓位）",
            "band_rule": "abs(desired - w) >= band - band_tol 才调仓",
        },
        "F3": {
            "name": "连续映射（报告一的 F3）",
            "target": "分位",
            "one_way": False,
            "band": 0.0,
            "band_tol": BAND_TOL,
            "band_rule": "band=0 且无单向约束，目标即可成交仓位，每日对齐",
        },
        "cash_leg_in_data": "cash_10y",
    },
    "execution": {
        "lag": LAG,
        "rule": "T 日收盘出信号，T+1 收盘成交；当日收益按前一日收盘仓位计算，随后仓位随收益漂移",
        "first_day": "起点当天无持仓、无收益（w 与 ret 为 NaN），首个目标在下一交易日成交",
    },
    "cash_legs": {
        "cash_10y": (
            "主口径：r = 上一交易日 cn_cgb_10y（百分点）；当日现金收益 = r / 100 × "
            "相邻交易日自然日数 / 365（act/365，不含久期损益）"
        ),
        "cash_ibo7d": (
            "同业拆借 7 天：r = 上一交易日 cn_ibo_7d（asof 对齐、7 天过期）；"
            "当日现金收益 = r / 100 × 相邻交易日自然日数 / 365"
        ),
    },
    "cost_bps": list(COST_BPS),
    "cost_rule": "单边成本，按成交日扣：ret_net = ret - bps / 1e4 × turnover",
    "boundary": {
        "research_only": True,
        "no_database_write": True,
        "production_qualified": False,
    },
}

repo_root = detect_repo_root()
bundle_dir = repo_root / "frozen" / LINE / BUNDLE
if bundle_dir.exists() and any(bundle_dir.iterdir()):
    raise RuntimeError(f"bundle 目录已存在且非空，拒绝覆盖：{bundle_dir}")
bundle_dir.mkdir(parents=True, exist_ok=True)
(bundle_dir / "data").mkdir(exist_ok=True)

config_bytes = (json.dumps(CONFIG, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
    "utf-8"
)
csv_bytes = signals.to_csv(index=False, float_format="%.12g", lineterminator="\n").encode("utf-8")
for rel, payload in (("config.json", config_bytes), ("data/signals_daily.csv", csv_bytes)):
    if len(payload) > MAX_BUNDLE_BYTES:
        raise RuntimeError(f"{rel} 超过 frozen/ 单文件上限 {MAX_BUNDLE_BYTES} 字节")
    (bundle_dir / rel).write_bytes(payload)
log(f"写出 {bundle_dir}")

# %% [markdown]
# 回读校验：CSV 按 `round_trip` 精度重新解析，与内存值的相对误差必须 < 1e-11
# （`float_format="%.12g"` 的 12 位有效数字给了一位数余量）。

# %%
csv_back = pd.read_csv(bundle_dir / "data/signals_daily.csv", float_precision="round_trip")
if list(csv_back.columns) != list(signals.columns):
    raise AssertionError("回读列名与内存不一致")
if len(csv_back) != len(signals):
    raise AssertionError(f"回读行数不一致：{len(csv_back)} vs {len(signals)}")
str_cols = ("trade_dt", "r_us_obs_dt")
num_cols = [c for c in signals.columns if c not in str_cols]
mem = signals[num_cols].to_numpy(dtype=float)
back = csv_back[num_cols].to_numpy(dtype=float)
if not np.array_equal(np.isnan(mem), np.isnan(back)):
    raise AssertionError("回读后 NaN 位置发生变化")
if not np.allclose(mem, back, rtol=1e-11, atol=0.0, equal_nan=True):
    rel = np.abs(back - mem) / np.where(mem == 0, 1.0, np.abs(mem))
    raise AssertionError(f"回读相对误差超标：最大 {np.nanmax(rel):.3e}")
for col in str_cols:
    if not (csv_back[col].fillna("") == signals[col].fillna("")).all():
        raise AssertionError(f"回读字符串列不一致：{col}")
rel_max = float(np.nanmax(np.abs(back - mem) / np.where(mem == 0, 1.0, np.abs(mem))))
log(f"回读校验通过：{len(csv_back)} 行，浮点最大相对误差 {rel_max:.3e} < 1e-11")


def sha256_lf(payload: bytes) -> str:
    """按统一 LF 计算 sha256（`.gitattributes` 把 frozen/** 标为 eol=lf）。"""
    return hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()


# %% [markdown]
# `manifest.json`：身份、来源运行、冻结窗口、配置 digest、每个文件的 digest 与行列合同。

# %%
source_runs = []
for line, run_id in (("erp_max_attribution", OLD_RUN_MAX), ("erp_rate_anchor", OLD_RUN_ERP)):
    summary_path = paths.root / "research" / line / run_id / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError(f"来源运行的 summary.json 不存在：{summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    source_runs.append(
        {
            "line": line,
            "run_id": run_id,
            "input_digest": summary["input_digest"],
            "output_digest": summary["output_digest"],
            "path": str(summary_path.relative_to(paths.root.parent)),
        }
    )

files_entry = [
    {
        "path": "config.json",
        "sha256": sha256_lf(config_bytes),
        "bytes": len(config_bytes),
    },
    {
        "path": "data/signals_daily.csv",
        "sha256": sha256_lf(csv_bytes),
        "bytes": len(csv_bytes),
        "rows": len(signals),
        "columns": list(signals.columns),
    },
]
manifest = {
    "bundle_id": f"{LINE}/{BUNDLE}",
    "research_line": LINE,
    "created": CREATED,
    "purpose": "报告三的候选口径，供 web 前瞻记录复现与追加。",
    "source_runs": source_runs,
    "freeze_window": {
        "start": START_SIGNAL.strftime("%Y-%m-%d"),
        "end": IDX[-1].strftime("%Y-%m-%d"),
    },
    "config_sha256": sha256_lf(config_bytes),
    "files": files_entry,
    "boundary": {
        "research_only": True,
        "no_database_write": True,
        "production_qualified": False,
    },
    "superseded_by": None,
}
manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
    "utf-8"
)
(bundle_dir / "manifest.json").write_bytes(manifest_bytes)

# %% [markdown]
# 写完重新计算所有 sha256 与 manifest 比对，并检查目录里没有未登记的文件。

# %%
on_disk = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
if on_disk != manifest:
    raise AssertionError("manifest.json 回读与内存不一致")
if sha256_lf((bundle_dir / "config.json").read_bytes()) != on_disk["config_sha256"]:
    raise AssertionError("config.json 的 digest 与 manifest.config_sha256 不一致")
registered = {entry["path"] for entry in on_disk["files"]}
for entry in on_disk["files"]:
    path = bundle_dir / entry["path"]
    if sha256_lf(path.read_bytes()) != entry["sha256"]:
        raise AssertionError(f"{entry['path']} 的 digest 与 manifest 不一致")
csv_check = pd.read_csv(bundle_dir / "data/signals_daily.csv", float_precision="round_trip")
csv_entry = next(e for e in on_disk["files"] if e["path"] == "data/signals_daily.csv")
if len(csv_check) != csv_entry["rows"]:
    raise AssertionError("CSV 行数与 manifest 不一致")
if list(csv_check.columns) != csv_entry["columns"]:
    raise AssertionError("CSV 列名与 manifest 不一致")
unregistered = sorted(
    p.relative_to(bundle_dir).as_posix()
    for p in bundle_dir.rglob("*")
    if p.is_file() and p.relative_to(bundle_dir).as_posix() not in registered | {"manifest.json"}
)
if unregistered:
    raise AssertionError(f"bundle 目录下有未登记的文件：{unregistered}")
log("manifest 自校验通过：digest、行列、目录清单一致")

print("\n冻结 bundle:")
print(f"  {bundle_dir}")
for entry in on_disk["files"]:
    if "rows" in entry:
        print(
            f"  {entry['path']:<24} {entry['sha256']}  rows={entry['rows']} cols={len(entry['columns'])}"
        )
    else:
        print(f"  {entry['path']:<24} {entry['sha256']}")
print(f"  {'manifest.json':<24} {sha256_lf(manifest_bytes)}")
print(f"  {'config_sha256 记录值':<24} {on_disk['config_sha256']}")

# %% [markdown]
# ## run log
#
# 只读运行，`dml_count=0`；`row_count` 是 `signals_daily.csv` 的行数。

# %%
input_digest = digest_json(
    {"config": CONFIG, "panel": json.loads(signals.to_json(orient="records", date_format="iso"))}
)
output_digest = digest_json({entry["path"]: entry["sha256"] for entry in on_disk["files"]})
run_id = new_run_id()
log_path = persist_run_log(
    RunLog(
        run_id=run_id,
        action="research.erp_freeze_candidates",
        status="success",
        finished_at=datetime.now(UTC),
        elapsed_ms=int((time.monotonic() - started) * 1000),
        input_digest=input_digest,
        output_digest=output_digest,
        row_count=len(signals),
        dml_count=0,
    ),
    paths,
)
conn.close()
log(f"run log {log_path}")
sys.stdout.flush()
