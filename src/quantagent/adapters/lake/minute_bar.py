"""只读取 manifest 登记的分钟分区，缺日及 footer 不一致均停止。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq

from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import EmptyDomainError, MissingVisibilityError
from quantagent.domain.minute_exclusions import JANUARY_21, JANUARY_21_EXCLUDED
from quantagent.domain.pit import visible_event_on_or_before
from quantagent.platform.duck import duck_session

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from pathlib import Path

    import pyarrow as pa

    from quantagent.domain.ports.calendar import CalendarRepository

_DATASET = "src.minprice.ashare_minute_bar"
_COLUMNS = frozenset(
    {"ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount", "trade_date"}
)
# 排除清单写在分区 footer 的 key-value 元数据里，JSON 数组。2026-01-21 分区没有该键，
# 它的名单在 domain.minute_exclusions 中。
_EXCLUDED_KEY = b"quantagent.excluded_codes"


class LakeMinuteBarRepository:
    def __init__(self, conn: Any, root: Path, calendar: CalendarRepository) -> None:
        self._conn, self._root, self._calendar = conn, root.resolve(), calendar

    def excluded_codes(self, *, as_of: date, day: date) -> frozenset[str]:
        # 排除集是数据质量裁定，不是 PIT 信息，但读取仍受可见日约束：晚于 as_of 的日子不得查询。
        contract = load_bundle().visibilities.get(_DATASET)
        if contract is None:
            raise MissingVisibilityError(_DATASET)
        if day > visible_event_on_or_before(contract, as_of=as_of):
            raise EmptyDomainError(f"{day.isoformat()} 晚于分钟行情可见日，不能读取排除集")
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date,file_name,row_count FROM src_minprice.lake_partition "
                "WHERE dataset=%s AND trade_date=%s",
                ("ashare_minute_bar", day),
            )
            records = cur.fetchall()
        if len(records) != 1:
            raise EmptyDomainError(f"分钟行情 manifest 中 {day.isoformat()} 分区数不是 1")
        _, name, count = records[0]
        target = self._partition_file(day, name)
        parquet_file = pq.ParquetFile(target)
        if parquet_file.metadata.num_rows != count:
            raise ValueError(f"分钟分区 footer 行数不符: {day}")
        excluded = set(self._footer_exclusions(parquet_file, day))
        if day == JANUARY_21:
            excluded |= JANUARY_21_EXCLUDED
        return frozenset(excluded)

    def scan_window(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        codes: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pa.Table:
        if start > end:
            raise ValueError("start 晚于 end")
        contract = load_bundle().visibilities.get(_DATASET)
        if contract is None:
            raise MissingVisibilityError(_DATASET)
        end = min(end, visible_event_on_or_before(contract, as_of=as_of))
        if start > end:
            raise EmptyDomainError("截止日前没有分钟行情")
        days = self._calendar.list_days(as_of=as_of, exchange="SSE", start=start, end=end)
        expected = {d.cal_dt for d in days if d.is_open}
        if not expected:
            raise EmptyDomainError("所选区间没有交易日")
        names = list(columns) if columns is not None else sorted(_COLUMNS)
        if not names or len(set(names)) != len(names) or set(names) - _COLUMNS:
            raise ValueError("分钟行情读取列非法")
        if codes is not None and not codes:
            raise EmptyDomainError("证券代码列表为空")
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date,file_name,row_count FROM src_minprice.lake_partition "
                "WHERE dataset=%s AND trade_date BETWEEN %s AND %s ORDER BY trade_date",
                ("ashare_minute_bar", start, end),
            )
            records = cur.fetchall()
        if {record[0] for record in records} != expected:
            raise EmptyDomainError("分钟行情 manifest 缺失交易日或存在非交易日")
        # 此日有明确排除的股票，不能把整日视为完整或静默返回空数据。
        if JANUARY_21 in expected and (codes is None or JANUARY_21_EXCLUDED.intersection(codes)):
            raise EmptyDomainError("2026-01-21 分钟分区不含已排除股票，请明确选择其他代码")
        files = []
        for day, name, count in records:
            target = self._partition_file(day, name)
            parquet_file = pq.ParquetFile(target)
            excluded = self._footer_exclusions(parquet_file, day)
            if excluded and (codes is None or set(excluded).intersection(codes)):
                raise EmptyDomainError(f"{day} 分钟分区不含已排除股票，请明确选择其他代码")
            if parquet_file.metadata.num_rows != count:
                raise ValueError(f"分钟分区 footer 行数不符: {day}")
            files.append(str(target))
        projection = ", ".join(f'"{col}"' for col in names)
        query = f"SELECT {projection} FROM read_parquet(?, hive_partitioning=false)"
        params: list[Any] = [files]
        if codes is not None:
            query += " WHERE ts_code IN (SELECT unnest(?))"
            params.append(list(codes))
        with duck_session() as conn:
            return conn.execute(query, params).to_arrow_table()

    def _partition_file(self, day: date, name: str) -> Path:
        target = (self._root / name).resolve()
        if not target.is_relative_to(self._root) or not target.is_file():
            raise ValueError(f"分钟分区文件路径无效: {day}")
        return target

    @staticmethod
    def _footer_exclusions(parquet_file: pq.ParquetFile, day: date) -> list[str]:
        metadata = parquet_file.metadata.metadata or {}
        raw = metadata.get(_EXCLUDED_KEY)
        if raw is None:
            return []
        try:
            excluded = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"分钟分区排除清单无效: {day}") from exc
        if not isinstance(excluded, list) or not all(isinstance(item, str) for item in excluded):
            raise ValueError(f"分钟分区排除清单无效: {day}")
        return excluded
