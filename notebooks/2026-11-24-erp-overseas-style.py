# %% [markdown]
# # A 股股债利差第五阶段 D 节：久期渠道还是全球成长风格同步
#
# 方案与判读标准见 `docs/research/erp-phase5-plan.md` 的 D 节（看结果前写定，本脚本不改口径）。
#
# - 闸门：先查聚源 `QT_OSIndexQuote` 五个代码的完整性（回填未完成就非零退出，不产出结果）。
# - D1：300 价差同期分解 `spread ~ ΔTIPS + ΔBE + Δr_CN + g_US`，用 g_US 与其对 ΔTIPS 的
#   残差 g_US⊥ 区分「久期渠道」「经由全球成长风格」「与利率无关的风格同步」。
# - D2（只报告）：加 ΔUSD 的美元渠道回归，300 价差与创业板价差、full 与 2015-08 起。
# - D3（只报告）：`fwd_spread ~ g_US`，口径同 C1。
#
# 读取、信号日、月末取值、TIPS 逐日 as_of、方差与 NW 的写法照
# `2026-11-24-erp-style-predict.py`（逐段复制，不 import 那个脚本），因此与报告五、报告六
# 逐值可比。方向与样本都已在报告五观察过，任何结论最高第 2 类。
#
# 只读：数据库只 SELECT；结果写到 `var/research/erp_overseas_style/<run_id>/`，落 run log。

# %%
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from erp_lib import asof_lookup, nw_ols

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.index_returns import PostgresIndexReturnRepository
from quantagent.adapters.postgres.macro import PostgresMacroRepository
from quantagent.adapters.postgres.overseas_index import PostgresOverseasIndexQuoteRepository
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
#
# 境外指数代码是聚源 `SecuMainAll.InnerCode`（旧仓 `market_data_service` 也不 join
# `SecuMainAll`，代码写死）。起始日是计划表列的第一次可用月份之后，用来判断回填起点够不够。

# %%
AS_OF = date(2026, 11, 20)  # 研究截止日，固定以便复现
START = date(2002, 1, 1)  # A 股侧读取起点，与报告五、报告六一致
OVL_START = date(1999, 1, 1)  # 境外指数读取起点，覆盖计划表里最早的 1999-01

G_TR = "h00918.CSI"  # 沪深 300 成长全收益
V_TR = "h00919.CSI"  # 沪深 300 价值全收益
CY_TR = "399606.SZ"  # 创业板全收益
ALL_TR = "h00985.CSI"  # 中证全指全收益（创业板的市场对照）
TR_CODES = (G_TR, V_TR, CY_TR, ALL_TR)

SPREAD_300 = "hs300_growth_minus_value"
SPREAD_CYB = "cyb_minus_allshare"
# 样本起点由「同月价差第一个非 NaN 月」决定，与报告五的 b23_reg 起点逐字一致
EXPECTED_START = {SPREAD_300: "2011-09", SPREAD_CYB: "2010-06"}

# 境外指数：代码写死（聚源 InnerCode），名称只用于打印
OVL_CODES: dict[str, int] = {
    "RLG": 744056,  # 罗素 1000 成长
    "RUI": 3216,  # 罗素 1000
    "NDX": 3205,  # 纳斯达克 100
    "SPX": 3210,  # 标普 500
    "USDX": 8676,  # NYCE 美元指数
}
# 闸门要求的最早交易日：计划表「起始」列所在月的月末。SPX/NDX/RUI 从 1999-01 起读，
# 所以 1999-01-31 是读取下界而不是源端起点（源端更早）。
OVL_PLANNED_START = {
    "RLG": date(2000, 5, 31),
    "RUI": date(1999, 1, 31),
    "NDX": date(1999, 1, 31),
    "SPX": date(1999, 1, 31),
    "USDX": date(2000, 1, 31),
}
OVL_LAST_REQUIRED = date(2026, 11, 18)  # 回填必须覆盖到这一天（含）
OVL_MAX_GAP_DAYS = 7  # 相邻交易日间隔上限（自然日），长假期也不超过
OVL_GAP_CHECK_FROM = date(2011, 1, 1)  # 只对 D1/D2 样本覆盖的区间查缺口
OVL_STALE_DAYS = 7  # 月末取值距信号日超过 7 个自然日即视为缺失

