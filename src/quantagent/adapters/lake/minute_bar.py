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


class LakeMinuteBarRepository:
    def __init__(self, conn: Any, root: Path, calendar: CalendarRepository) -> None:
        self._conn, self._root, self._calendar = conn, root.resolve(), calendar

    def scan_window(  # noqa: PLR0912
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
            target = (self._root / name).resolve()
            if not target.is_relative_to(self._root) or not target.is_file():
                raise ValueError(f"分钟分区文件路径无效: {day}")
            parquet_file = pq.ParquetFile(target)
            metadata = parquet_file.metadata.metadata or {}
            raw_exclusions = metadata.get(b"quantagent.excluded_codes")
            if raw_exclusions is not None:
                try:
                    excluded = json.loads(raw_exclusions)
                    if not isinstance(excluded, list) or not all(
                        isinstance(item, str) for item in excluded
                    ):
                        raise ValueError("invalid exclusion metadata")
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError(f"分钟分区排除清单无效: {day}") from exc
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
