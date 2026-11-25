"""组装切段振幅物化：读行情、计算、写长表。业务规则不在这里。

``wind_codes`` 为 ``None`` 时，按每个截面日取 all_a 成员：读取范围取区间内各截面日成员的并集，
输出只保留截面日当天属于 all_a 的行。口径与其他因子一致（见 ``cli/_universe.py``）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.cli._universe import all_a_members_by_day, keep_rows_in_membership, union_codes
from quantagent.domain.calendar import open_dates
from quantagent.features.panel.cutamp import build_cutamp_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from datetime import date

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.cutamp"
_EXCHANGE = "SSE"
_LOOKBACK_DAYS = 60


def materialize_cutamp(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    wind_codes: tuple[str, ...] | None,
    as_of: date,
) -> tuple[int, str]:
    started = datetime.now(UTC)
    dest = paths.lake / "feature" / "value"
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    try:
        members_by_day: dict[date, frozenset[str]] | None = None
        conn = connect(settings, "src")
        try:
            if wind_codes is None:
                events = _open_days(paths, as_of=as_of, start=start, end=end)
                members_by_day = all_a_members_by_day(conn, as_of=as_of, days=events)
                codes = union_codes(members_by_day)
            else:
                codes = wind_codes
            prices = PostgresDailyPriceRepository(conn).list_prices(
                as_of=as_of,
                start=start - timedelta(days=_LOOKBACK_DAYS),
                end=end,
                wind_codes=codes,
            )
        finally:
            conn.close()
        rows = build_cutamp_values(
            prices,
            contract=load_price_visibility(),
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


def _open_days(paths: VarPaths, *, as_of: date, start: date, end: date) -> tuple[date, ...]:
    """``[start, end]`` 内的 SSE 开市日。``as_of`` 之后的日子不可见，自然不进入。"""
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    days = calendar.list_days(as_of=as_of, exchange=_EXCHANGE, start=start, end=end)
    return tuple(day for day in open_dates(days) if start <= day <= end)


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
