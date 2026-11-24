"""``pf_single_mif_1_mean_neg``。
旧仓 ``factors/factors.py`` 的 ``MIF``（国盛《基于对知情交易者信息优势的刻画》）：
窗口内 20 个截面日的 ``|night_ratio|`` 与各自前一交易日换手率的 Pearson 相关系数。
``night_ratio = round(100 * (adj_open / adj_preclose - 1), 4)``（ROUND_HALF_UP），公式取自旧仓
``docs/DESIGN/DESIGN-0025-stock-factor-catalog.md`` 第 124 行，与旧仓派生表 ``stock_ratio.night_ratio`` 对应。
4 位舍入是为了与旧输入精度一致：旧表列为 numeric(20,4)，旧 MIF 用的就是这 4 位小数。
只在可复现的截面日成立（见 ADR ``docs/adr/2026-11-24-mif.md`` 决策 3）：截面日的 21 行窗口内，每个交易日的
``stock_ratio.night_ratio`` 与本公式吻合率都 ≥99%。已核验的 1,147 个交易日里吻合率为 99.76%–100%。
窗口内有派生表不一致的交易日，本仓不保证复现旧值。Current-20 消费方向为 -1，长表存 ``-raw``。

窗口是个股自有行，不是开市日：往前取 21 行价格，其中第 2–21 行的 ``night_ratio`` 进入相关，
第 1–20 行的换手率作为滞后项。换手按 ``(wind_code, trade_dt)`` 对齐到价格行，衍生指标里没有对应
价格行的非交易日行不参与。

缺失规则（本仓口径，旧仓只要求窗口全非空）：
- 停牌行（``trade_status_code == 0``）的 ``night_ratio`` 记缺失，不记 0。停牌日没有成交，
  开盘价是 Wind 填的前收盘价，不是观测。因此含停牌行的 20 行窗口整窗不产值。
- ``adj_preclose`` 缺失或非正、``adj_open`` 缺失，该行 ``night_ratio`` 缺失。
- 窗口内任一换手缺失，或 ``|night_ratio|`` 与换手之一在窗口内为常数（方差为 0），都不产值。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.derivative_indicator.types import Turnover
    from quantagent.domain.prices.types import DailyPrice

FEATURE_ID = "pf_single_mif_1_mean_neg"
DEFINITION_VERSION = "v1"
# 相关的样本行数。
WINDOW = 20
# 换手滞后的行数：第 k 行的换手取自第 k-1 个价格行（个股自有行序，不是日历）。
LAG = 1
SIGN = Decimal("-1")
HUNDRED = Decimal(100)
HALTED_CODE = 0
# night_ratio 的舍入位数与舍入方式。核实的 3 个截面日（约 1.5 万行）上 HALF_UP 与 HALF_EVEN 结果无差异，
# 两者并列，取 HALF_UP，与本仓 q6 的舍入约定一致。舍入后再进入 |·| 与相关。
NIGHT_DECIMALS = Decimal("0.0001")
# 相关至少需要两对样本；窗口长度已由 WINDOW 固定，这里只防御调用方传入的退化序列。
_MIN_PAIRS = 2
# 60 位有效数字足以让两遍法的中心化误差远小于常数判断以外的精度要求。
_CONTEXT = Context(prec=60)

PARAMS = {
    "window": WINDOW,
    "lag": LAG,
    "sign": format(SIGN, "f"),
    "mean_window": 1,
}
PARAM_HASH = digest_json(PARAMS)


@dataclass(frozen=True)
class MifValue:
    event_dt: date
    asset_id: str
    raw: Decimal
    value: Decimal
    knowledge_dt: date
    pit_grade: str


def night_ratio(row: DailyPrice) -> Decimal | None:
    """单日隔夜收益（百分比，保留 4 位小数）。停牌、复权价缺失或前收非正都返回 ``None``。
    停牌行的开盘价是 Wind 填的前收盘价，不是观测，所以记缺失而不记 0。
    """
    if row.trade_status_code == HALTED_CODE:
        return None
    if row.adj_open is None or row.adj_preclose is None:
        return None
    if row.adj_preclose <= 0:
        return None
    with localcontext(_CONTEXT):
        raw = HUNDRED * (row.adj_open / row.adj_preclose - 1)
        return raw.quantize(NIGHT_DECIMALS, rounding=ROUND_HALF_UP)


def mif_value(
    window: Sequence[DailyPrice],
    turnover_by_day: Mapping[date, Turnover],
    *,
    price_contract: VisibilityContract,
    turnover_contract: VisibilityContract,
) -> MifValue | None:
    """``window`` 是个股自有的最近 21 行价格，最后一行是截面日，按交易日升序。
    ``turnover_by_day`` 是同一只股票按交易日索引的换手行，缺哪一天就当缺失。
    """
    if len(window) != WINDOW + LAG:
        return None
    rows = tuple(window)
    nights: list[Decimal] = []
    for row in rows[LAG:]:
        ratio = night_ratio(row)
        if ratio is None:
            return None
        nights.append(abs(ratio))
    turns: list[Decimal] = []
    for row in rows[:WINDOW]:
        turn = turnover_by_day.get(row.trade_dt)
        if turn is None or turn.turnover is None:
            return None
        turns.append(turn.turnover)
    raw = _pearson(nights, turns)
    if raw is None:
        return None
    grade = price_contract.visibility.grade
    turnover_grade = turnover_contract.visibility.grade
    inputs = [(row.trade_dt, grade) for row in rows[LAG:]]
    inputs.extend((row.trade_dt, turnover_grade) for row in rows[:WINDOW])
    knowledge_dt, pit_grade = derive_feature_lineage(tuple(inputs))
    return MifValue(
        event_dt=rows[-1].trade_dt,
        asset_id=rows[-1].wind_code,
        raw=raw,
        value=SIGN * raw,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
    )


def _pearson(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    """两遍法 Pearson。先判常数再算：两列各自全相等时方差为 0，相关无定义，返回 ``None``。
    常数判断用精确相等，不靠浮点或小量阈值，避免把接近常数的真实波动误判为常数。
    """
    if len(xs) != len(ys) or len(xs) < _MIN_PAIRS:
        return None
    if _is_constant(xs) or _is_constant(ys):
        return None
    with localcontext(_CONTEXT):
        n = Decimal(len(xs))
        mean_x = sum(xs, Decimal(0)) / n
        mean_y = sum(ys, Decimal(0)) / n
        dx = [x - mean_x for x in xs]
        dy = [y - mean_y for y in ys]
        sxy = sum((a * b for a, b in zip(dx, dy, strict=True)), Decimal(0))
        sxx = sum((a * a for a in dx), Decimal(0))
        syy = sum((b * b for b in dy), Decimal(0))
        if sxx == 0 or syy == 0:
            return None
        return sxy / (sxx * syy).sqrt()


def _is_constant(values: Sequence[Decimal]) -> bool:
    first = values[0]
    return all(value == first for value in values)
