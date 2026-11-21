"""Tushare ``shibor`` 采集作业。CLI 与 Dagster 共用。

按自然月分段拉取、分段提交：每段一个事务，每段一条 run log。某段失败即停，前面已提交的段保留。
重跑同一区间是幂等的：已有行指纹相同则跳过，只有源端改过的历史值才会替换。

"""

from __future__ import annotations

import calendar
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.postgres.src_progress import latest_success_window_end
from quantagent.adapters.postgres.src_targets import SHIBOR
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.errors import IngestError
from quantagent.ingest.sources.tushare.shibor import (
    open_shibor_client,
    shibor_wide_to_long,
)
from quantagent.ingest.writers.src_follow import write_src_follow
from quantagent.platform.errors import ConfigError, RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable

    from quantagent.ingest.sources.tushare.shibor import ShiborClient
    from quantagent.ingest.writers.src_follow import SrcFollowWriteResult
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.tushare.shibor"

# 日更重查的回看天数。修订的历史值会被跟随源端替换，回看只为覆盖近期修订与迟到的数据。
DAILY_LOOKBACK_DAYS = 30

_YMD = "%Y%m%d"
_YMD_LEN = 8


@dataclass(frozen=True)
class TushareShiborIngestResult:
    """干跑时 ``written`` 为 False，计数字段为 0 或只有 ``row_count``，不代表源端没有变化。"""

    dataset: str
    written: bool
    segments: int
    row_count: int
    inserted: int
    replaced: int
    skipped: int
    metadata_skipped: int
    dml_count: int
    # 区间内源端没有返回任何期限行的月段起点。预期有数据却没有，要人工看一眼。
    empty_segments: tuple[str, ...]
    batch_ids: tuple[int, ...]
    payload_digest: str
    output_digest: str