NW_LAGS = 3  # 主口径（h=1）的 Newey-West 滞后
POST_FX = date(2015, 8, 1)  # 汇改以后的样本（计划 D2：2015-08 起）
US_STALE_DAYS = 7  # 美债/TIPS 超过 7 个自然日未更新视为缺失
MIN_N = 36  # 回归最少观测数，低于即报错（与 C1 的门槛一致）
B2_REF_RUN = "428f1c1e4b334c54af0b8d664464a628"  # 报告五的运行号
REF_TOL = 1e-10  # 与报告五逐值比对的阈值

PARAMS = {
    "as_of": AS_OF.isoformat(),
    "start": START.isoformat(),
    "overseas_start": OVL_START.isoformat(),
    "total_return_codes": {
        "growth_300": G_TR,
        "value_300": V_TR,
        "growth_cyb": CY_TR,
        "allshare": ALL_TR,
    },
    "overseas_index_codes": OVL_CODES,
    "overseas_planned_start": {k: v.isoformat() for k, v in OVL_PLANNED_START.items()},
    "overseas_visibility": "src.jydb.qt_osindexquote：TradingDay 严格早于 as_of，境外交易日 T "
    "的收盘在 T+1 可见（docs/adr/2026-11-23-overseas-daily-next-day.md）",
    "overseas_month_end_rule": "对每个 A 股信号日 T，取严格早于 T 的最后一个境外 trading_day 的"
    "收盘；该校验日距 T 超过 7 个自然日即 NaN。as_of=AS_OF 一次读出"
    "再按 < T 对齐，与逐 T 调端口等价（契约是 TradingDay < as_of 的"
    "单调规则，不会读到 T 当日或之后的收盘）",
    "spread_definition": "100 * [sum log1p(r_left) - sum log1p(r_right)] over the month window, "
    "NaN if any daily return in the window is missing",
    "spread_same_month": "(previous signal day, this signal day] in daily total returns",
    "signal_day": "last open A-share day of the natural month; the last month is truncated at "
    "as_of",
    "sample_start": "first month where the same-month spread is available: "
    f"{EXPECTED_START[SPREAD_300]} (300) / {EXPECTED_START[SPREAD_CYB]} (cyb)",
    "rates_at_signal_day": {
        "r_us": "latest observation strictly before T-1 (7 calendar days stale limit)",
        "tips": "ALFRED vintage read per signal day as_of=T, strictly before T, 7 day stale limit",
        "be": "r_us - tips (identity split, not T10YIE)",
        "r_cn": "same day close",
    },
    "deltas": "level(T) - level(previous signal day)",
    "growth_factors": {
        "g_us": "100 * (dln RLG - dln RUI), month-end value strictly before the signal day",
        "g_ndx": "100 * (dln NDX - dln SPX), same alignment",
        "d_usd": "100 * dln USDX, same alignment",
        "g_us_perp": "residual of g_us on the same-month d_tips + constant, OLS estimated on the "
        "full D1 sample",
        "g_ndx_perp": "residual of g_ndx on the same-month d_tips + constant, full D1 sample",
    },
    "nw_lags": NW_LAGS,
    "post_fx_start": POST_FX.isoformat(),
    "min_n": MIN_N,
    "d1_models": {
        "M1": "spread ~ d_tips + d_be + d_rcn + growth proxy",
        "M2": "spread ~ d_tips + d_be + d_rcn + growth proxy residual (perp d_tips)",
        "B3": "spread ~ d_tips + d_be + d_rcn (control row: same controls as M1 without the "
        "growth proxy; report-five B3 additionally carried d_fx)",
    },
    "d1_judgement": {
        "duration_direct": "M1 t(d_tips) <= -2",
        "via_global_growth": "M1 |t(d_tips)| < 1 and t(growth proxy) >= 2",
        "extra_sync": "M2 t(perp proxy) >= 2",
        "undetermined": "none of the above",
        "applies_to": "g_us only; g_ndx models are reported without judgement",
    },
    "d2_models": "spread ~ d_tips + d_be + d_usd + d_rcn; 300 spread and cyb spread, "
    "full and 2015-08 onward; report only",
    "d3_models": "fwd_spread ~ growth proxy (h=1, NW 3); report only",
    "research_class": "direction and sample already observed in report five; class at most 2",
    "ref_b2_run": f"research/erp_dividend_growth/{B2_REF_RUN}",
}

