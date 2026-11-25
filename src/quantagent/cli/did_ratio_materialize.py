"""组装稳健股息率物化：读日历、股票域、分红、利润表、财务指标与市值，计算，写长表。业务规则不在这里。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.derivative_indicator import PostgresDerivativeIndicatorRepository
from quantagent.adapters.postgres.fundamental import (
    DIVIDEND_DATASET,
    INCOME_DATASET,
    INDICATOR_DATASET,
    PostgresDividendRepository,
    PostgresFinancialIndicatorRepository,
    PostgresNetProfitRepository,
    load_fundamental_visibility,
)
from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.adapters.postgres.universe import load_derivative_visibility
from quantagent.cli._universe import all_a_members_by_day, union_codes
from quantagent.domain.calendar import open_dates
from quantagent.features.library.fundamental.did_ratio import (
    STATEMENT_TYPE,
    WINDOW_DAYS,
)
from quantagent.features.panel.did_ratio import build_did_ratio_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.did_ratio"
_EXCHANGE = "SSE"
# ANN_DT 窗口为 (T − 1825 天, T]，最早需要的公告日是 start − 1824 天。
_READ_BACK_DAYS = WINDOW_DAYS - 1


def materialize_did_ratio(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    wind_codes: tuple[str, ...] | None,
    as_of: date,
) -> tuple[int, str, int]:
    """返回 (行数, 输出 digest, 因取值冲突跳过的股票日数)。

    股票域：``wind_codes`` 为 None 时，每个截面日取 all_a 成员去掉当日 ST，读取范围为各截面日成员的并集；
    输出只保留截面日当天属于 all_a 的行。与 ``cli/mif_materialize`` 相同，避免用某一日成员回填整个区间。
    ``wind_codes`` 非空时不套用 all_a，只去掉当日 ST，供小范围核对。
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
            members_by_day: Mapping[date, frozenset[str]] | None = None
            if wind_codes is None:
                members_by_day = all_a_members_by_day(conn, as_of=as_of, days=events)
                codes = union_codes(members_by_day)
            else:
                codes = wind_codes
            st_repo = PostgresStStatusRepository(conn)
            domain_by_day: dict[date, frozenset[str]] = {}
            for day in events:
                base = frozenset(codes) if members_by_day is None else members_by_day[day]
                domain_by_day[day] = base - st_repo.st_codes_at(as_of=as_of, dt=day)
            read_start = start - timedelta(days=_READ_BACK_DAYS)
            dividends = PostgresDividendRepository(conn).list_dividends(
                as_of=as_of, start=read_start, end=end, wind_codes=codes
            )
            net_profits = PostgresNetProfitRepository(conn).list_net_profits(
                as_of=as_of,
                start=read_start,
                end=end,
                statement_type=STATEMENT_TYPE,
                wind_codes=codes,
            )
            indicators = PostgresFinancialIndicatorRepository(conn).list_indicator_rows(
                as_of=as_of, start=read_start, end=end, wind_codes=codes
            )
            market_values = PostgresDerivativeIndicatorRepository(conn).list_market_value(
                as_of=as_of, start=start, end=end, wind_codes=codes
            )
        finally:
            conn.close()
        built = build_did_ratio_values(
            domain_by_day=domain_by_day,
            dividends=dividends,
            net_profits=net_profits,
            indicators=indicators,
            market_values=market_values,
            dividend_contract=load_fundamental_visibility(DIVIDEND_DATASET),
            income_contract=load_fundamental_visibility(INCOME_DATASET),
            indicator_contract=load_fundamental_visibility(INDICATOR_DATASET),
            market_contract=load_derivative_visibility(),
            computed_at=computed_at,
            run_id=run_id,
        )
        rows = built.values
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
    return len(rows), digest, len(built.conflicts)


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