def ingest_tushare_shibor(
    *,
    settings: Settings,
    paths: VarPaths,
    write_db: bool = False,
    start_date: str,
    end_date: str,
    client: ShiborClient | None = None,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> TushareShiborIngestResult:
    _assert_ymd(start_date, field="start_date")
    _assert_ymd(end_date, field="end_date")
    if start_date > end_date:
        raise IngestError("start_date 晚于 end_date")
    clock = now or (lambda: datetime.now(UTC))
    resolved_client = client or open_shibor_client(settings.tushare_token.get_secret_value())
    owned_conn = None
    try:
        if write_db and store is None:
            owned_conn = connect(settings, "src")
            store = PostgresSrcStore(owned_conn)
        outcomes: list[_SegmentOutcome] = []
        for seg_start, seg_end in month_segments(start_date, end_date):
            outcomes.append(
                _ingest_segment(
                    settings=settings,
                    paths=paths,
                    client=resolved_client,
                    store=store,
                    write_db=write_db,
                    seg_start=seg_start,
                    seg_end=seg_end,
                    clock=clock,
                )
            )
    finally:
        if owned_conn is not None:
            owned_conn.close()
    return _aggregate(outcomes, write_db=write_db)


@dataclass(frozen=True)
class _SegmentOutcome:
    start: str
    end: str
    result: SrcFollowWriteResult | None


def _ingest_segment(
    *,
    settings: Settings,
    paths: VarPaths,
    client: ShiborClient,
    store: SrcWriteStore | None,
    write_db: bool,
    seg_start: str,
    seg_end: str,
    clock: Callable[[], datetime],
) -> _SegmentOutcome:
    started = datetime.now(UTC)
    try:
        frame = client.shibor(start_date=seg_start, end_date=seg_end)
        # 同一段的所有行共用一个采集时刻。它同时作为 _ingested_at 与原生 ingested_at，
        # 写入器会核对两者是否一致。
        stamp = clock()
        rows = shibor_wide_to_long(
            frame,
            start_date=seg_start,
            end_date=seg_end,
            ingested_at=stamp.astimezone(UTC).replace(tzinfo=None),
        )
        result: SrcFollowWriteResult | None = None
        if rows:
            result = write_src_follow(
                spec=SHIBOR,
                rows=rows,
                settings=settings,
                write_db=write_db,
                store=store,
                window_start=seg_start,
                window_end=seg_end,
                now=lambda: stamp,
            )
    except Exception as exc:
        # 失败段的 run log 也要落。已提交的段各自有 run log，不受影响。
        with suppress(RunLogError):
            _persist_run_log(
                paths=paths,
                started=started,
                seg_start=seg_start,
                seg_end=seg_end,
                write_db=write_db,
                result=None,
                error=str(exc),
            )
        raise
    _persist_run_log(
        paths=paths,
        started=started,
        seg_start=seg_start,
        seg_end=seg_end,
        write_db=write_db,
        result=result,
        error=None,
    )
    return _SegmentOutcome(start=seg_start, end=seg_end, result=result)


def _aggregate(outcomes: list[_SegmentOutcome], *, write_db: bool) -> TushareShiborIngestResult:
    results = [item.result for item in outcomes if item.result is not None]
    empty = tuple(item.start for item in outcomes if item.result is None)
    segment_digests = [
        item.result.output_digest if item.result is not None else digest_json([])
        for item in outcomes
    ]
    return TushareShiborIngestResult(
        dataset=SHIBOR.dataset,
        written=write_db,
        segments=len(outcomes),
        row_count=sum(item.row_count for item in results),
        inserted=sum(item.inserted for item in results),
        replaced=sum(item.replaced for item in results),
        skipped=sum(item.skipped for item in results),
        metadata_skipped=sum(item.metadata_skipped for item in results),
        dml_count=sum(item.dml_count for item in results),
        empty_segments=empty,
        batch_ids=tuple(item.batch_id for item in results if item.batch_id is not None),
        payload_digest=digest_json([item.payload_digest for item in results]),
        output_digest=digest_json(segment_digests),
    )


def month_segments(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """按自然月切段，首尾相接、不重叠。起止日都取闭区间。"""
    _assert_ymd(start_date, field="start_date")
    _assert_ymd(end_date, field="end_date")
    if start_date > end_date:
        raise IngestError("start_date 晚于 end_date")
    current = _parse(start_date)
    last = _parse(end_date)
    segments: list[tuple[str, str]] = []
    while current <= last:
        month_last = date(
            current.year,
            current.month,
            calendar.monthrange(current.year, current.month)[1],
        )
        seg_end = min(month_last, last)
        segments.append((current.strftime(_YMD), seg_end.strftime(_YMD)))
        current = seg_end + timedelta(days=1)
    return segments


def daily_start_date(window_end: str | None, *, end_date: str) -> str:
    """日更起点 = 最近成功批次的 ``window_end`` 往前 ``DAILY_LOOKBACK_DAYS`` 个自然日。

    没有成功批次时直接报错。此时不知道该从哪一天开始，猜一个日期会静默漏数或多拉。
    """
    _assert_ymd(end_date, field="end_date")
    if window_end is None:
        raise ConfigError(
            "tushare.shibor 尚无成功批次，无法推出日更起点。请先用 "
            "quantagent ingest tushare shibor --start 回填"
        )
    _assert_ymd(window_end, field="window_end")
    start = _parse(window_end) - timedelta(days=DAILY_LOOKBACK_DAYS)
    if start.strftime(_YMD) > end_date:
        raise IngestError(f"日更起点 {start:%Y%m%d} 晚于 end_date {end_date}")
    return start.strftime(_YMD)


def resolve_daily_start(*, settings: Settings, end_date: str) -> str:
    """读 ``src_tushare._batch`` 的最近成功批次，算出日更起点。只读。"""
    conn = connect(settings, "src")
    try:
        window_end = latest_success_window_end(
            conn,
            pg_schema=SHIBOR.pg_schema,
            dataset=SHIBOR.dataset,
        )
    finally:
        conn.close()
    return daily_start_date(window_end, end_date=end_date)


def _persist_run_log(
    *,
    paths: VarPaths,
    started: datetime,
    seg_start: str,
    seg_end: str,
    write_db: bool,
    result: SrcFollowWriteResult | None,
    error: str | None,
) -> None:
    finished = datetime.now(UTC)
    status: Literal["success", "failure"] = "failure" if error is not None else "success"
    record = RunLog(
        action=ACTION,
        status=status,
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json(
            {
                "dataset": SHIBOR.dataset,
                "segment_start": seg_start,
                "segment_end": seg_end,
                "write_db": write_db,
            }
        ),
        output_digest=None if result is None else result.output_digest,
        row_count=0 if result is None else result.row_count,
        dml_count=0 if result is None else result.dml_count,
        error=error,
    )
    persist_run_log(record, paths)


def _assert_ymd(value: str, *, field: str) -> None:
    if len(value) != _YMD_LEN or not value.isdigit():
        raise IngestError(f"{field} 必须是 YYYYMMDD: {value!r}")
    _parse(value)


def _parse(value: str) -> date:
    try:
        return datetime.strptime(value, _YMD).replace(tzinfo=None).date()
    except ValueError as exc:
        raise IngestError(f"不是合法日期: {value!r}") from exc