started = time.monotonic()
settings = get_settings()
paths = resolve_var_paths(settings, repo_root=detect_repo_root())
conn = connect(settings, "src")
conn.read_only = True
macro = PostgresMacroRepository(conn)
index_returns = PostgresIndexReturnRepository(conn)
overseas = PostgresOverseasIndexQuoteRepository(conn)
calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")

# %% [markdown]
# ## 闸门：境外指数回填完整性（先于一切计算）
#
# 回填在另一个进程里进行，这里只读。四条检查任一不满足：打印每个代码的行数、起止与缺口，
# 以非零退出码停止，不产出结果。闸门是 fail-closed 的：缺行不猜、不缩样本。
#
# - (a) 最大交易日 ≥ 2026-11-18；
# - (b) 最小交易日 ≤ 计划表起始；
# - (c) 2011-01-01 起相邻交易日间隔不超过 7 个自然日；
# - (d) close 无 NULL。

# %%
ovl_rows = overseas.list_closes(
    as_of=AS_OF,
    start=OVL_START,
    end=AS_OF,
    index_codes=tuple(OVL_CODES.values()),
)
log(
    f"境外指数读入 {len(ovl_rows)} 行，"
    f"{OVL_CODES}，区间 {OVL_START}..{AS_OF}（as_of={AS_OF}，次日可见）"
)

ovl_days: dict[str, np.ndarray] = {}
ovl_close: dict[str, np.ndarray] = {}
gate_rows: list[dict[str, object]] = []
gap_notes: list[str] = []
for _name, _code in OVL_CODES.items():
    _rows = [row for row in ovl_rows if row.index_code == _code]
    _rows.sort(key=lambda row: row.trading_day)
    day_list = [row.trading_day for row in _rows]
    days = np.array(day_list, dtype="datetime64[D]")
    closes = np.array(
        [np.nan if row.close is None else float(row.close) for row in _rows], dtype=float
    )
    ovl_days[_name] = days
    ovl_close[_name] = closes

    n_rows = len(day_list)
    first_day = day_list[0] if day_list else None
    last_day = day_list[-1] if day_list else None
    null_close = int(np.isnan(closes).sum()) if n_rows else 0
    _from = int(np.searchsorted(days, np.datetime64(OVL_GAP_CHECK_FROM)))
    gaps = np.diff(days[_from:]).astype("int64")
    bad = np.flatnonzero(gaps > OVL_MAX_GAP_DAYS)
    max_gap = int(gaps.max()) if len(gaps) else None
    violations = ", ".join(
        f"{days[_from:][i]!s}→{days[_from:][i + 1]!s}({int(gaps[i])}d)" for i in bad
    )
    if violations:
        gap_notes.append(f"{_name}({_code}) 缺口超过 {OVL_MAX_GAP_DAYS} 天: {violations}")
    pass_last = last_day is not None and last_day >= OVL_LAST_REQUIRED
    pass_first = first_day is not None and first_day <= OVL_PLANNED_START[_name]
    pass_gap = len(gaps) > 0 and not len(bad)
    pass_close = n_rows > 0 and null_close == 0
    gate_rows.append(
        {
            "index_code": _code,
            "name": _name,
            "n_rows": n_rows,
            "first_day": "" if first_day is None else first_day.isoformat(),
            "last_day": "" if last_day is None else last_day.isoformat(),
            "null_close": null_close,
            "max_gap_days": max_gap,
            "gap_violations": violations,
            "pass_rows_last": bool(pass_last),
            "pass_rows_first": bool(pass_first),
            "pass_gap": bool(pass_gap),
            "pass_close": bool(pass_close),
            "passed": bool(pass_last and pass_first and pass_gap and pass_close),
        }
    )

