"""组装第二批分钟因子物化：读分钟分区与日行情、计算、写长表。业务规则不在这里。

股票范围与 ``minute_factors_materialize.py`` 相同：未指定 ``codes`` 时，每个截面日取该日 all_a 成员。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.minute_bar import LakeMinuteBarRepository
from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import PostgresDailyPriceRepository
from quantagent.cli._universe import all_a_members_by_day
from quantagent.contracts.loader import load_bundle
from quantagent.domain.calendar import open_dates
from quantagent.features.panel.minute_2b import build_minute_2b_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    import psycopg

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.minute_factors_2b"
MINUTE_DATASET = "src.minprice.ashare_minute_bar"
PRICE_DATASET = "src.wind.ashareeodprices"
_EXCHANGE = "SSE"
# 起点之前至少要有 20 个开市日（20 日窗口加 pxret21 的基准日）。60 个自然日足以覆盖长假。
_CALENDAR_PAD_DAYS = 60


def materialize_minute_factors_2b(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    as_of: date,
    codes: Sequence[str] | None,
    feature_ids: Sequence[str],
) -> tuple[int, str]:
    """``feature_ids`` 为空时抛错；``codes`` 为 ``None`` 时每个截面日的股票范围取该日 ``all_a`` 成员。"""
    started = datetime.now(UTC)
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    dest = paths.lake / "feature" / "value"
    minute_root = paths.lake / "src" / "minprice" / "ashare_minute_bar"
    try:
        calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
        days = calendar.list_days(
            as_of=as_of,
            exchange=_EXCHANGE,
            start=start - timedelta(days=_CALENDAR_PAD_DAYS),
            end=end,
        )
        opens = open_dates(days)
        targets = tuple(day for day in opens if start <= day <= end)
        bundle = load_bundle()
        conn = connect(settings, "src")
        try:
            conn.read_only = True
            repo = LakeMinuteBarRepository(conn, minute_root, calendar)
            rows = build_minute_2b_values(
                repo,
                PostgresDailyPriceRepository(conn),
                as_of=as_of,
                opens=opens,
                start=start,
                end=end,
                minute_contract=bundle.visibilities[MINUTE_DATASET],
                price_contract=bundle.visibilities[PRICE_DATASET],
                universe_at=_universe_at(conn, as_of=as_of, days=targets, codes=codes),
                computed_at=computed_at,
                run_id=run_id,
                feature_ids=feature_ids,
            )
        finally:
            conn.close()
        write_feature_values(rows, dest)
    except Exception as exc:
        _log(
            paths=paths,
            started=started,
            start=start,
            end=end,
            as_of=as_of,
            codes=codes,
            feature_ids=feature_ids,
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
                "feature_id": row.feature_id,
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
        codes=codes,
        feature_ids=feature_ids,
        run_id=run_id,
        status="success",
        row_count=len(rows),
        output_digest=digest,
        dml_count=0,
    )
    return len(rows), digest


def _universe_at(
    conn: psycopg.Connection[object],
    *,
    as_of: date,
    days: Sequence[date],
    codes: Sequence[str] | None,
) -> Callable[[date], Sequence[str]]:
    """返回 ``截面日 -> 股票代码``。指定 ``codes`` 时所有截面日相同；否则取该日 all_a 成员（共用口径）。"""
    if codes is not None:
        fixed = tuple(sorted(set(codes)))
        return lambda _day: fixed
    members = all_a_members_by_day(conn, as_of=as_of, days=days)
    return lambda day: tuple(sorted(members[day]))


def _log(
    *,
    paths: VarPaths,
    started: datetime,
    start: date,
    end: date,
    as_of: date,
    codes: Sequence[str] | None,
    feature_ids: Sequence[str],
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
                "universe": "all_a_per_open_day" if codes is None else sorted(set(codes)),
                "feature_ids": sorted(set(feature_ids)),
                "datasets": [MINUTE_DATASET, PRICE_DATASET],
            }
        ),
        output_digest=output_digest,
        row_count=row_count,
        dml_count=dml_count,
        error=error,
    )
    persist_run_log(record, paths)
