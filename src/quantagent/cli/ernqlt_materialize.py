"""组装 barra_cne6_ernqlt 物化：读日历、股票域、四表财报、行业映射与流通市值，逐截面合成，写长表。

业务规则不在这里——descriptor 计算在 ``features.library.fundamental.ernqlt*``，跨股票合成在
``features.library.cross_section``，截面驱动在 ``features.panel.ernqlt``。本 CLI 只负责
取数、装配、写湖、记 run log。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.derivative_indicator import PostgresDerivativeIndicatorRepository
from quantagent.adapters.postgres.fundamental import (
    BALANCE_DATASET,
    CASHFLOW_DATASET,
    INCOME_DATASET,
    INDICATOR_DATASET,
    PostgresFinancialSeriesRepository,
    load_fundamental_visibility,
)
from quantagent.adapters.postgres.industry import PostgresIndustryMapRepository
from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.adapters.postgres.universe import load_derivative_visibility
from quantagent.cli._universe import all_a_members_by_day, union_codes
from quantagent.domain.calendar import open_dates
from quantagent.features.library.fundamental.ernqlt_series import (
    BALANCE_FIELDS,
    CASHFLOW_FIELDS,
    INCOME_FIELDS,
    INDICATOR_FIELDS,
)
from quantagent.features.panel.ernqlt import build_ernqlt_values
from quantagent.lake.materialize.feature_value import write_feature_values
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.materialize.feature.barra_cne6_ernqlt"
_EXCHANGE = "SSE"
# ERNQLT 回看 21 个报告期（约 5.25 年），留出公告滞后余量按 6 年回读报告期下界。
_READ_BACK_YEARS = 6


def materialize_ernqlt(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    wind_codes: tuple[str, ...] | None,
    as_of: date,
) -> tuple[int, str, tuple[tuple[date, int, int], ...]]:
    """返回 (行数, 输出 digest, 逐截面覆盖率)。

    股票域与 did_ratio/mif 相同：``wind_codes`` 为 None 时每个截面日取 all_a 减当日 ST，
    读取范围是各截面日成员的并集；输出只保留截面日当天属于 all_a 的行。财报一次性读全历史
    （``REPORT_PERIOD >= start - 6 年`` 下界），逐截面按 ``ANN_DT < day`` 裁剪，复现旧仓
    ``ANN_DT < adj_date``。行业映射与流通市值逐截面日读取（截面权重）。
    """
    started = datetime.now(UTC)
    dest = paths.lake / "feature" / "value"
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    coverage: tuple[tuple[date, int, int], ...] = ()
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

            # 财报四表一次性读全历史。min_period 按报告期下界（约 6 年覆盖 21 期+公告滞后）。
            min_period = date(start.year - _READ_BACK_YEARS, 1, 1)
            balance_rows = PostgresFinancialSeriesRepository(
                conn, dataset=BALANCE_DATASET
            ).list_series(
                as_of=as_of, min_period=min_period, fields=BALANCE_FIELDS, wind_codes=codes
            )
            income_rows = PostgresFinancialSeriesRepository(
                conn, dataset=INCOME_DATASET
            ).list_series(
                as_of=as_of, min_period=min_period, fields=INCOME_FIELDS, wind_codes=codes
            )
            cashflow_rows = PostgresFinancialSeriesRepository(
                conn, dataset=CASHFLOW_DATASET
            ).list_series(
                as_of=as_of, min_period=min_period, fields=CASHFLOW_FIELDS, wind_codes=codes
            )
            indicator_rows = PostgresFinancialSeriesRepository(
                conn, dataset=INDICATOR_DATASET
            ).list_series(
                as_of=as_of, min_period=min_period, fields=INDICATOR_FIELDS, wind_codes=codes
            )

            # 行业映射与流通市值逐截面日读取。
            industry_repo = PostgresIndustryMapRepository(conn)
            derivative_repo = PostgresDerivativeIndicatorRepository(conn)
            industry_map_by_day: dict[date, dict[str, str]] = {}
            dq_mv_by_day: dict[date, dict[str, Decimal | None]] = {}
            for day in events:
                industry_map_by_day[day] = industry_repo.industry_map_at(as_of=as_of, dt=day)
                mv_rows = derivative_repo.list_dq_market_value(
                    as_of=as_of, start=day, end=day, wind_codes=codes
                )
                dq_mv_by_day[day] = {row.wind_code: row.dq_mv for row in mv_rows}
        finally:
            conn.close()

        built = build_ernqlt_values(
            domain_by_day=domain_by_day,
            balance_rows=balance_rows,
            cashflow_rows=cashflow_rows,
            income_rows=income_rows,
            indicator_rows=indicator_rows,
            industry_map_by_day=industry_map_by_day,
            dq_mv_by_day=dq_mv_by_day,
            financial_grade=load_fundamental_visibility(BALANCE_DATASET).visibility.grade,
            market_grade=load_derivative_visibility().visibility.grade,
            industry_grade="B",  # mart.universe_member 成分契约 grade B（knowledge_dt=INDATE 近似）
            computed_at=computed_at,
            run_id=run_id,
        )
        rows = built.values
        coverage = built.coverage
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
    return len(rows), digest, coverage


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
