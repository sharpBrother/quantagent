"""组装 event_delta_roe 物化：读交易日历、股票域、三源事件候选、ROE、股东权益与利润序列，计算，写长表。业务规则不在这里。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.fundamental import (
    PostgresRoeRepository,
    PostgresShareholderEquityRepository,
)
from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.adapters.postgres.suntime_event import PostgresEarningsEventRepository
from quantagent.adapters.postgres.suntime_income_gen import PostgresIncomeGenRepository
from quantagent.cli._universe import all_a_members_by_day, union_codes
from quantagent.domain.calendar import open_dates
from quantagent.features.panel.event_delta_roe import build_event_delta_roe_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.lake.partitions import LakeLayoutError
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Mapping

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.event_delta_roe"
_EXCHANGE = "SSE"
# 日历/域向后宽限：非交易日 declare 后首个交易日可能落在 end 之后（同 event_sue）。
_DOMAIN_LOOKAHEAD_DAYS = 10
# 报告期回退年数：period 最远可上溯（Q1 last_period=前年Q4，period_ly=去年同期），
# 需覆盖 period_ly 与 last_period 的 ROE/eqt/profit。给足回退取 start 前 3 年（年报披露的
# period_ly/last_period 链最多前推 2 年），逐事件精确裁剪在 panel。
_PERIOD_LOOKBACK_YEARS = 3
# 披露期月份（剔除业绩修正期）。cli 统计本月有效候选以区分合法空/异常空，与 panel 同源。
_VALID_MONTHS = frozenset({1, 2, 3, 4, 7, 8, 10})


def materialize_event_delta_roe(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    wind_codes: tuple[str, ...] | None,
    as_of: date,
) -> tuple[int, str]:
    """返回 (行数, 输出 digest)。

    股票域：``wind_codes`` 为 None 时每个交易日取 all_a 成员去掉当日 ST。event_delta_roe 是
    事件驱动稀疏因子：``event_dt = declare_date``（不依赖行情），缺失不补 0。
    """
    started = datetime.now(UTC)
    dest = paths.lake / "feature" / "value"
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    try:
        cal_end = end + timedelta(days=_DOMAIN_LOOKAHEAD_DAYS)
        days = LakeCalendarRepository(paths.lake / "std" / "trade_calendar").list_days(
            as_of=as_of,
            exchange=_EXCHANGE,
            start=start,
            end=cal_end,
        )
        opens = open_dates(days)
        events_days = tuple(day for day in opens if start <= day <= cal_end)
        conn = connect(settings, "src")
        try:
            members_by_day: Mapping[date, frozenset[str]] | None = None
            if wind_codes is None:
                members_by_day = all_a_members_by_day(conn, as_of=as_of, days=events_days)
                codes = union_codes(members_by_day)
            else:
                codes = wind_codes
            st_repo = PostgresStStatusRepository(conn)
            domain_by_day: dict[date, frozenset[str]] = {}
            for day in events_days:
                base = frozenset(codes) if members_by_day is None else members_by_day[day]
                domain_by_day[day] = base - st_repo.st_codes_at(as_of=as_of, dt=day)
            # 三源事件候选（forecast → income → express，adapter 内固定优先级）。
            events = PostgresEarningsEventRepository(conn).list_events(
                as_of=as_of, start=start, end=end, wind_codes=codes
            )
            # ROE/股东权益/利润序列的报告期范围：覆盖 period_ly 与 last_period。min_period 取
            # start 前 _PERIOD_LOOKBACK_YEARS 年的 Q1 期末，max_period 取 end 所在年 Q4 期末。
            min_period = date(start.year - _PERIOD_LOOKBACK_YEARS, 3, 31)
            max_period = date(end.year, 12, 31)
            roe_rows = PostgresRoeRepository(conn).list_roe_by_periods(
                as_of=as_of, min_period=min_period, max_period=max_period, wind_codes=codes
            )
            equity_rows = PostgresShareholderEquityRepository(conn).list_equity_by_periods(
                as_of=as_of, min_period=min_period, max_period=max_period, wind_codes=codes
            )
            # 利润序列（get_profit 上一期累计）。report_type in (1001,1003)，端口不换算。
            profit_rows = PostgresIncomeGenRepository(conn).list_profit_series(
                as_of=as_of,
                min_report_year=start.year - _PERIOD_LOOKBACK_YEARS,
                max_period=end.year * 10000 + 1004,
                wind_codes=codes,
            )
        finally:
            conn.close()
        built = build_event_delta_roe_values(
            events=events,
            roe_rows=roe_rows,
            equity_rows=equity_rows,
            profit_rows=profit_rows,
            domain_by_day=domain_by_day,
            computed_at=computed_at,
            run_id=run_id,
        )
        values = built.values
        if not values:
            # 空批次合法/异常区分（同 event_sue/event_aog）。本月候选限定 declare ∈ [start,end]
            # 且披露期月份——非披露期无事件是合法空。
            month_candidates = sum(
                1
                for event in events
                if start <= event.declare_dt <= end and event.declare_dt.month in _VALID_MONTHS
            )
            if month_candidates == 0:
                digest_empty = digest_json([])
                _log(
                    paths=paths,
                    started=started,
                    start=start,
                    end=end,
                    as_of=as_of,
                    wind_codes=wind_codes,
                    run_id=run_id,
                    status="success",
                    row_count=0,
                    output_digest=digest_empty,
                    dml_count=0,
                )
                return 0, digest_empty
            raise LakeLayoutError(
                f"本月候选 {month_candidates}、过滤后候选 {built.candidate_count} 但全部未产值，"
                "属异常空，fail-closed"
            )
        write_feature_values(values, dest)
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
            for row in values
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
        row_count=len(values),
        output_digest=digest,
        dml_count=0,
    )
    return len(values), digest


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
