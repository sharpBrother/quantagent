"""组装 event_aog 物化：读交易日历、股票域、三源事件候选与开盘行情，计算，写长表。业务规则不在这里。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import PostgresDailyPriceRepository
from quantagent.adapters.postgres.index_returns import PostgresIndexReturnRepository
from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.adapters.postgres.suntime_event import PostgresEarningsEventRepository
from quantagent.cli._universe import all_a_members_by_day, union_codes
from quantagent.domain.calendar import open_dates
from quantagent.features.library.fundamental.event_aog import BENCHMARK_INDEX
from quantagent.features.panel.event_aog import build_event_aog_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.lake.partitions import LakeLayoutError
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.event_aog"
_EXCHANGE = "SSE"
# 行情/日历窗口向后宽限的自然日数：月末 declare 的次日 open 落在下月初，需覆盖。
# declare 距 open 最多 1 个交易日，5 个自然日足够覆盖任何周末/小长假；给 10 天留余量。
# 多读不碍正确性（panel 按 declare 窗口过滤事件），只影响读取体积。
_OPEN_LOOKAHEAD_DAYS = 10


def materialize_event_aog(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    wind_codes: tuple[str, ...] | None,
    as_of: date,
) -> tuple[int, str]:
    """返回 (行数, 输出 digest)。

    股票域：``wind_codes`` 为 None 时每个事件 declare 日取 all_a 成员去掉当日 ST。
    event_aog 是事件驱动稀疏因子：``event_dt = open_date``（财报跳空反映在开盘价的那天，
    非 declare_date），缺失不补 0。
    """
    started = datetime.now(UTC)
    dest = paths.lake / "feature" / "value"
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    try:
        # 日历与行情窗口向后宽限，覆盖月末 declare 的次月 open_date。
        cal_end = end + timedelta(days=_OPEN_LOOKAHEAD_DAYS)
        days = LakeCalendarRepository(paths.lake / "std" / "trade_calendar").list_days(
            as_of=as_of,
            exchange=_EXCHANGE,
            start=start,
            end=cal_end,
        )
        opens = open_dates(days)
        # 域判定截面是所有可能的 open_date——即 [start, cal_end] 窗口内全部交易日（含宽限）。
        # 域判定在 open_date 而非 declare 日（裁定 A1），月末 declare 的 open 落在次月，需覆盖。
        open_domain_days = tuple(day for day in opens if start <= day <= cal_end)
        conn = connect(settings, "src")
        try:
            members_by_day: Mapping[date, frozenset[str]] | None = None
            if wind_codes is None:
                members_by_day = all_a_members_by_day(conn, as_of=as_of, days=open_domain_days)
                codes = union_codes(members_by_day)
            else:
                codes = wind_codes
            st_repo = PostgresStStatusRepository(conn)
            domain_by_day: dict[date, frozenset[str]] = {}
            for day in open_domain_days:
                base = frozenset(codes) if members_by_day is None else members_by_day[day]
                domain_by_day[day] = base - st_repo.st_codes_at(as_of=as_of, dt=day)
            # 三源事件候选（forecast → income → express，adapter 内固定优先级）。
            events = PostgresEarningsEventRepository(conn).list_events(
                as_of=as_of, start=start, end=end, wind_codes=codes
            )
            # open_date 行情窗口：[窗口首个开市日, cal_end]。个股复权价算夜盘涨幅。
            px_start = opens[0] if opens else start
            stock_prices = PostgresDailyPriceRepository(conn).list_prices(
                as_of=as_of, start=px_start, end=cal_end, wind_codes=codes
            )
            index_returns = PostgresIndexReturnRepository(conn).list_returns(
                as_of=as_of, start=px_start, end=cal_end, wind_codes=(BENCHMARK_INDEX,)
            )
        finally:
            conn.close()
        built = build_event_aog_values(
            events=events,
            stock_prices=stock_prices,
            index_returns=index_returns,
            open_day_set=frozenset(opens),
            domain_by_day=domain_by_day,
            computed_at=computed_at,
            run_id=run_id,
        )
        values = built.values
        if not values:
            # 空批次合法/异常区分（同 event_sue，负责人 2026-11-26 裁定）：候选为 0 是合法空。
            if built.candidate_count == 0:
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
                f"有 {built.candidate_count} 个候选事件但全部未产值，属异常空，fail-closed"
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
