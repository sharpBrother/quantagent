"""组装 MIF 物化：读日历、股票池、行情、衍生指标换手，计算，写长表。业务规则不在这里。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.adapters.postgres.derivative_indicator import PostgresDerivativeIndicatorRepository
from quantagent.adapters.postgres.universe import load_derivative_visibility
from quantagent.cli._universe import (
    all_a_members_by_day,
    keep_rows_in_membership,
    union_codes,
)
from quantagent.domain.calendar import open_dates
from quantagent.features.panel.mif import build_mif_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from datetime import date

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.mif"
_EXCHANGE = "SSE"
# 个股自有 21 行的窗口：按自然日估计，取 120 天，与资金流物化的个股行窗口口径一致。
# 停牌日在源表里仍有行（Wind 填前收盘价），行数按交易日计，不因停牌缩短。
_OWN_ROW_PAD_DAYS = 120


def materialize_mif(
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
    会丢掉退出前的截面，造成幸存者偏差。口径与资金流因子（``cli/moneyflow_materialize``）一致。
    """
    started = datetime.now(UTC)
    dest = paths.lake / "feature" / "value"
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    try:
        days = LakeCalendarRepository(paths.lake / "std" / "trade_calendar").list_days(
            as_of=as_of,
            exchange=_EXCHANGE,
            start=start,
            end=end,
        )
        events = tuple(day for day in open_dates(days) if start <= day <= end)
        conn = connect(settings, "src")
        try:
            members_by_day: dict[date, frozenset[str]] | None = None
            if wind_codes is None:
                members_by_day = all_a_members_by_day(conn, as_of=as_of, days=events)
                codes = union_codes(members_by_day)
            else:
                codes = wind_codes
            read_start = start - timedelta(days=_OWN_ROW_PAD_DAYS)
            prices = PostgresDailyPriceRepository(conn).list_prices(
                as_of=as_of,
                start=read_start,
                end=end,
                wind_codes=codes,
            )
            turnovers = PostgresDerivativeIndicatorRepository(conn).list_turnover(
                as_of=as_of,
                start=read_start,
                end=end,
                wind_codes=codes,
            )
        finally:
            conn.close()
        rows = build_mif_values(
            prices,
            turnovers,
            price_contract=load_price_visibility(),
            turnover_contract=load_derivative_visibility(),
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
