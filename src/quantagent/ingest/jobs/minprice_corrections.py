"""负责人明确裁定的单条历史源数据修正。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pyarrow as pa
import pyarrow.compute as pc

from quantagent.ingest.errors import SourceFetchError

# 仅记录负责人逐条确认的日期、代码和原值；不存在通用负数置零规则。
_CORRECTIONS = {
    date(2025, 10, 28): ("920014.BJ", Decimal("-1"), Decimal("-21")),
    date(2025, 11, 26): ("600289.SH", Decimal("0"), Decimal("-43")),
    date(2025, 12, 8): ("920260.BJ", Decimal("0"), Decimal("-3")),
}


def correct_known_row(
    table: pa.Table, *, trade_date: date, is_mysql: bool
) -> tuple[pa.Table, list[dict[str, str]]]:
    """只修复已确认原值；源端变动时必须停止，不能泛化为负数填零。"""
    if not is_mysql or trade_date not in _CORRECTIONS:
        return table, []
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
    return table, details
