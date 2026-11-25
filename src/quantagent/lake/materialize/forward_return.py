"""``mart.forward_return``：从端口选取行情与日历、算收益、写入 Parquet。

选取只依赖 ``domain.ports`` 的 Protocol，不认识 PostgreSQL 或 DuckDB。
写入前逐行校验，任一行不合法即整批拒绝。写入后回读行数与内容 digest，不一致就删除本次文件。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.domain.calendar import open_dates
from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.feature_lineage import PIT_GRADES
from quantagent.domain.forward_return import (
    BENCHMARK_NONE,
    HORIZONS,
    RETURN_KIND,
    RETURN_LEG,
    build_forward_returns,
    forward_return_read_window,
)
from quantagent.lake.partitions import (
    FROZEN_FORWARD_RETURN_LAYOUT,
    LakeLayoutError,
    write_forward_return_parquet,
)
from quantagent.platform.identity import digest_json
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date
    from pathlib import Path

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.forward_return import ForwardReturn
    from quantagent.domain.ports.calendar import CalendarRepository
    from quantagent.domain.ports.prices import DailyPriceRepository
    from quantagent.platform.storage.paths import VarPaths

DATASET = "mart.forward_return"
ACTION = "lake.materialize.mart.forward_return"
EXCHANGE = "SSE"


@dataclass(frozen=True)
class ForwardReturnWriteResult:
    row_count: int
    n_files: int
    nbytes: int
    digest: str


def select_forward_returns(
    *,
    calendar: CalendarRepository,
    prices: DailyPriceRepository,
    contract: VisibilityContract,
    start: date,
    end: date,
    as_of: date,
    wind_codes: tuple[str, ...],
    horizons: Sequence[str] = HORIZONS,
    keep_row: Callable[[ForwardReturn], bool] | None = None,
) -> tuple[ForwardReturn, ...]:
    """信号日取 ``[start, end]`` 内的 SSE 开市日，且终点不晚于 ``as_of``。
    ``as_of`` 之后未成熟的区间不产行。没有成熟区间时返回空元组，由调用方决定如何报错。
    ``keep_row`` 为 None 时保留全部行；否则只保留它返回真的行，用于按截面日股票池过滤输出。
    """
    if start > end:
        raise InvalidQueryError("start 晚于 end")
    if start > as_of:
        raise InvalidQueryError("start 晚于 as_of")
    if not wind_codes:
        raise InvalidQueryError("wind_codes 为空，不扩成全市场")
    days = calendar.list_days(as_of=as_of, exchange=EXCHANGE, start=start, end=as_of)
    signal_dates = tuple(day for day in open_dates(days) if start <= day <= min(end, as_of))
    window = forward_return_read_window(
        days,
        signal_dates=signal_dates,
        horizons=horizons,
        as_of=as_of,
    )
    if window is None:
        return ()
    rows = prices.list_prices(
        as_of=as_of,
        start=window[0],
        end=window[1],
        wind_codes=wind_codes,
    )
    built = build_forward_returns(
        rows,
        days,
        signal_dates=signal_dates,
        contract=contract,
        as_of=as_of,
        horizons=horizons,
    )
    if keep_row is None:
        return built
    return tuple(row for row in built if keep_row(row))


def write_forward_returns(rows: Sequence[ForwardReturn], dest: Path) -> ForwardReturnWriteResult:
    if not rows:
        raise LakeLayoutError("没有可写入的前瞻收益行")
    _check_rows(rows)
    _check_identity_unique(rows)
    frame = pd.DataFrame(
        {
            "asset_id": [row.asset_id for row in rows],
            "event_dt": [row.event_dt for row in rows],
            "horizon": [row.horizon for row in rows],
            "return_kind": [row.return_kind for row in rows],
            "benchmark_id": [row.benchmark_id for row in rows],
            "return_leg": [row.return_leg for row in rows],
            "start_dt": [row.start_dt for row in rows],
            "value": [row.value for row in rows],
            "end_dt": [row.end_dt for row in rows],
            "knowledge_dt": [row.knowledge_dt for row in rows],
            "pit_grade": [row.pit_grade for row in rows],
        }
    )
    to_pandera(load_bundle().schemas[DATASET]).validate(frame)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    expected_digest = _content_digest(table)
    written = write_forward_return_parquet(table, dest, FROZEN_FORWARD_RETURN_LAYOUT)
    try:
        _verify_readback(written, table.num_rows, expected_digest)
    except LakeLayoutError:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    nbytes = sum(path.stat().st_size for path in written)
    return ForwardReturnWriteResult(
        row_count=table.num_rows,
        n_files=len(written),
        nbytes=nbytes,
        digest=expected_digest,
    )


def _check_rows(rows: Sequence[ForwardReturn]) -> None:
    """写入前逐行校验。这些规则在 domain 已经满足，这里是写入路径的最后一道闸，不替 domain 算。"""
    for row in rows:
        where = f"asset_id={row.asset_id} event_dt={row.event_dt} horizon={row.horizon}"
        if row.horizon not in HORIZONS:
            raise LakeLayoutError(f"horizon 不在允许集合，整批拒绝写入: {where}")
        if row.return_leg != RETURN_LEG or row.return_kind != RETURN_KIND:
            raise LakeLayoutError(f"收益腿或收益种类不合法，整批拒绝写入: {where}")
        if row.benchmark_id != BENCHMARK_NONE:
            raise LakeLayoutError(f"total 收益的 benchmark_id 必须为 none，整批拒绝写入: {where}")
        if row.pit_grade not in PIT_GRADES:
            raise LakeLayoutError(
                f"pit_grade 非法，整批拒绝写入: {where} pit_grade={row.pit_grade!r}"
            )
        if row.knowledge_dt != row.end_dt:
            raise LakeLayoutError(
                f"knowledge_dt 必须等于 end_dt，整批拒绝写入: {where} "
                f"knowledge_dt={row.knowledge_dt} end_dt={row.end_dt}"
            )
        if not (row.event_dt < row.start_dt < row.end_dt):
            raise LakeLayoutError(
                f"区间顺序必须是 event_dt < start_dt < end_dt，整批拒绝写入: {where}"
            )
        if not math.isfinite(row.value):
            raise LakeLayoutError(f"value 非有限值，整批拒绝写入: {where}")


def _check_identity_unique(rows: Sequence[ForwardReturn]) -> None:
    """身份键在批次内必须唯一。先于 pandera 检查，让错误类型与其他写入守卫一致。"""
    seen: set[tuple[str, date, str, str, str, str]] = set()
    for row in rows:
        key = (
            row.asset_id,
            row.event_dt,
            row.horizon,
            row.return_kind,
            row.benchmark_id,
            row.return_leg,
        )
        if key in seen:
            raise LakeLayoutError(
                f"写入批次含重复身份键，整批拒绝: asset_id={row.asset_id} "
                f"event_dt={row.event_dt} horizon={row.horizon}"
            )
        seen.add(key)


def _content_digest(table: pa.Table) -> str:
    return digest_json(_sorted_rows(table.to_pylist()))


def _sorted_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda item: (
            str(item["asset_id"]),
            str(item["event_dt"]),
            str(item["horizon"]),
            str(item["benchmark_id"]),
            str(item["return_leg"]),
        ),
    )


def _verify_readback(written: Sequence[Path], expected_rows: int, expected_digest: str) -> None:
    if not written:
        raise LakeLayoutError("写入结果为空，无法回读校验")
    # partitioning=None：回读单个文件时不让 pyarrow 从 ym= 目录名推断分区列，只比文件内容。
    readback = pa.concat_tables([pq.read_table(path, partitioning=None) for path in written])
    if readback.num_rows != expected_rows:
        raise LakeLayoutError(f"写后回读行数不一致: wrote={expected_rows} read={readback.num_rows}")
    if _content_digest(readback) != expected_digest:
        raise LakeLayoutError("写后回读内容 digest 不一致")


def materialize_forward_return(
    *,
    paths: VarPaths,
    calendar: CalendarRepository,
    prices: DailyPriceRepository,
    contract: VisibilityContract,
    start: date,
    end: date,
    as_of: date,
    wind_codes: tuple[str, ...],
    keep_row: Callable[[ForwardReturn], bool] | None = None,
    horizons: Sequence[str] = HORIZONS,
) -> ForwardReturnWriteResult:
    """选取、写入、写 run log。``dest`` 固定为 ``lake/mart/forward_return``。
    连接与代码池由调用方（CLI）组装，这里只接收端口，便于用内存实现测试。
    ``keep_row`` 由 CLI 按截面日股票池构造，选取后过滤输出行。
    ``horizons`` 默认全部；日更增量按 horizon 分别取起点时只传一个。
    """
    started = datetime.now(UTC)
    dest = paths.lake / "mart" / "forward_return"
    try:
        rows = select_forward_returns(
            calendar=calendar,
            prices=prices,
            contract=contract,
            start=start,
            end=end,
            as_of=as_of,
            wind_codes=wind_codes,
            keep_row=keep_row,
            horizons=horizons,
        )
        result = write_forward_returns(rows, dest)
    except Exception as exc:
        _log(
            paths=paths,
            started=started,
            start=start,
            end=end,
            as_of=as_of,
            wind_codes=wind_codes,
            horizons=horizons,
            error=str(exc),
        )
        raise
    _log(
        paths=paths,
        started=started,
        start=start,
        end=end,
        as_of=as_of,
        wind_codes=wind_codes,
        horizons=horizons,
        result=result,
    )
    return result


def _log(
    *,
    paths: VarPaths,
    started: datetime,
    start: date,
    end: date,
    as_of: date,
    wind_codes: tuple[str, ...],
    horizons: Sequence[str] = HORIZONS,
    result: ForwardReturnWriteResult | None = None,
    error: str | None = None,
) -> None:
    finished = datetime.now(UTC)
    record = RunLog(
        action=ACTION,
        status="failure" if error is not None else "success",
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "as_of": as_of.isoformat(),
                "wind_codes": list(wind_codes),
                "horizons": list(horizons),
                "return_leg": RETURN_LEG,
            }
        ),
        output_digest=None if result is None else result.digest,
        row_count=None if result is None else result.row_count,
        dml_count=0,
        error=error,
    )
    persist_run_log(record, paths)