gate = pd.DataFrame(gate_rows)
hdr("闸门：QT_OSIndexQuote 回填完整性")
show(
    f"gate 每代码行数、起止、最大间隔（自然日；缺口只查 {OVL_GAP_CHECK_FROM} 起）",
    gate,
)
if not bool(gate["passed"].all()):
    for _note in gap_notes:
        print(_note, flush=True)
    log(
        "闸门未通过：境外指数回填未完成或不完整，停止，不产出结果"
        f"（要求：最大交易日 >= {OVL_LAST_REQUIRED}、最小交易日 <= 计划起始、"
        f"{OVL_GAP_CHECK_FROM} 起间隔 <= {OVL_MAX_GAP_DAYS} 天、close 无 NULL）"
    )
    conn.close()
    sys.exit(1)
log(f"闸门通过：五个代码行数 {int(gate['n_rows'].sum())}，覆盖全部工作区间")

# %% [markdown]
# ## A 股侧读取（与报告五、报告六同一段代码）
#
# 中债、中间价是日频单版本、发布当天可见，以研究截止日整段读一次再按信号日对齐。
# 美债按契约严格早于信号日（`观测日 < 信号日`，7 天过期）。TIPS 有版本，按逐日 as_of 读取。

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
log(f"中债 {len(r_cn_raw)} 美债 {len(r_us_raw)} 中间价 {int(fx_raw.notna().sum())}")

ret_rows = index_returns.list_returns(as_of=AS_OF, start=START, end=AS_OF, wind_codes=TR_CODES)
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

# %% [markdown]
# ## 月度面板
#
# 信号日 = 每月最后一个 A 股开市日。`month_log_sum` 给出同月价差用的自然月对数收益
# （窗口 = (上月信号日, 本月信号日]），`fwd_spread` 给出 T+1 收盘成交的下月价差。

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


# %% [markdown]
# ## 境外指数月末取值
#
# 对每个 A 股信号日 T，取严格早于 T 的最后一个境外 trading_day 的收盘（端口已保证
# `TradingDay < as_of` 可见）。一次整段读出后按 `< T` 对齐与逐 T 调端口等价：契约是
# 「TradingDay 严格早于 as_of」的单调规则，只要 `T <= AS_OF`，T 之前可见的行在
# as_of=AS_OF 下同样可见，且对齐只取 T 之前的行，不会用到 T 当日或之后的收盘。
# 距 T 超过 7 个自然日即 NaN（不补前值、不跨市场对齐）。


# %%
def month_end_level(name: str) -> np.ndarray:
    days = ovl_days[name]
    closes = ovl_close[name]
    out = np.full(N_M, np.nan)
    for i, t in enumerate(SIGNAL_DATES):
        td = t.to_datetime64().astype("datetime64[D]")
        pos = int(np.searchsorted(days, td, side="left")) - 1
        if pos < 0:
            continue
        if int((td - days[pos]).astype("int64")) > OVL_STALE_DAYS:
            continue
        out[i] = closes[pos]
    return out


