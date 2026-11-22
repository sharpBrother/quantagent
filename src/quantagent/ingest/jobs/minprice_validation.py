"""分钟源数据日分区校验及与写法无关的内容摘要。"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from quantagent.ingest.errors import SourceFetchError

if TYPE_CHECKING:
    from datetime import date

_COLUMNS = ("ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount")
_MORNING_START = 9 * 60 + 30
_MORNING_END = 11 * 60 + 30
_AFTERNOON_START = 13 * 60 + 1
_AFTERNOON_END = 15 * 60
_OPEN_LOW_TOLERANCE = pa.scalar(Decimal("0.005"), type=pa.decimal128(4, 3))


def validate_day(table: pa.Table, *, trade_date: date) -> pa.Table:  # noqa: PLR0912
    """保留源数值及类型；缺失、非法时间、重复键和不合理价格均拒绝。"""
    if table.num_rows == 0 or tuple(table.column_names) != _COLUMNS:
        raise SourceFetchError("分钟行情为空或源字段不匹配")
    if any(table.column(name).null_count for name in _COLUMNS):
        raise SourceFetchError("分钟行情存在空字段")
    table = table.combine_chunks().sort_by([("ts_code", "ascending"), ("trade_time", "ascending")])
    codes = table["ts_code"].combine_chunks()
    stamps = table["trade_time"].combine_chunks()
    if not pa.types.is_string(codes.type) or stamps.type != pa.timestamp("us"):
        raise SourceFetchError("分钟行情代码或时间类型不符")
    if (
        pc.any(pc.equal(pc.utf8_length(pc.utf8_trim_whitespace(codes)), 0)).as_py()
        or not pc.all(
            pc.equal(pc.cast(stamps, pa.date32()), pa.scalar(trade_date, type=pa.date32()))
        ).as_py()
    ):
        raise SourceFetchError("分钟行情代码为空或交易日期不符")
    minute = pc.add(pc.multiply(pc.hour(stamps), 60), pc.minute(stamps))
    morning = pc.and_(pc.greater_equal(minute, _MORNING_START), pc.less_equal(minute, _MORNING_END))
    afternoon = pc.and_(
        pc.greater_equal(minute, _AFTERNOON_START), pc.less_equal(minute, _AFTERNOON_END)
    )
    if (
        not pc.all(pc.or_(morning, afternoon)).as_py()
        or pc.any(
            pc.or_(pc.not_equal(pc.second(stamps), 0), pc.not_equal(pc.microsecond(stamps), 0))
        ).as_py()
    ):
        raise SourceFetchError("分钟行情时间不在交易时段")
    if (
        table.num_rows > 1
        and pc.any(
            pc.and_(
                pc.equal(codes.slice(1), codes.slice(0, table.num_rows - 1)),
                pc.equal(stamps.slice(1), stamps.slice(0, table.num_rows - 1)),
            )
        ).as_py()
    ):
        raise SourceFetchError("分钟行情存在重复键")
    for name in ("open", "high", "low", "close", "vol", "amount"):
        values = table[name]
        if values.type != pa.decimal128(20, 4):
            raise SourceFetchError(f"分钟行情字段精度不符 decimal(20,4): {name}")
        zero = pa.scalar(0, type=values.type)
        valid = (
            pc.greater(values, zero) if name in _COLUMNS[2:6] else pc.greater_equal(values, zero)
        )
        if not pc.all(valid).as_py():
            raise SourceFetchError(f"分钟行情字段值非法: {name}")
    # 源端偶有开盘价低于最低价；负责人允许不超过最低价 0.5% 的差异，源值不修正。
    open_gap = pc.subtract(table["low"], table["open"])
    allowed_gap = pc.multiply(table["low"], _OPEN_LOW_TOLERANCE)
    if not pc.all(pc.less_equal(open_gap, allowed_gap)).as_py():
        raise SourceFetchError("分钟行情开盘价低于最低价超过 0.5%")
    for name in ("close", "high"):
        if not pc.all(pc.less_equal(table["low"], table[name])).as_py():
            raise SourceFetchError("分钟行情最低价高于其他价格")
    for name in ("open", "close"):
        if not pc.all(pc.less_equal(table[name], table["high"])).as_py():
            raise SourceFetchError("分钟行情最高价低于开盘或收盘价")
    return table.append_column(
        "trade_date", pa.array([trade_date] * table.num_rows, type=pa.date32())
    )


def content_digest(table: pa.Table) -> str:
    """排序及合并分块后固定 Arrow IPC，避免批次边界改变摘要。"""
    canonical = table.combine_chunks().sort_by(
        [("ts_code", "ascending"), ("trade_time", "ascending")]
    )
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, canonical.schema) as writer:
        writer.write_table(canonical, max_chunksize=120_000)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()
