"""组装分钟因子物化：读分钟分区、计算、写长表。业务规则不在这里。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.minute_bar import LakeMinuteBarRepository
from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.contracts.loader import load_bundle
from quantagent.domain.calendar import open_dates
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID
from quantagent.features.panel.minute import build_minute_factor_values
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

ACTION = "lake.materialize.feature.minute_factors"
DATASET = "src.minprice.ashare_minute_bar"
_EXCHANGE = "SSE"
# 起点之前至少要有 4 个开市日。60 个自然日足以覆盖长假。
_CALENDAR_PAD_DAYS = 60


def materialize_minute_factors(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    as_of: date,
    codes: Sequence[str] | None,
    feature_ids: Sequence[str] | None = None,
) -> tuple[int, str]:
    """``codes`` 为 ``None`` 时，每个截面日的股票范围取该日 ``all_a`` 成员。
    ``feature_ids`` 非空时只写这些因子（计算仍覆盖四个因子）；增量运行按因子分别取起点时使用。
    """
    if feature_ids is not None and not feature_ids:
        raise ValueError("feature_ids 为空，拒绝写入")
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
        conn = connect(settings, "src")
        try:
            conn.read_only = True
            repo = LakeMinuteBarRepository(conn, minute_root, calendar)
            rows = build_minute_factor_values(
                repo,
                as_of=as_of,
                opens=opens,
                start=start,
                end=end,
                contract=load_bundle().visibilities[DATASET],
                universe_at=_universe_at(conn, as_of=as_of, codes=codes),
                computed_at=computed_at,
                run_id=run_id,
            )
        finally:
            conn.close()
        if feature_ids is not None:
            wanted = frozenset(feature_ids)
            rows = tuple(row for row in rows if row.feature_id in wanted)
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
    codes: Sequence[str] | None,
) -> Callable[[date], Sequence[str]]:
    """返回 ``截面日 -> 股票代码``。指定 ``codes`` 时所有截面日相同；否则取该日 all_a 成员。"""
    if codes is not None:
        fixed = tuple(sorted(set(codes)))
        return lambda _day: fixed
    universe = PostgresUniverseRepository(conn)

    def _members(day: date) -> tuple[str, ...]:
        members = universe.members_at(as_of=as_of, dt=day, universe_id=ALL_A_UNIVERSE_ID)
        return tuple(sorted(member.asset_id for member in members))

    return _members


def _log(
    *,
    paths: VarPaths,
    started: datetime,
    start: date,
    end: date,
    as_of: date,
    codes: Sequence[str] | None,
    feature_ids: Sequence[str] | None,
    run_id: str,
    status: Literal["success", "failure"],
    row_count: int | None = None,
    output_digest: str | None = None,
    dml_count: int = 0,
    error: str | None = None,
) -> None:
    finished = datetime.now(UTC)
    extra: dict[str, object] = {}
    if feature_ids is not None:
        extra["feature_ids"] = sorted(set(feature_ids))
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
                "dataset": DATASET,
                **extra,
            }
        ),
        output_digest=output_digest,
        row_count=row_count,
        dml_count=dml_count,
        error=error,
    )
    persist_run_log(record, paths)