def dlog100(level: np.ndarray) -> np.ndarray:
    """百分数对数变化；任一端缺失即 NaN。"""
    out = np.full(N_M, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        lg = np.log(np.where(np.isfinite(level) & (level > 0), level, np.nan))
    out[1:] = 100.0 * (lg[1:] - lg[:-1])
    return out


LEVEL = {name: month_end_level(name) for name in OVL_CODES}
DLOG = {name: dlog100(LEVEL[name]) for name in OVL_CODES}
G_US = DLOG["RLG"] - DLOG["RUI"]
G_NDX = DLOG["NDX"] - DLOG["SPX"]
D_USD = DLOG["USDX"]
for _name in OVL_CODES:
    _ok = np.flatnonzero(np.isfinite(LEVEL[_name]))
    log(
        f"{_name} 月末取值有效 {len(_ok)} 个月"
        + (f"，{SIGNAL_DATES[_ok[0]].date()}..{SIGNAL_DATES[_ok[-1]].date()}" if len(_ok) else "")
    )

# %% [markdown]
# ## 汇总月度面板

# %%
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

monthly = pd.DataFrame(
    {
        "period": LAST_OF_MONTH.index.astype(str).to_numpy(),
        "signal_dt": SIGNAL_DATES,
        "r_us": RUS_M,
        "r_cn": RCN_M,
        "tips": TIPS_M,
        "be": BE_M,
        "fx": FX_M,
        "rlg": LEVEL["RLG"],
        "rui": LEVEL["RUI"],
        "ndx": LEVEL["NDX"],
        "spx": LEVEL["SPX"],
        "usdx": LEVEL["USDX"],
        "g_us": G_US,
        "g_ndx": G_NDX,
        "d_usd": D_USD,
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
D_TIPS = monthly["d_tips"].to_numpy(dtype=float)

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
# ## 残差因子
#
# `g_us⊥` 是 g_us 对同月 ΔTIPS（含常数）的残差，代表与实际利率无关的美国成长风格冲击。
# 回归只在 D1 样本内估（300 价差、ΔTIPS、ΔBE、Δr_CN、g_US 都齐的月份），再对全部有
# g_us 与 d_tips 的月份算残差；样本外那些月的残差不用来估系数。


# %%
def residual_on_dtips(x: np.ndarray) -> np.ndarray:
    base = np.zeros(N_M, dtype=bool)
    base[SPREAD_START_POS[SPREAD_300] :] = True
    for arr in (
        monthly["spread_300"].to_numpy(dtype=float),
        D_TIPS,
        monthly["d_be"].to_numpy(dtype=float),
        monthly["d_rcn"].to_numpy(dtype=float),
        x,
    ):
        base &= np.isfinite(arr)
    idx = np.flatnonzero(base)
    if len(idx) < MIN_N:
        raise RuntimeError(f"残差回归样本太短：{len(idx)}，停止")
    design = np.column_stack([np.ones(len(idx)), D_TIPS[idx]])
    coef = np.linalg.lstsq(design, x[idx], rcond=None)[0]
    out = np.full(N_M, np.nan)
    ok = np.isfinite(x) & np.isfinite(D_TIPS)
    out[ok] = x[ok] - (coef[0] + coef[1] * D_TIPS[ok])
    log(f"残差因子：n={len(idx)}，斜率 {coef[1]:.6f}，常数 {coef[0]:.6f}")
    return out


G_US_PERP = residual_on_dtips(G_US)
G_NDX_PERP = residual_on_dtips(G_NDX)
monthly["g_us_perp"] = G_US_PERP
monthly["g_ndx_perp"] = G_NDX_PERP

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
    (b2_ref["spread_name"] == SPREAD_300) & (b2_ref["model"] == "B2") & (b2_ref["sample"] == "full")
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
        {
            "field": f"{_var}_coef",
            "ours": _c_ours,
            "report5": _c_ref,
            "diff": abs(_c_ours - _c_ref),
            "equal": bool(abs(_c_ours - _c_ref) <= REF_TOL),
        }
    )
    _repro_rows.append(
        {
            "field": f"{_var}_t_nw",
            "ours": _t_ours,
            "report5": _t_ref,
            "diff": abs(_t_ours - _t_ref),
            "equal": bool(abs(_t_ours - _t_ref) <= REF_TOL),
        }
    )
_repro_rows.append(
    {
        "field": "n",
        "ours": float(_b2_n),
        "report5": float(b2_ref_rows["n"].iloc[0]),
        "diff": abs(_b2_n - float(b2_ref_rows["n"].iloc[0])),
        "equal": bool(_b2_n == int(b2_ref_rows["n"].iloc[0])),
    }
)
_repro_rows.append(
    {
        "field": "start",
        "ours": _b2_first,
        "report5": str(b2_ref_rows["start"].iloc[0]),
        "diff": np.nan,
        "equal": bool(_b2_first == str(b2_ref_rows["start"].iloc[0])),
    }
)
_repro_rows.append(
    {
        "field": "end",
        "ours": _b2_last,
        "report5": str(b2_ref_rows["end"].iloc[0]),
        "diff": np.nan,
        "equal": bool(_b2_last == str(b2_ref_rows["end"].iloc[0])),
    }
)
b2_repro = pd.DataFrame(_repro_rows)[["field", "ours", "report5", "diff", "equal"]]
hdr("断言：同月价差复现报告五 B2（spread ~ d_rus + d_rcn，NW 滞后 3）")
show("b2_repro 断言（阈值 1e-10；n 与起止日期要求完全相等）", b2_repro)
if not bool(b2_repro["equal"].all()):
    raise RuntimeError("断言失败：B2 与报告五不一致，停止")
log(f"断言通过：B2 与报告五逐值一致，{_b2_first}..{_b2_last}，n={_b2_n}")

# %% [markdown]
# ## 回归工具
#
# 每个自变量一行，n 与 r2 在同一次回归内相同。样本起点是该价差第一个同月价差可用月，
# Newey-West 滞后 3。

# %%
REG_COLS = [
    "spread_name",
    "model",
    "growth_proxy",
    "sample",
    "var",
    "coef",
    "t_nw",
    "n",
    "r2",
    "start",
    "end",
]


def reg_block(
    *,
    spread_name: str,
    model: str,
    growth_proxy: str,
    y: np.ndarray,
    xs: tuple[str, ...],
    sample: str = "full",
) -> list[dict[str, object]]:
    """一次 OLS（NW 滞后 3），每个自变量一行。缺值不补：行必须全部非 NaN。"""
    cols = {name: monthly[name].to_numpy(dtype=float) for name in xs}
    mask = np.isfinite(y)
    for arr in cols.values():
        mask &= np.isfinite(arr)
    mask[: SPREAD_START_POS[spread_name]] = False
    if sample == "post_2015_08":
        mask &= POST_FX_MASK
    elif sample != "full":
        raise RuntimeError(f"未知样本标签 {sample}")
    idx = np.flatnonzero(mask)
    if len(idx) < MIN_N:
        raise RuntimeError(f"{spread_name} {model} {sample} 样本太短：{len(idx)}")
    fit, n = nw_ols(
        pd.Series(y[idx], name="y"),
        pd.DataFrame({k: v[idx] for k, v in cols.items()}),
        NW_LAGS,
    )
    r2 = float(fit.rsquared)
    log(f"  {spread_name} {model} {growth_proxy} {sample}: n={n} r2={r2:.4f}")
    return [
        {
            "spread_name": spread_name,
            "model": model,
            "growth_proxy": growth_proxy,
            "sample": sample,
            "var": name,
            "coef": float(fit.params[name]),
            "t_nw": float(fit.tvalues[name]),
            "n": n,
            "r2": r2,
            "start": str(monthly["period"].iloc[idx[0]]),
            "end": str(monthly["period"].iloc[idx[-1]]),
        }
        for name in xs
    ]


SPREAD300_ARR = monthly["spread_300"].to_numpy(dtype=float)
SPREADCYB_ARR = monthly["spread_cyb"].to_numpy(dtype=float)
FWD300_ARR = monthly["fwd_300"].to_numpy(dtype=float)
D1_CONTROLS = ("d_tips", "d_be", "d_rcn")

# %% [markdown]
# ## D1：同期分解（300 价差，2011-09 起）
#
# 模型 1 加 g，模型 2 加 g⊥（g 对同月 ΔTIPS 的残差），再分别用 g_NDX 做一遍（只报告）。
# B3 是不含 g 的原模型，作为对照行。判读只看 g_US 的版本。

# %%
d1_rows: list[dict[str, object]] = []
for _proxy, _perp in (("g_us", "g_us_perp"), ("g_ndx", "g_ndx_perp")):
    d1_rows += reg_block(
        spread_name=SPREAD_300,
        model="M1",
        growth_proxy=_proxy,
        y=SPREAD300_ARR,
        xs=(*D1_CONTROLS, _proxy),
    )
    d1_rows += reg_block(
        spread_name=SPREAD_300,
        model="M2",
        growth_proxy=_proxy,
        y=SPREAD300_ARR,
        xs=(*D1_CONTROLS, _perp),
    )
d1_rows += reg_block(
    spread_name=SPREAD_300,
    model="B3",
    growth_proxy="none",
    y=SPREAD300_ARR,
    xs=D1_CONTROLS,
)
d1_reg = pd.DataFrame(d1_rows)[REG_COLS]
show("d1_reg 同期分解（300 价差，NW 滞后 3）", d1_reg)


def d1_value(model: str, proxy: str, var: str, col: str) -> float:
    hit = d1_reg[
        (d1_reg["model"] == model) & (d1_reg["growth_proxy"] == proxy) & (d1_reg["var"] == var)
    ]
    if len(hit) != 1:
        raise RuntimeError(f"d1_reg 缺少 {model}/{proxy}/{var}，停止")
    return float(hit[col].iloc[0])


# %% [markdown]
# ### D1 判读（事先写定，只对 g_US）
#
# - `duration_direct`：模型 1 中 ΔTIPS 仍满足 t ≤ −2；
# - `via_global_growth`：模型 1 中 |t_ΔTIPS| < 1 且 g_US 满足 t ≥ 2；
# - `extra_sync`：模型 2 中 g_US⊥ 满足 t ≥ 2（可与前两条同时成立）；
# - 其余为「区分不了」。

# %%
_d1_t_tips = d1_value("M1", "g_us", "d_tips", "t_nw")
_d1_t_gus = d1_value("M1", "g_us", "g_us", "t_nw")
_d1_t_gus_perp = d1_value("M2", "g_us", "g_us_perp", "t_nw")
DURATION_DIRECT = bool(_d1_t_tips <= -2.0)
VIA_GLOBAL_GROWTH = bool(abs(_d1_t_tips) < 1.0 and _d1_t_gus >= 2.0)
EXTRA_SYNC = bool(_d1_t_gus_perp >= 2.0)
UNDETERMINED = not (DURATION_DIRECT or VIA_GLOBAL_GROWTH or EXTRA_SYNC)
d1_judge = pd.DataFrame(
    [
        {
            "spread_name": SPREAD_300,
            "growth_proxy": "g_us",
            "t_dtips_m1": _d1_t_tips,
            "coef_dtips_m1": d1_value("M1", "g_us", "d_tips", "coef"),
            "t_growth_m1": _d1_t_gus,
            "coef_growth_m1": d1_value("M1", "g_us", "g_us", "coef"),
            "t_growth_perp_m2": _d1_t_gus_perp,
            "coef_growth_perp_m2": d1_value("M2", "g_us", "g_us_perp", "coef"),
            "duration_direct": DURATION_DIRECT,
            "via_global_growth": VIA_GLOBAL_GROWTH,
            "extra_sync": EXTRA_SYNC,
            "undetermined": bool(UNDETERMINED),
        }
    ]
)
show("d1_judge（只对 g_US；三条判据可以同时成立）", d1_judge)

_corr_rows: list[dict[str, object]] = []
for _proxy in ("g_us", "g_ndx"):
    _mask = np.zeros(N_M, dtype=bool)
    _mask[SPREAD_START_POS[SPREAD_300] :] = True
    _x = monthly[_proxy].to_numpy(dtype=float)
    _mask &= np.isfinite(_x) & np.isfinite(D_TIPS)
    _idx = np.flatnonzero(_mask)
    if len(_idx) < MIN_N:
        raise RuntimeError(f"corr({_proxy}, d_tips) 样本太短：{len(_idx)}")
    _corr_rows.append(
        {
            "growth_proxy": _proxy,
            "var": "d_tips",
            "corr": float(np.corrcoef(_x[_idx], D_TIPS[_idx])[0, 1]),
            "n": len(_idx),
            "start": str(monthly["period"].iloc[_idx[0]]),
            "end": str(monthly["period"].iloc[_idx[-1]]),
        }
    )
d1_corr = pd.DataFrame(_corr_rows)
show("d1_corr 成长因子与同月 ΔTIPS 的相关系数（D1 样本）", d1_corr)

# %% [markdown]
# ## D2：美元渠道（只报告）
#
# 300 价差与创业板价差分别做 `spread ~ ΔTIPS + ΔBE + ΔUSD + Δr_CN`，样本为 full 与
# 2015-08 起。美元指数代表美元对一篮子货币，中间价代表人民币对美元，两者都报告。

# %%
d2_rows: list[dict[str, object]] = []
for _spread, _y in ((SPREAD_300, SPREAD300_ARR), (SPREAD_CYB, SPREADCYB_ARR)):
    for _sample in ("full", "post_2015_08"):
        d2_rows += reg_block(
            spread_name=_spread,
            model="D2",
            growth_proxy="d_usd",
            y=_y,
            xs=("d_tips", "d_be", "d_usd", "d_rcn"),
            sample=_sample,
        )
d2_reg = pd.DataFrame(d2_rows)[REG_COLS]
show("d2_reg 美元渠道（只报告）", d2_reg)

# %% [markdown]
# ## D3：美国成长因子能否预测下月价差（只报告）
#
# `fwd_spread_{t+1} ~ g_t`，300 价差，Newey-West 滞后 3，口径同 C1。

# %%
d3_rows: list[dict[str, object]] = []
for _proxy in ("g_us", "g_ndx"):
    d3_rows += reg_block(
        spread_name=SPREAD_300,
        model="D3",
        growth_proxy=_proxy,
        y=FWD300_ARR,
        xs=(_proxy,),
    )
d3_reg = pd.DataFrame(d3_rows)[REG_COLS]
show("d3_reg 预测回归（只报告）", d3_reg)

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
    "src.jydb.qt_osindexquote",
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
        "境外指数次日可见：qt_osindexquote 契约是 TradingDay 严格早于 as_of，"
        "A 股信号日 T 只能用到 T 之前的最后一个境外交易日收盘。",
        "RLG/RUI/NDX/SPX 为价格指数，未含股息；股息差异约每年 1 个百分点，月度可忽略，"
        "因此 g_US 是价格口径的成长相对全市场，不是全收益口径。",
        "USDX 为 NYCE 美元指数（美元对一篮子货币），与 cn_usdcny_fix（人民币对美元）"
        "口径不同，两者都只报告。",
        "方向与样本已在报告五观察过（同一段样本上 300 成长相对 300 价值的同期利率敏感度为负），"
        "D 的结论最高第 2 类。",
        "TIPS 按 ALFRED 版本逐信号日读 as_of，契约严格早于信号日，超过 7 个自然日视为缺失；"
        "BE = r_US − TIPS 是同一日的恒等式拆分，不是 T10YIE。",
        "下月价差从 T+1 收盘起算，到下一信号日的 T+1 收盘止，符合 T+1 成交：日收益区间 "
        "(T+1, T'+1]，任一天缺失即 NaN。",
    ],
}

