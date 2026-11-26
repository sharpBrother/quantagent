"""PostgreSQL 朝阳永续利润表（``fin_income_gen``）窄读取。可见性来自契约，``declare_date`` 是截止列。

只服务于事件因子的历史利润序列重构。与 ``suntime_adjust`` 的差别：本表事件时间与可见时间
同为 ``declare_date``（财报入库及时，负责人 2026-11-26 裁定统一用 declare_date，grade A），
没有单独的 entrytime 截止列。

读取口径（复现旧仓 ``event_sue`` 历史序列 SQL）：

- ``report_type in (1001,1003)``（合并期末/合并期末_调整，负责人 2026-11-26 提供字典）；
- ``declare_date <= as_of``（可见截止，由契约驱动）；
- ``report_year`` 下界与 ``period`` 上界由调用方按当期事件推导（端口不预知事件报告期，
  批量读取时给足范围，逐事件的 ``period < 当期`` 裁剪在使用方做）。

利润单位元，**不在端口换算**——库函数复现旧代码 ÷10000 的时机，保证逐位一致。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import MissingVisibilityError
from quantagent.domain.fundamental.types import ProfitSeriesRecord
from quantagent.domain.pit.solve import pit_cutoff
from quantagent.domain.prices.select import normalize_wind_codes

if TYPE_CHECKING:
    from collections.abc import Mapping

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

DATASET = "src.suntime.fin_income_gen"

# 合并口径报表类型：1001 合并期末、1003 合并期末_调整（负责人 2026-11-26 字典）。
# 1002/1004 母公司口径不进入事件因子利润序列。
MERGED_REPORT_TYPES = (1001, 1003)


def load_income_gen_visibility() -> VisibilityContract:
    vis = load_bundle().visibilities.get(DATASET)
    if vis is None:
        raise MissingVisibilityError(DATASET)
    return vis


class PostgresIncomeGenRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = contract if contract is not None else load_income_gen_visibility()

    def list_profit_series(
        self,
        *,
        as_of: date,
        min_report_year: int,
        max_period: int,
        wind_codes: tuple[str, ...],
    ) -> tuple[ProfitSeriesRecord, ...]:
        """``report_type in (1001,1003)``、``declare_date <= as_of``、``report_year >= min_report_year``、
        ``report_year*10000+report_quarter <= max_period`` 且代码在域内的行，按代码与期间升序。

        ``max_period`` 是批量读取的 period 上界（``report_year*10000+report_quarter``）。逐事件还要求
        ``period < 当期 event period``，那一步在使用方按事件裁剪——端口批量给足范围即可。
        """
        codes = normalize_wind_codes(wind_codes)
        if codes is None:
            return ()
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        visible_end = cutoff.on_or_before
        bare_by_wind = {_bare(code): code for code in codes}
        if not bare_by_wind:
            return ()
        statement = (
            f"SELECT {quote_ident('stock_code')}, {quote_ident('report_year')},"
            f" {quote_ident('report_quarter')}, {quote_ident('report_type')},"
            f" {quote_ident('declare_date')}, {quote_ident('np_shareholder')}"
            f" FROM {quote_ident('src_suntime')}.{quote_ident('fin_income_gen')}"
            f" WHERE {quote_ident('report_type')} = ANY(%s)"
            f" AND {quote_ident('declare_date')}::date <= %s"
            f" AND {quote_ident('report_year')} >= %s"
            f" AND {quote_ident('report_year')} * 10000 + {quote_ident('report_quarter')} <= %s"
            f" AND {quote_ident('stock_code')} = ANY(%s)"
            f" ORDER BY {quote_ident('stock_code')}, {quote_ident('report_year')},"
            f" {quote_ident('report_quarter')}, {quote_ident('report_type')}"
        )
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                assert_src_dml_sql(statement),
                (
                    list(MERGED_REPORT_TYPES),
                    visible_end.isoformat(),
                    min_report_year,
                    max_period,
                    list(bare_by_wind),
                ),
            )
            fetched = cur.fetchall()
        rows: list[ProfitSeriesRecord] = []
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
) -> ProfitSeriesRecord | None:
    stock_code = row.get("stock_code")
    if not isinstance(stock_code, str) or not stock_code.strip():
        return None
    bare = stock_code.strip()
    wind_code = bare_by_wind.get(bare)
    if wind_code is None:
        return None
    declare_date = row.get("declare_date")
    if isinstance(declare_date, datetime):
        declare_dt: date = declare_date.date()
    elif isinstance(declare_date, date):
        declare_dt = declare_date
    else:
        # declare_date 是可见截止列，缺失即不可参与 PIT，跳过。
        return None
    report_year = row.get("report_year")
    report_quarter = row.get("report_quarter")
    report_type = row.get("report_type")
    if not (
        isinstance(report_year, (int, float))
        and isinstance(report_quarter, (int, float))
        and isinstance(report_type, (int, float))
    ):
        return None
    np_shareholder = row.get("np_shareholder")
    return ProfitSeriesRecord(
        asset_id=wind_code,
        report_year=int(report_year),
        report_quarter=int(report_quarter),
        report_type=int(report_type),
        declare_dt=declare_dt,
        np_shareholder=Decimal(str(np_shareholder)) if np_shareholder is not None else None,
    )
