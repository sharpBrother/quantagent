"""组装 event_sue 物化：读交易日历、股票域、三源事件候选与历史利润序列，计算，写长表。业务规则不在这里。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.st import PostgresStStatusRepository
from quantagent.adapters.postgres.suntime_event import PostgresEarningsEventRepository
from quantagent.adapters.postgres.suntime_income_gen import PostgresIncomeGenRepository
from quantagent.cli._universe import all_a_members_by_day, union_codes
from quantagent.domain.calendar import open_dates
from quantagent.features.library.fundamental.event_sue import LOOKBACK_YEARS
from quantagent.features.panel.event_sue import build_event_sue_values
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

ACTION = "lake.materialize.feature.event_sue"
_EXCHANGE = "SSE"
# 日历/域向后宽限的自然日数：非交易日 declare 后首个交易日可能落在物化窗口 end 之后。
_DOMAIN_LOOKAHEAD_DAYS = 10
# 历史利润序列的批量回退年数：事件报告期最早可追溯到 start 前一年（Q4 报告次年披露），
# 单季同比需 8 期 + 序列重构需 LOOKBACK_YEARS 年。给足余量取 start 前 6 年，逐事件的精确
# report_year >= 当期 − LOOKBACK_YEARS 裁剪在 panel 做。多读不碍正确性（panel 逐事件再过滤），
# 只影响读取体积。
_READ_BACK_YEARS = LOOKBACK_YEARS + 2


def materialize_event_sue(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    wind_codes: tuple[str, ...] | None,
    as_of: date,
) -> tuple[int, str]:
    """返回 (行数, 输出 digest)。

    股票域：``wind_codes`` 为 None 时每个事件日取 all_a 成员去掉当日 ST（与 did_ratio/nap 相同）。
    event_sue 是事件驱动稀疏因子：只在事件公告日对域内股票落行，缺失不补 0。
    """
    started = datetime.now(UTC)
    dest = paths.lake / "feature" / "value"
    run_id = new_run_id()
    computed_at = started.replace(tzinfo=None)
    try:
        # 日历向后宽限覆盖域判定截面：月末/周末 declare 后首个交易日可能落在 end 之后
        # （如 10-31 周六 declare → 11-02 周一）。declare 距后首个交易日最多几天，给 10 天余量。
        cal_end = end + timedelta(days=_DOMAIN_LOOKAHEAD_DAYS)
        days = LakeCalendarRepository(paths.lake / "std" / "trade_calendar").list_days(
            as_of=as_of,
            exchange=_EXCHANGE,
            start=start,
            end=cal_end,
        )
        # 域判定截面含宽限（覆盖 declare 后首个交易日）；事件候选仍按 [start,end] 的 declare 窗口。
        events_days = tuple(day for day in open_dates(days) if start <= day <= cal_end)
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
            # 历史利润序列批量读取：给足回退。max_period 取 end 所在年 Q4。
            min_report_year = start.year - _READ_BACK_YEARS
            max_period = end.year * 10000 + 1004
            profit_rows = PostgresIncomeGenRepository(conn).list_profit_series(
                as_of=as_of,
                min_report_year=min_report_year,
                max_period=max_period,
                wind_codes=codes,
            )
        finally:
            conn.close()
        built = build_event_sue_values(
            events=events,
            profit_rows=profit_rows,
            domain_by_day=domain_by_day,
            computed_at=computed_at,
            run_id=run_id,
        )
        values = built.values
        if not values:
            # 空批次的合法/异常区分（负责人 2026-11-26 裁定）：事件驱动因子在非披露期本无事件。
            # 候选为 0（经月份/时效过滤后无事件）是业务事实，返回 0 行成功不写文件；
            # 候选非 0 却全部未产值是算法/数据问题，必须 fail-closed 报错。
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