panel_records: dict[str, object] = {}
_daily = pd.DataFrame(
    {
        "trade_dt": open_idx,
        "r_cn": r_cn,
        "r_us": r_us,
        "tips": tips,
        "fx": fx,
        "ret_growth": RG,
        "ret_value": RV,
        "ret_cyb": RCY,
        "ret_allshare": RALL,
    }
)
panel_records["daily"] = json.loads(_daily.to_json(orient="records", date_format="iso"))
panel_records["monthly"] = json.loads(monthly.to_json(orient="records", date_format="iso"))
panel_records["overseas_gate"] = json.loads(gate.to_json(orient="records"))

starts = {
    "spread_300": str(monthly["period"].iloc[SPREAD_START_POS[SPREAD_300]]),
    "spread_cyb": str(monthly["period"].iloc[SPREAD_START_POS[SPREAD_CYB]]),
    "b2_ref": f"{_b2_first}..{_b2_last}",
    "overseas": {row["name"]: f"{row['first_day']}..{row['last_day']}" for row in gate_rows},
    "g_us_first_period": str(monthly["period"].iloc[int(np.flatnonzero(np.isfinite(G_US))[0])]),
}
input_digest = digest_json({"params": PARAMS, "panels": panel_records, "starts": starts})

results = {
    "gate": gate,
    "b2_repro": b2_repro,
    "d1_reg": d1_reg,
    "d1_judge": d1_judge,
    "d1_corr": d1_corr,
    "d2_reg": d2_reg,
    "d3_reg": d3_reg,
}
output_digest = digest_json(
    {k: json.loads(v.to_json(orient="records")) for k, v in results.items()}
)

judgement = {
    "duration_direct": DURATION_DIRECT,
    "via_global_growth": VIA_GLOBAL_GROWTH,
    "extra_sync": EXTRA_SYNC,
    "undetermined": bool(UNDETERMINED),
    "detail": {
        "t_dtips_m1": _d1_t_tips,
        "t_growth_m1": _d1_t_gus,
        "t_growth_perp_m2": _d1_t_gus_perp,
    },
    "d1_judgement_rule": PARAMS["d1_judgement"],
    "g_ndx_note": "g_NDX 与 g_NDX⊥ 的两个模型只报告，不参与判读",
    "research_class": "2 (direction and sample taken from the already observed report five)",
}

run_id = new_run_id()
out_dir = paths.root / "research" / "erp_overseas_style" / run_id
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
        action="research.erp_overseas_style",
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
