"""组装资金流因子物化：读日历、股票池、行情、资金流、指数收益，计算，写长表。业务规则不在这里。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.adapters.postgres.index_returns import (
    PostgresIndexReturnRepository,
    load_index_visibility,
)
from quantagent.adapters.postgres.money_flow import (
    PostgresMoneyFlowRepository,
    load_money_flow_visibility,
)
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.domain.calendar import open_dates
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID
from quantagent.features.library.money_flow.abso_umr import LOOKBACK
from quantagent.features.library.price.tr_umr import BENCHMARK
from quantagent.features.panel.money_flow import build_money_flow_factor_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    import psycopg

    from quantagent.domain.feature_value import FeatureValue
    from quantagent.domain.index_returns.types import IndexReturn
    from quantagent.domain.money_flow.types import MoneyFlow
    from quantagent.domain.prices.types import DailyPrice
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.moneyflow_factors"
_EXCHANGE = "SSE"
# 日历往前取 240 个自然日，覆盖第一个截面日之前的 68 个开市日。
_CALENDAR_PAD_DAYS = 240
# 个股自有 20 行的窗口：按自然日估计，取 120 天以覆盖停牌等造成的空档。
_OWN_ROW_PAD_DAYS = 120


def materialize_moneyflow_factors(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    wind_codes: tuple[str, ...] | None,
    as_of: date,
) -> tuple[int, str]:
    """``wind_codes`` 为 None 时，按每个截面日取 all_a 成员：读取范围取区间内各截面日成员的并集，
    输出只保留截面日当天属于 all_a 的行。不用 ``end`` 日成员回填整个区间，否则区间中途退出 all_a 的股票
    会丢掉退出前的截面，造成幸存者偏差。口径与分钟因子（``minute_factors_materialize._universe_at``）一致。
    """
    started = datetime.now(UTC)
    dest = paths.lake / "feature" / "value"
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    try:
        days = LakeCalendarRepository(paths.lake / "std" / "trade_calendar").list_days(
            as_of=as_of,
            exchange=_EXCHANGE,
            start=start - timedelta(days=_CALENDAR_PAD_DAYS),
            end=end,
        )
        opens = open_dates(days)
        events = tuple(day for day in opens if start <= day <= end)
        conn = connect(settings, "src")
        try:
            members_by_day: dict[date, frozenset[str]] | None = None
            if wind_codes is None:
                members_by_day = _all_a_members_by_day(conn, as_of=as_of, days=events)
                codes = union_codes(members_by_day)
            else:
                codes = wind_codes
            prices, money_flows, index_returns = read_moneyflow_inputs(
                conn,
                as_of=as_of,
                opens=opens,
                start=start,
                end=end,
                codes=codes,
            )
        finally:
            conn.close()
        rows = build_money_flow_factor_values(
            prices,
            money_flows,
            index_returns,
            opens,
            price_contract=load_price_visibility(),
            money_flow_contract=load_money_flow_visibility(),
            index_contract=load_index_visibility(),
            start=start,
            end=end,
            computed_at=computed_at,
            run_id=run_id,
        )
        if members_by_day is not None:
            rows = keep_rows_in_membership(rows, members_by_day)
        write_feature_values(rows, dest)
    except Exception as exc:
        _log(
            paths=paths,
            started=started,
            start=start,
            end=end,
            as_of=as_of,
            wind_codes=wind_codes,
            run_id=run_id,
            status="failure",
            error=str(exc),
        )
        raise
    digest = digest_json(
        [
            {
                "feature_id": row.feature_id,
                "event_dt": row.event_dt.isoformat(),
                "asset_id": row.asset_id,
                "value": row.value,
                "knowledge_dt": row.knowledge_dt.isoformat(),
                "pit_grade": row.pit_grade,
            }
            for row in rows
        ]
    )
    _log(
        paths=paths,
        started=started,
        start=start,
        end=end,
        as_of=as_of,
        wind_codes=wind_codes,
        run_id=run_id,
        status="success",
        row_count=len(rows),
        output_digest=digest,
        dml_count=0,
    )
    return len(rows), digest


def read_moneyflow_inputs(
    conn: psycopg.Connection[object],
    *,
    as_of: date,
    opens: Sequence[date],
    start: date,
    end: date,
    codes: tuple[str, ...],
) -> tuple[tuple[DailyPrice, ...], tuple[MoneyFlow, ...], tuple[IndexReturn, ...]]:
    """按截面区间读取行情、资金流、基准指数。读取起点由 ``read_start`` 决定。"""
    read_start = read_start_for(opens, start=start, end=end)
    prices = PostgresDailyPriceRepository(conn).list_prices(
        as_of=as_of,
        start=read_start,
        end=end,
        wind_codes=codes,
    )
    money_flows = PostgresMoneyFlowRepository(conn).list_money_flows(
        as_of=as_of,
        start=read_start,
        end=end,
        wind_codes=codes,
    )
    index_returns = PostgresIndexReturnRepository(conn).list_returns(
        as_of=as_of,
        start=read_start,
        end=end,
        wind_codes=(BENCHMARK,),
    )
    return prices, money_flows, index_returns


def _all_a_members_by_day(
    conn: psycopg.Connection[object], *, as_of: date, days: Sequence[date]
) -> dict[date, frozenset[str]]:
    repo = PostgresUniverseRepository(conn)
    return {
        day: frozenset(
            member.asset_id
            for member in repo.members_at(as_of=as_of, dt=day, universe_id=ALL_A_UNIVERSE_ID)
        )
        for day in days
    }


def union_codes(members_by_day: Mapping[date, frozenset[str]]) -> tuple[str, ...]:
    """区间内各截面日 all_a 成员的并集，升序。只决定读哪些股票，不决定产出哪些行。"""
    merged: set[str] = set()
    for members in members_by_day.values():
        merged |= members
    return tuple(sorted(merged))


def keep_rows_in_membership(
    rows: Sequence[FeatureValue], members_by_day: Mapping[date, frozenset[str]]
) -> tuple[FeatureValue, ...]:
    """只保留截面日当天属于 all_a 的行。截面日不在映射里的行一律丢弃（fail-closed）。"""
    return tuple(
        row for row in rows if row.asset_id in members_by_day.get(row.event_dt, frozenset())
    )


def read_start_for(open_days: Sequence[date], *, start: date, end: date) -> date:
    """读取起点取两者的较早者：第一个截面开市日前 68 个开市日，以及截面起点前 120 个自然日。"""
    ordered = tuple(sorted(open_days))
    events = [day for day in ordered if start <= day <= end]
    own_row_start = start - timedelta(days=_OWN_ROW_PAD_DAYS)
    if not events:
        return own_row_start
    first = ordered.index(events[0])
    calendar_start = ordered[max(0, first - (LOOKBACK - 1))]
    return min(calendar_start, own_row_start)


def _log(
    *,
    paths: VarPaths,
    started: datetime,
    start: date,
    end: date,
    as_of: date,
    wind_codes: tuple[str, ...] | None,
    run_id: str,
    status: Literal["success", "failure"],
    row_count: int | None = None,
    output_digest: str | None = None,
    dml_count: int = 0,
    error: str | None = None,
) -> None:
    finished = datetime.now(UTC)
    record = RunLog(
        run_id=run_id,
        action=ACTION,
        status=status,
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "as_of": as_of.isoformat(),
                "wind_codes": None if wind_codes is None else list(wind_codes),
            }
        ),
        output_digest=output_digest,
        row_count=row_count,
        dml_count=dml_count,
        error=error,
    )
    persist_run_log(record, paths)
