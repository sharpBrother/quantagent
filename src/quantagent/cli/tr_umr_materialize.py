"""组装真实波幅 UMR 物化：读日历、行情、指数收益，计算，写长表。业务规则不在这里。"""

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
from quantagent.domain.calendar import open_dates
from quantagent.features.library.price.tr_umr import BENCHMARK, LOOKBACK
from quantagent.features.panel.tr_umr import build_tr_umr_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.tr_umr"
_EXCHANGE = "SSE"
# 69 个开市日大约三个月。日历从截面起点再往前取 240 个自然日，用来覆盖第一个截面日之前的 68 个开市日。
_CALENDAR_PAD_DAYS = 240


def materialize_tr_umr(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    wind_codes: tuple[str, ...],
    as_of: date,
) -> tuple[int, str]:
    started = datetime.now(UTC)
    dest = paths.lake / "feature" / "value"
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    try:
        # 旧仓 trade_cal 的开市日来自 Wind 日历。本仓按市场拆开，这个 A 股因子用 SSE。
        days = LakeCalendarRepository(paths.lake / "std" / "trade_calendar").list_days(
            as_of=as_of,
            exchange=_EXCHANGE,
            start=start - timedelta(days=_CALENDAR_PAD_DAYS),
            end=end,
        )
        opens = open_dates(days)
        read_start = _read_start(opens, start=start, end=end)
        conn = connect(settings, "src")
        try:
            prices = PostgresDailyPriceRepository(conn).list_prices(
                as_of=as_of,
                start=read_start,
                end=end,
                wind_codes=wind_codes,
            )
            index_returns = PostgresIndexReturnRepository(conn).list_returns(
                as_of=as_of,
                start=read_start,
                end=end,
                wind_codes=(BENCHMARK,),
            )
        finally:
            conn.close()
        rows = build_tr_umr_values(
            prices,
            index_returns,
            opens,
            price_contract=load_price_visibility(),
            index_contract=load_index_visibility(),
            start=start,
            end=end,
            computed_at=computed_at,
            run_id=run_id,
        )
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


def _read_start(open_days: Sequence[date], *, start: date, end: date) -> date:
    """行情和指数的读取起点，覆盖第一个截面开市日再往前 68 个开市日。"""
    ordered = tuple(sorted(open_days))
    events = [day for day in ordered if start <= day <= end]
    if not events:
        return start
    first = ordered.index(events[0])
    return ordered[max(0, first - (LOOKBACK - 1))]


def _log(
    *,
    paths: VarPaths,
    started: datetime,
    start: date,
    end: date,
    as_of: date,
    wind_codes: tuple[str, ...],
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
                "wind_codes": list(wind_codes),
            }
        ),
        output_digest=output_digest,
        row_count=row_count,
        dml_count=dml_count,
        error=error,
    )
    persist_run_log(record, paths)
