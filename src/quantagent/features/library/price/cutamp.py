"""``pf_single_cutamp_1_mean_neg``。

旧仓 ``CUTAMP.cal`` 用 20 个交易日的高低价振幅，去掉收盘触及涨跌停的日子，
按复权收盘价切出高低两端各 25% 的振幅差。Current-20 消费的是这个值的相反数，
窗口为 1。缺失不落成 0。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.prices.types import DailyPrice

FEATURE_ID = "pf_single_cutamp_1_mean_neg"
DEFINITION_VERSION = "v1"
WINDOW = 20
MIN_KEPT = 10
CUT_RATIO = Decimal("0.25")
SIGN = Decimal("-1")
PARAMS = {
    "window": WINDOW,
    "min_kept": MIN_KEPT,
    "cut_ratio": format(CUT_RATIO, "f"),
    "sign": format(SIGN, "f"),
    "mean_window": 1,
}
PARAM_HASH = digest_json(PARAMS)


@dataclass(frozen=True)
class CutampValue:
    event_dt: date
    asset_id: str
    raw: Decimal
    value: Decimal
    knowledge_dt: date
    pit_grade: str


def cutamp_value(
    window: Sequence[DailyPrice],
    *,
    contract: VisibilityContract,
) -> CutampValue | None:
    """窗口必须已经按交易日排好，且最后一天是截面日。不够 20 日则缺失。"""
    if len(window) < WINDOW:
        return None
    rows = tuple(window[-WINDOW:])
    raw = _raw_cutamp(rows)
    if raw is None:
        return None
    grade = contract.visibility.grade
    knowledge_dt, pit_grade = derive_feature_lineage(tuple((row.trade_dt, grade) for row in rows))
    return CutampValue(
        event_dt=rows[-1].trade_dt,
        asset_id=rows[-1].wind_code,
        raw=raw,
        value=SIGN * raw,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
    )


def _raw_cutamp(rows: Sequence[DailyPrice]) -> Decimal | None:
    kept: list[tuple[Decimal, Decimal, object]] = []
    for row in rows:
        if row.close is None or row.high is None or row.low is None or row.adj_close is None:
            continue
        if row.low == 0:
            return None
        if row.close in {row.limit_up, row.limit_down}:
            continue
        amplitude = Decimal(100) * (row.high / row.low - 1)
        kept.append((row.adj_close, amplitude, row.trade_dt))
    if len(kept) < MIN_KEPT:
        return None
    # 复权收盘价并列时按交易日稳定排序。旧仓 pandas sort_values 默认 quicksort，
    # 并列顺序不稳定；2024-01-05 全市场对拍里，无并列的股票全部一致，差异只出现在并列上。
    kept.sort(key=lambda item: (item[0], item[2]))
    cut = int(CUT_RATIO * len(kept))
    if cut == 0:
        return None
    low_mean = sum((item[1] for item in kept[:cut]), Decimal(0)) / cut
    high_mean = sum((item[1] for item in kept[-cut:]), Decimal(0)) / cut
    return high_mean - low_mean
