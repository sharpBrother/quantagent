"""PostgreSQL 朝阳永续业绩公告事件候选窄读取（业绩预告/快报/正式财报三源）。

复现旧仓 ``FactorEvent.__init__`` 的三源读取（行号见 event-factors-handoff.md §2）。口径要点：

- **不过滤 ``is_valid``、不去重 ``sequence``**：旧仓原样读取全量镜像行，作废公告与修订行
  都进入候选。事件去重靠下游"同事件键先到先得"机制，不在端口做。golden 先固化旧行为，
  is_valid 口径差异单列登记（若有），不顺手修正。
- income 源（正式财报）``report_type = 1001``（仅合并期末，**不含** 1003 调整版）——与历史
  利润序列的 ``in (1001,1003)`` 不同，是旧代码的有意区分，不可统一。
- 可见性截止 ``declare_date <= as_of``（三源契约统一 declare_date，grade A）。
- profit 单位换算：income 源 ``np_shareholder`` 元 ÷10000 转万；forecast ``np_floor``/express ``np``
  源端即万元，不换算（实证比值恒 ≈1e4，见 event-factors-handoff.md §5）。
- ``report_quarter`` 统一为 1001-1004：forecast/express 源端 ``report_period`` 是 1-4，端口映射为
  1001-1004；income 源端 ``report_quarter`` 本就是 1001-1004。

sources 顺序固定为 forecast → income → express（与旧仓 ``process_event`` 遍历顺序一致，
决定同事件键的先到先得）。
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
from quantagent.domain.fundamental.types import EarningsEventRecord
from quantagent.domain.pit.solve import pit_cutoff
from quantagent.domain.prices.select import normalize_wind_codes

if TYPE_CHECKING:
    from collections.abc import Mapping

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

FORECAST_DATASET = "src.suntime.fin_performance_forecast"
EXPRESS_DATASET = "src.suntime.fin_performance_express"
INCOME_DATASET = "src.suntime.fin_income_gen"

# income 源事件候选只取合并期末（1001），不含调整版（1003）。旧代码 report_type = 1001。
_INCOME_EVENT_REPORT_TYPE = 1001
# 元转万。
_YUAN_TO_WAN = 10000.0
# forecast/express 的 report_period(1-4) 到 quarter(1001-1004) 的映射。
_PERIOD_TO_QUARTER = {1: 1001, 2: 1002, 3: 1003, 4: 1004}


def _load_visibility(dataset: str) -> VisibilityContract:
    vis = load_bundle().visibilities.get(dataset)
    if vis is None:
        raise MissingVisibilityError(dataset)
    return vis


def load_forecast_visibility() -> VisibilityContract:
    return _load_visibility(FORECAST_DATASET)


def load_express_visibility() -> VisibilityContract:
    return _load_visibility(EXPRESS_DATASET)


def load_income_event_visibility() -> VisibilityContract:
    return _load_visibility(INCOME_DATASET)


class PostgresEarningsEventRepository:
    """三源事件候选读取。每次调用按来源分别查询，调用方按 forecast → income → express 合并。"""

    def __init__(self, conn: psycopg.Connection[object]) -> None:
        self._conn = conn

    def _visible_end(self, dataset: str, as_of: date) -> date:
        return pit_cutoff(_load_visibility(dataset), as_of=as_of).on_or_before

    def list_events(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[EarningsEventRecord, ...]:
        """三源 ``declare_date ∈ [start, min(end, as_of)]`` 且代码在域内的事件候选，按 declare_date 升序。

        返回已按 forecast → income → express 优先级排序（同源内按 declare_date），供使用方
        按事件键先到先得去重。``start``/``end`` 是事件公告日窗口（物化的起止）。
        """
        codes = normalize_wind_codes(wind_codes)
        if codes is None:
            return ()
        bare_by_wind = {_bare(code): code for code in codes}
        if not bare_by_wind:
            return ()
        events: list[EarningsEventRecord] = []
        events += self._forecast_events(
            as_of=as_of, start=start, end=end, bare_by_wind=bare_by_wind
        )
        events += self._income_events(as_of=as_of, start=start, end=end, bare_by_wind=bare_by_wind)
        events += self._express_events(
            as_of=as_of, start=start, end=end, bare_by_wind=bare_by_wind
        )
        return tuple(events)

    def _window(self, dataset: str, as_of: date, start: date, end: date) -> tuple[date, date] | None:
        visible_end = min(end, self._visible_end(dataset, as_of))
        if start > visible_end:
            return None
        return start, visible_end

    def _fetch(
        self, statement: str, params: tuple[object, ...]
    ) -> list[Mapping[str, object]]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(assert_src_dml_sql(statement), params)
            return list(cur.fetchall())

    def _forecast_events(
        self, *, as_of: date, start: date, end: date, bare_by_wind: Mapping[str, str]
    ) -> list[EarningsEventRecord]:
        window = self._window(FORECAST_DATASET, as_of, start, end)
        if window is None:
            return []
        lo, hi = window
        statement = (
            f"SELECT {quote_ident('stock_code')}, {quote_ident('report_year')},"
            f" {quote_ident('report_period')}, {quote_ident('declare_date')}, {quote_ident('entrytime')},"
            f" {quote_ident('np_floor')}"
            f" FROM {quote_ident('src_suntime')}.{quote_ident('fin_performance_forecast')}"
            f" WHERE {quote_ident('declare_date')}::date BETWEEN %s AND %s"
            f" AND {quote_ident('stock_code')} = ANY(%s)"
            f" ORDER BY {quote_ident('declare_date')}"
        )
        rows = self._fetch(statement, (lo.isoformat(), hi.isoformat(), list(bare_by_wind)))
        out: list[EarningsEventRecord] = []
        for item in rows:
            rec = _event_from_mapping(
                item,
                bare_by_wind,
                profit_col="np_floor",
                profit_scale=1.0,  # forecast.np_floor 源端即万元
                source="forecast",
                period_is_quarter=False,
            )
            if rec is not None:
                out.append(rec)
        return out

    def _income_events(
        self, *, as_of: date, start: date, end: date, bare_by_wind: Mapping[str, str]
    ) -> list[EarningsEventRecord]:
        window = self._window(INCOME_DATASET, as_of, start, end)
        if window is None:
            return []
        lo, hi = window
        statement = (
            f"SELECT {quote_ident('stock_code')}, {quote_ident('report_year')},"
            f" {quote_ident('report_quarter')}, {quote_ident('declare_date')}, {quote_ident('entrytime')},"
            f" {quote_ident('np_shareholder')}"
            f" FROM {quote_ident('src_suntime')}.{quote_ident('fin_income_gen')}"
            f" WHERE {quote_ident('declare_date')}::date BETWEEN %s AND %s"
            f" AND {quote_ident('report_type')} = %s"
            f" AND {quote_ident('stock_code')} = ANY(%s)"
            f" ORDER BY {quote_ident('declare_date')}"
        )
        rows = self._fetch(
            statement,
            (lo.isoformat(), hi.isoformat(), _INCOME_EVENT_REPORT_TYPE, list(bare_by_wind)),
        )
        out: list[EarningsEventRecord] = []
        for item in rows:
            rec = _event_from_mapping(
                item,
                bare_by_wind,
                profit_col="np_shareholder",
                profit_scale=_YUAN_TO_WAN,  # income.np_shareholder 元 ÷10000 转万
                source="income",
                period_is_quarter=True,
            )
            if rec is not None:
                out.append(rec)
        return out

    def _express_events(
        self, *, as_of: date, start: date, end: date, bare_by_wind: Mapping[str, str]
    ) -> list[EarningsEventRecord]:
        window = self._window(EXPRESS_DATASET, as_of, start, end)
        if window is None:
            return []
        lo, hi = window
        statement = (
            f"SELECT {quote_ident('stock_code')}, {quote_ident('report_year')},"
            f" {quote_ident('report_period')}, {quote_ident('declare_date')}, {quote_ident('entrytime')},"
            f" {quote_ident('np')}"
            f" FROM {quote_ident('src_suntime')}.{quote_ident('fin_performance_express')}"
            f" WHERE {quote_ident('declare_date')}::date BETWEEN %s AND %s"
            f" AND {quote_ident('stock_code')} = ANY(%s)"
            f" ORDER BY {quote_ident('declare_date')}"
        )
        rows = self._fetch(statement, (lo.isoformat(), hi.isoformat(), list(bare_by_wind)))
        out: list[EarningsEventRecord] = []
        for item in rows:
            rec = _event_from_mapping(
                item,
                bare_by_wind,
                profit_col="np",
                profit_scale=1.0,  # express.np 源端即万元
                source="express",
                period_is_quarter=False,
            )
            if rec is not None:
                out.append(rec)
        return out


def _bare(wind_code: str) -> str:
    return wind_code.split(".", 1)[0]


def _event_from_mapping(
    row: Mapping[str, object],
    bare_by_wind: Mapping[str, str],
    *,
    profit_col: str,
    profit_scale: float,
    source: str,
    period_is_quarter: bool,
) -> EarningsEventRecord | None:
    stock_code = row.get("stock_code")
    if not isinstance(stock_code, str) or not stock_code.strip():
        return None
    wind_code = bare_by_wind.get(stock_code.strip())
    if wind_code is None:
        return None
    declare_date = row.get("declare_date")
    if isinstance(declare_date, datetime):
        declare_dt: date = declare_date.date()
    elif isinstance(declare_date, date):
        declare_dt = declare_date
    else:
        return None
    report_year = row.get("report_year")
    # report_period/quarter 统一为 1001-1004。
    period_raw = row.get("report_quarter") if period_is_quarter else row.get("report_period")
    if not (isinstance(report_year, (int, float)) and isinstance(period_raw, (int, float))):
        return None
    if period_is_quarter:
        report_quarter: int | None = int(period_raw)
    else:
        report_quarter = _PERIOD_TO_QUARTER.get(int(period_raw))
    if report_quarter is None:
        return None
    profit_raw = row.get(profit_col)
    profit: Decimal | None = None
    if profit_raw is not None:
        scaled = Decimal(str(profit_raw)) / Decimal(str(profit_scale))
        profit = scaled
    entrytime = row.get("entrytime")
    if not isinstance(entrytime, datetime):
        entrytime = None
    return EarningsEventRecord(
        asset_id=wind_code,
        declare_dt=declare_dt,
        report_year=int(report_year),
        report_quarter=report_quarter,
        profit=profit,
        source=source,
        entrytime=entrytime,
    )
