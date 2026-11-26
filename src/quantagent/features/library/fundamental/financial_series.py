"""Wind 财报季度序列处理纯函数，barra 风格因子（ERNQLT 等）用。

复现旧仓 ``core/raw_loader.py`` 的 ``_add_quarter_col`` / ``_convert_quarter`` 与
``QUALITY.__init__`` 的矩阵透视 + ``rolling(4).sum()`` TTM 语义。**纯 python（不用 pandas）**，
与项目既有 panel/library 风格一致。

核心概念：

- **keep=last 去重**：同一（股票, 报告期）多次公告（修订），取 ``ann_dt`` 最大（最后公告）的版本。
  对应 RAW ``drop_duplicates(['S_INFO_WINDCODE','REPORT_PERIOD'], keep='last')``（其输入按
  ``ORDER BY REPORT_PERIOD, ANN_DT``，keep=last 即取 ANN_DT 最新）。
- **tail(count)**：每只股票取**最近 count 个报告期**（count=21，ERNQLT 用 5×4+1 期历史）。
- **last_report_num**：报告期在全样本（所有股票所有期）排序后的相对期号。RAW 用它做 pivot 的
  行索引，对齐不同股票不齐的财报期。**注意**：本项目逐股票独立处理，不依赖跨股票的统一期号——
  因为 rolling/TTM 都是逐股票时序操作，跨股票对齐只发生在截面 descriptor_process。故本模块
  不引入 last_report_num，直接按报告期排序处理每只股票，语义等价且更简单。
- **单季拆分（``field_Q``）**：流量字段（利润/现金流/折旧）从**累计值**拆成单季：
  Q1（0331）= 累计值本身；其余季 = 本期累计 − 上期累计（``field − field_last``）。
  ``is_last`` 校验：上期报告期必须是**相邻上一季**（``REPORT_PERIOD_LAST == get_last_period(本期)``）
  才有效，否则 ``field_Q = None``（防止财报期不连续时错算差额）。
- **折旧摊销插值**：``S_STM_IS``/``CAPITALIZED`` 只有半年报（0630）+ 年报（1231）有数据，
  Q1/Q3 缺失。缺失季按 ``last / last_month × this_month`` 比例插值（last_month/this_month
  是上期/本期报告期的月份数 3/6/9/12）。**注意这是月度比例换算，不是简单平分**。
- **rolling(4).sum() TTM**：满 4 期才产值（前 3 期 None），**窗口内任一 None 则结果为 None**
  （pandas rolling 默认 min_periods=window，NaN 传播）。任一季缺失（折旧插值失败/is_last 不连续）
  使 TTM 为 None，进而 descriptor 为空——与"数据不足则 descriptor 为空"裁定一致。

口径裁定（2026-11-26）：股票池 all_a 减 ST、不预过滤上市时间、数据不足则 descriptor 为空。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from quantagent.domain.errors import InvalidQueryError

if TYPE_CHECKING:
    from quantagent.domain.fundamental.types import FinancialSeriesRecord

# 报告期 mmdd 列表（正式季报截止日）。
_MMDD_LIST = ("0331", "0630", "0930", "1231")
# 折旧摊销/资本支出字段：只有半年报+年报有数据，需插值（复现旧仓特殊处理）。
_INTERPOLATE_FIELDS = frozenset({"S_STM_IS", "CAPITALIZED"})


def get_last_period(period: date) -> date | None:
    """上一报告期。0331→前年1231；0630→0331；0930→0630；1231→0930。非季末返回 None。"""
    mmdd = period.strftime("%m%d")
    if mmdd not in _MMDD_LIST:
        return None
    i = _MMDD_LIST.index(mmdd)
    year = period.year
    if i == 0:
        return date(year - 1, 12, 31)
    prev_mmdd = _MMDD_LIST[i - 1]
    return date(year, int(prev_mmdd[:2]), int(prev_mmdd[2:]))


def dedupe_keep_last(
    rows: tuple[FinancialSeriesRecord, ...],
) -> dict[str, dict[date, FinancialSeriesRecord]]:
    """按（股票, 报告期）keep=last 去重，返回 {asset_id: {report_period: 行}}。

    同报告期取 ``ann_dt`` 最大的版本（修订取最新）；ann_dt 并列时取输入序列中靠后的
    （adapter 已按 ANN_DT 升序，遍历覆盖即 keep=last）。
    """
    out: dict[str, dict[date, FinancialSeriesRecord]] = {}
    for row in rows:
        per_stock = out.setdefault(row.asset_id, {})
        existing = per_stock.get(row.report_period)
        if existing is None or row.ann_dt >= existing.ann_dt:
            per_stock[row.report_period] = row
    return out


def sorted_periods(
    stock_rows: dict[date, FinancialSeriesRecord],
    *,
    count: int,
) -> list[date]:
    """取最近 count 个报告期，升序返回（tail(count) 后保持时间序）。"""
    periods = sorted(stock_rows.keys())
    return periods[-count:] if len(periods) > count else periods


def split_single_quarter(
    stock_rows: dict[date, FinancialSeriesRecord],
    field: str,
    *,
    count: int,
) -> list[tuple[date, Decimal | None]]:
    """对单只股票的某流量字段做累计→单季拆分，返回 [(report_period, 单季值)] 按时间升序。

    复现 ``_add_quarter_col``：先按报告期排序、tail(count)，再逐期算 ``field_Q``。
    折旧类字段先做月度比例插值再拆分。存量字段（资产/负债等）**不应**用本函数——直接用原值。
    """
    periods = sorted_periods(stock_rows, count=count)
    rows = [stock_rows[p] for p in periods]
    interp = field in _INTERPOLATE_FIELDS
    # 第一步：构建累计值序列。折旧类字段缺失季按 last/last_month×this_month 插值，
    # 插值就地进行、逐期向后传播（旧仓插值后重算 field_last=shift(插值后field)，
    # 故下期插值基于本期已插值的值——链式）。非折旧字段不插值，原样（缺失保持 None）。
    cumulative: list[Decimal | None] = []
    for idx, row in enumerate(rows):
        val = row.values.get(field)
        if interp and val is None and idx > 0:
            prev_val = cumulative[idx - 1]
            prev_period = rows[idx - 1].report_period
            if prev_val is not None and prev_period.month != 0:
                # last/last_month×this_month，月份取报告期月份（3/6/9/12）。
                val = prev_val / Decimal(prev_period.month) * Decimal(row.report_period.month)
        cumulative.append(val)
    # 第二步：单季拆分。is_last 校验对**所有期**（含 Q1）生效：上期存在且为相邻上一季才产值。
    # 序列第一期永远 is_last=False → 第一期永远 None（Q1 也不例外——旧仓 ``~is_last`` 覆盖 Q1）。
    # Q1 用累计值本身；非 Q1 = 本期累计 − 上期累计。
    out: list[tuple[date, Decimal | None]] = []
    for idx, row in enumerate(rows):
        period = row.report_period
        cur = cumulative[idx]
        if idx == 0:
            out.append((period, None))
            continue
        expected_prev = get_last_period(period)
        actual_prev = rows[idx - 1].report_period
        is_last = expected_prev is not None and actual_prev == expected_prev
        if not is_last or cur is None:
            out.append((period, None))
            continue
        if period.strftime("%m%d") == "0331":
            out.append((period, cur))
            continue
        prev = cumulative[idx - 1]
        out.append((period, cur - prev if prev is not None else None))
    return out


def rolling_ttm(values: list[Decimal | None], *, window: int = 4) -> list[Decimal | None]:
    """``rolling(window).sum()``：满 window 期才产值，窗口内任一 None 则结果 None（NaN 传播）。

    返回与输入等长的列表，前 window-1 个为 None。用于流量单季序列的 TTM。
    """
    out: list[Decimal | None] = []
    for i in range(len(values)):
        if i < window - 1:
            out.append(None)
            continue
        window_vals = values[i - window + 1 : i + 1]
        if any(v is None for v in window_vals):
            out.append(None)
        else:
            out.append(sum(window_vals))  # type: ignore[arg-type]
    return out


def latest_value(
    stock_rows: dict[date, FinancialSeriesRecord],
    field: str,
) -> Decimal | None:
    """最新报告期（按 ann_dt keep=last 后时间最大期）的字段值。用于资产负债表当期截面（如总资产分母）。"""
    if not stock_rows:
        return None
    latest_period = max(stock_rows.keys())
    return stock_rows[latest_period].values.get(field)


def period_series_values(
    stock_rows: dict[date, FinancialSeriesRecord],
    field: str,
    *,
    count: int,
) -> list[tuple[date, Decimal | None]]:
    """存量字段的逐期原值序列（不拆分），[(report_period, value)] 按时间升序、tail(count)。"""
    periods = sorted_periods(stock_rows, count=count)
    return [(p, stock_rows[p].values.get(field)) for p in periods]


def require_decimal(value: Decimal | None, field: str) -> Decimal:
    """非空校验：descriptor 计算的硬依赖缺失时由调用方决定跳过（返回 None 而非报错，由 panel 控制）。"""
    if value is None:
        raise InvalidQueryError(f"{field} 缺失")
    return value
