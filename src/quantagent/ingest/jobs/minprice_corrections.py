"""负责人明确裁定的单条历史源数据修正。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from quantagent.ingest.errors import SourceFetchError
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from quantagent.domain.ports.prices import DailyPriceRepository

# 逐条确认过的记录仍需精确匹配，以免源端修订后悄悄套用旧决定。
_CORRECTIONS = {
    date(2025, 10, 28): ("920014.BJ", Decimal("-1"), Decimal("-21")),
    date(2025, 11, 26): ("600289.SH", Decimal("0"), Decimal("-43")),
    date(2025, 12, 8): ("920260.BJ", Decimal("0"), Decimal("-3")),
    date(2025, 12, 11): ("600165.SH", Decimal("0"), Decimal("-56")),
    date(2025, 12, 29): ("002898.SZ", Decimal("0"), Decimal("-94")),
}
_MAX_DAILY_NEGATIVE_AMOUNTS = 10
_APPROVED_DATE = date(2025, 10, 17)
_APPROVED_COUNT = 45
_APPROVED_FINGERPRINT = "72a22991d69043d1433990eac7e89ff78b58dbfea4f249a8f595fb0836039c51"
_JANUARY_DATE = date(2026, 1, 13)
_JANUARY_COUNT = 75
_JANUARY_FINGERPRINT = "b99d14d4bb77527b6a275bb25ffcebdd4be1c8afaa060ea472fcedd1de9a7831"


def _negative_rows_fingerprint(table: pa.Table) -> str:
    """固定代码、时间和全部数值列，防止源数据变化后沿用原裁定。"""
    rows = table.sort_by([("ts_code", "ascending"), ("trade_time", "ascending")]).to_pylist()
    return digest_json(
        [
            [
                item["ts_code"],
                item["trade_time"].isoformat(sep=" "),
                *[
                    f"{item[name]:.4f}"
                    for name in ("open", "high", "low", "close", "vol", "amount")
                ],
            ]
            for item in rows
        ]
    )


def correct_known_row(
    table: pa.Table, *, trade_date: date, is_mysql: bool
) -> tuple[pa.Table, list[dict[str, str]]]:
    """MySQL 负成交额每日不超过 10 条时保留原值记录并置零；其他异常照常阻断。"""
    if not is_mysql:
        return table, []
    negative_mask = pc.less(table["amount"], pa.scalar(0, type=table["amount"].type))
    negatives = table.filter(negative_mask)
    if trade_date == _APPROVED_DATE:
        if (
            negatives.num_rows != _APPROVED_COUNT
            or _negative_rows_fingerprint(negatives) != _APPROVED_FINGERPRINT
        ):
            raise SourceFetchError("2025-10-17 负成交额记录与已确认的 45 条不一致")
        return _correct_negative_amounts(table, negative_mask, negatives)
    if trade_date == _JANUARY_DATE:
        if (
            negatives.num_rows != _JANUARY_COUNT
            or _negative_rows_fingerprint(negatives) != _JANUARY_FINGERPRINT
        ):
            raise SourceFetchError("2026-01-13 负成交额记录与已确认的 75 条不一致")
        return _correct_negative_amounts(table, negative_mask, negatives)
    if negatives.num_rows > _MAX_DAILY_NEGATIVE_AMOUNTS:
        raise SourceFetchError("负成交额超过每日 10 条上限，拒绝自动修正")
    if trade_date not in _CORRECTIONS:
        return _correct_negative_amounts(table, negative_mask, negatives)
    code, volume, amount = _CORRECTIONS[trade_date]
    timestamp = datetime.combine(trade_date, datetime.min.time()).replace(hour=15)
    expected = {"vol": volume, "amount": amount}
    mask = pc.and_(pc.equal(table["ts_code"], code), pc.equal(table["trade_time"], timestamp))
    matches = table.filter(mask).select(["vol", "amount"]).to_pylist()
    if len(matches) != 1 or matches[0] != expected:
        raise SourceFetchError("指定修正记录不存在、重复或原值已变化，拒绝自动修正")
    details = [
        {
            "ts_code": code,
            "trade_time": timestamp.isoformat(sep=" "),
            "vol_before": f"{volume:.4f}",
            "vol_after": "0.0000",
            "amount_before": f"{amount:.4f}",
            "amount_after": "0.0000",
        }
    ]
    for name in ("vol", "amount") if volume < 0 else ("amount",):
        index = table.schema.get_field_index(name)
        column = table[name]
        corrected = pc.if_else(mask, pa.scalar(0, type=column.type), column)
        table = table.set_column(index, name, corrected)
    remaining_mask = pc.less(table["amount"], pa.scalar(0, type=table["amount"].type))
    table, other_details = _correct_negative_amounts(
        table, remaining_mask, table.filter(remaining_mask)
    )
    return table, details + other_details


def _correct_negative_amounts(
    table: pa.Table, mask: pa.ChunkedArray, negatives: pa.Table
) -> tuple[pa.Table, list[dict[str, str]]]:
    if negatives.num_rows == 0:
        return table, []
    rows = negatives.select(["ts_code", "trade_time", "vol", "amount"]).to_pylist()
    details = [
        {
            "ts_code": item["ts_code"],
            "trade_time": item["trade_time"].isoformat(sep=" "),
            "vol_before": f"{item['vol']:.4f}",
            "vol_after": f"{item['vol']:.4f}",
            "amount_before": f"{item['amount']:.4f}",
            "amount_after": "0.0000",
        }
        for item in rows
    ]
    index = table.schema.get_field_index("amount")
    column = table["amount"]
    corrected = pc.if_else(mask, pa.scalar(0, type=column.type), column)
    return table.set_column(index, "amount", corrected), details


def reconcile_negative_amounts(
    table: pa.Table, *, trade_date: date, prices: DailyPriceRepository
) -> tuple[pa.Table, list[dict[str, str]], list[str], list[dict[str, str]]]:
    """逐股票与日成交额比较；日行情缺失和差异不达标均排除整只股票。"""
    mask = pc.less(table["amount"], 0)
    negatives = table.filter(mask)
    if not negatives.num_rows:
        return table, [], [], []
    codes = sorted(set(negatives["ts_code"].to_pylist()))
    # 通过现有日行情端口获取同日可见数据，Wind 成交额单位为千元。
    daily = prices.list_prices(
        as_of=trade_date, start=trade_date, end=trade_date, wind_codes=tuple(codes)
    )
    amounts = {item.wind_code: item.amount * 1000 for item in daily if item.amount is not None}
    subset = table.filter(pc.is_in(table["ts_code"], value_set=pa.array(codes)))
    zeroed = pc.if_else(
        pc.less(subset["amount"], 0), pa.scalar(0, type=subset["amount"].type), subset["amount"]
    )
    subset = subset.set_column(subset.schema.get_field_index("amount"), "amount", zeroed)
    totals = {
        row["ts_code"]: row["amount_sum"]
        for row in subset.group_by("ts_code").aggregate([("amount", "sum")]).to_pylist()
    }
    decisions = []
    excluded = []
    for code in codes:
        day_amount = amounts.get(code)
        minute_amount = totals[code]
        valid = (
            day_amount is not None
            and day_amount > 0
            and abs(minute_amount - day_amount) * 200 < day_amount
        )
        if not valid:
            excluded.append(code)
        decisions.append(
            {
                "ts_code": code,
                "minute_amount_yuan": str(minute_amount),
                "daily_amount_yuan": str(day_amount) if day_amount is not None else "",
                "decision": "correct" if valid else "exclude",
            }
        )
    if excluded:
        table = table.filter(pc.invert(pc.is_in(table["ts_code"], value_set=pa.array(excluded))))
    mask = pc.less(table["amount"], 0)
    table, corrected = _correct_negative_amounts(table, mask, table.filter(mask))
    return table, corrected, excluded, decisions
