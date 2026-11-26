"""PostgreSQL 朝阳永续盈利预测调整窄读取。可见性来自契约，``entrytime`` 是截止列。

与财报三表（``fundamental.py``）的差别：本表的事件时间 ``current_create_date`` 与可见时间
``entrytime`` 是两个字段。SQL 只按 ``entrytime`` 做可见性截止与读取范围（``entrytime >=
current_create_date`` 恒成立，按 entrytime 读取必覆盖所有业务窗口行）；``current_create_date``
的业务窗口裁剪在使用方（``features.library.fundamental.nap_adj_ratio``）做，因为截面日历史行
还须再按 ``entrytime <= 观察日`` 过滤，端口无法预知观察日。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import InvalidQueryError, MissingVisibilityError
from quantagent.domain.fundamental.types import EarningsAdjustRecord
from quantagent.domain.pit.solve import pit_cutoff
from quantagent.domain.prices.select import normalize_wind_codes

if TYPE_CHECKING:
    from collections.abc import Mapping

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

DATASET = "src.suntime.rpt_earnings_adjust"


def load_adjust_visibility() -> VisibilityContract:
    vis = load_bundle().visibilities.get(DATASET)
    if vis is None:
        raise MissingVisibilityError(DATASET)
    return vis


class PostgresEarningsAdjustRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = contract if contract is not None else load_adjust_visibility()

    def list_adjustments(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[EarningsAdjustRecord, ...]:
        """``entrytime ∈ [start, min(end, as_of)]`` 且代码在域内的行，按代码与入库时间升序。

        ``start`` 由调用方给足回退（截面日最早窗口起点再减 30 天），保证覆盖所有观察日的
        业务窗口。可见截止 ``min(end, as_of)`` 由契约 ``entrytime`` 字段驱动。
        """
        codes = normalize_wind_codes(wind_codes)
        if codes is None:
            return ()
        if start > end:
            raise InvalidQueryError("start 晚于 end")
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        visible_end = min(end, cutoff.on_or_before)
        if start > visible_end:
            return ()
        # 把 Wind 格式代码转回裸 6 位与源表 stock_code 匹配；同时保留后缀映射以便回填。
        bare_by_wind = {_bare(code): code for code in codes}
        statement = (
            f"SELECT {quote_ident('stock_code')}, {quote_ident('current_create_date')},"
            f" {quote_ident('entrytime')}, {quote_ident('report_year')}, {quote_ident('np_adjust_rate')}"
            f" FROM {quote_ident('src_suntime')}.{quote_ident('rpt_earnings_adjust')}"
            f" WHERE {quote_ident('entrytime')}::date BETWEEN %s AND %s"
            f" AND {quote_ident('stock_code')} = ANY(%s)"
            f" ORDER BY {quote_ident('stock_code')}, {quote_ident('entrytime')}"
        )
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                assert_src_dml_sql(statement),
                (start.isoformat(), visible_end.isoformat(), list(bare_by_wind)),
            )
            fetched = cur.fetchall()
        rows: list[EarningsAdjustRecord] = []
        for item in fetched:
            record = _record_from_mapping(item, bare_by_wind)
            if record is not None:
                rows.append(record)
        return tuple(rows)


def _bare(wind_code: str) -> str:
    """Wind 格式代码去掉交易所后缀，与源表裸 6 位匹配。"""
    return wind_code.split(".", 1)[0]


def _record_from_mapping(
    row: Mapping[str, object],
    bare_by_wind: Mapping[str, str],
) -> EarningsAdjustRecord | None:
    stock_code = row.get("stock_code")
    if not isinstance(stock_code, str) or not stock_code.strip():
        return None
    bare = stock_code.strip()
    wind_code = bare_by_wind.get(bare)
    if wind_code is None:
        # 裸代码不在请求域内（如 B 股被过滤前），跳过。
        return None
    create_dt = row.get("current_create_date")
    entrytime = row.get("entrytime")
    if not isinstance(create_dt, date) or entrytime is None:
        # 事件时间或可见时间缺失即不可参与 PIT 计算，跳过（fail-closed 由面板对空域负责）。
        return None
    if isinstance(entrytime, datetime):
        entry_dt: date = entrytime.date()
    elif isinstance(entrytime, date):
        entry_dt = entrytime
    else:
        return None
    report_year = row.get("report_year")
    np_adjust_rate = row.get("np_adjust_rate")
    return EarningsAdjustRecord(
        asset_id=wind_code,
        create_dt=create_dt,
        entry_dt=entry_dt,
        report_year=int(report_year) if isinstance(report_year, (int, float)) else None,
        np_adjust_rate=Decimal(str(np_adjust_rate)) if np_adjust_rate is not None else None,
    )
