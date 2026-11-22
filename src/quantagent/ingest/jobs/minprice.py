"""单日分钟源镜像任务。异常和未知事务状态均停止，不自动重试。"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from datetime import time as time_of_day
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import Field

from quantagent.ingest.errors import ReplaceRequiredError, SourceNotReadyError
from quantagent.ingest.jobs.minprice_corrections import correct_known_row
from quantagent.ingest.jobs.minprice_validation import content_digest, validate_day
from quantagent.ingest.sources.minprice import read_day
from quantagent.ingest.writers.minprice_manifest import register_partition
from quantagent.ingest.writers.minprice_parquet import stage_partition
from quantagent.platform.config import assert_db_write_allowed
from quantagent.platform.identity import digest_file
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Iterable

    from quantagent.domain.ports.calendar import CalendarRepository
    from quantagent.platform.config import Settings
    from quantagent.platform.storage.paths import VarPaths

_NAMES = ("ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount")
_EXPECTED_BARS = 241
_SCHEMA = pa.schema(
    [
        ("ts_code", pa.string()),
        ("trade_time", pa.timestamp("us")),
        *[(name, pa.decimal128(20, 4)) for name in _NAMES[2:]],
    ]
)


class MinuteRunLog(RunLog):
    trade_date: date
    unusual_bar_counts: dict[str, int] = Field(default_factory=dict)
    tolerated_open_below_low: list[dict[str, str]] = Field(default_factory=list)
    source_corrections: list[dict[str, str]] = Field(default_factory=list)
    outcome: str = "unknown"


def assert_daily_ready(table: pa.Table, previous_code_count: int) -> None:
    """当前数据至少到 15:00，股票数不低于上一个交易日的 95%。"""
    if previous_code_count <= 0 or table.num_rows == 0:
        raise SourceNotReadyError("上一交易日股票数不可用或当日无行情")
    latest = pc.max(table["trade_time"]).as_py()
    codes = len(pc.unique(table["ts_code"]))
    if latest.time() != time_of_day(15) or codes * 100 < previous_code_count * 95:
        raise SourceNotReadyError("当日分钟行情尚未出齐")


def ingest_day(  # noqa: PLR0912, PLR0915
    mysql: Any,
    pg: Any,
    *,
    trade_date: date,
    settings: Settings,
    paths: VarPaths,
    calendar: CalendarRepository,
    previous_code_count: int | None = None,
    source_batches: Iterable[list[Any]] | None = None,
    source_table: str | None = None,
    write_db: bool = False,
) -> str:
    """处理一个日期，写入前完成内容验证；已有相同 digest 不重复写。"""
    if (source_batches is None and source_table is not None) or (
        source_batches is not None and source_table != "eastmoney.trends2"
    ):
        raise ValueError("分钟行情来源和输入不匹配")
    if write_db:
        assert_db_write_allowed(settings=settings, write_db=True)
    started = datetime.now(UTC)
    started_clock = time.monotonic()
    input_digest: str | None = None
    original_input_digest: str | None = None
    output_digest: str | None = None
    row_count: int | None = None
    dml_count = 0
    failure: str | None = None
    outcome = "failed"
    unusual_bar_counts: dict[str, int] = {}
    tolerated_open_below_low: list[dict[str, str]] = []
    source_corrections: list[dict[str, str]] = []
    try:
        table_name = "m" + trade_date.strftime("%Y%m%d")
        batches = []
        source = (
            source_batches
            if source_batches is not None
            else read_day(mysql, database=settings.minprice_mysql_database, table=table_name)
        )
        for rows in source:
            arrays = [
                pa.array([row[i] for row in rows], type=field.type)
                for i, field in enumerate(_SCHEMA)
            ]
            batches.append(pa.RecordBatch.from_arrays(arrays, schema=_SCHEMA))
        table = pa.Table.from_batches(batches, schema=_SCHEMA)
        corrected, source_corrections = correct_known_row(
            table, trade_date=trade_date, is_mysql=source_batches is None
        )
        if source_corrections:
            source_dates = pa.array([trade_date] * table.num_rows, type=pa.date32())
            original_input_digest = content_digest(table.append_column("trade_date", source_dates))
        table = corrected
        checked = validate_day(table, trade_date=trade_date)
        tolerated = checked.filter(pc.less(checked["open"], checked["low"]))
        tolerated_open_below_low = [
            {key: str(value) for key, value in item.items()}
            for item in tolerated.select(["ts_code", "trade_time", "open", "low"]).to_pylist()
        ]
        if previous_code_count is not None:
            assert_daily_ready(checked, previous_code_count)
        row_count = checked.num_rows
        counts = checked.group_by("ts_code").aggregate([("ts_code", "count")]).to_pylist()
        unusual_bar_counts = {
            item["ts_code"]: item["ts_code_count"]
            for item in counts
            if item["ts_code_count"] != _EXPECTED_BARS
        }
        input_digest = content_digest(checked)
        if not write_db:
            return "dry_run"
        with pg.cursor() as cur:
            cur.execute(
                "SELECT content_digest,file_name,row_count,file_sha256 FROM src_minprice.lake_partition "
                "WHERE dataset=%s AND trade_date=%s",
                ("ashare_minute_bar", trade_date),
            )
            existing = cur.fetchone()
        if existing is not None and existing[0] == input_digest:
            root = (paths.lake / "src" / "minprice" / "ashare_minute_bar").resolve()
            existing_path = (root / existing[1]).resolve()
            if (
                not existing_path.is_relative_to(root)
                or not existing_path.is_file()
                or pq.ParquetFile(existing_path).metadata.num_rows != existing[2]
                or digest_file(existing_path) != existing[3]
            ):
                raise ValueError("已登记分钟分区缺失或校验失败，不可跳过")
            output_digest = input_digest
            outcome = "skipped"
            return "skipped"
        if existing is not None:
            raise ReplaceRequiredError("分钟分区已存在且内容不同，禁止自动覆盖")
        partition = stage_partition(
            table,
            trade_date=trade_date,
            calendar=calendar,
            settings=settings,
            paths=paths,
            write_db=True,
        )
        register_partition(
            pg,
            partition=partition,
            trade_date=trade_date,
            settings=settings,
            expected_digest=None if existing is None else existing[0],
            source_table=source_table,
            write_db=True,
        )
        output_digest = partition.content_digest
        dml_count = 2
        outcome = "inserted"
        return "inserted"
    except SourceNotReadyError:
        outcome = "not_ready"
        raise
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if write_db:
            finished = datetime.now(UTC)
            record = MinuteRunLog(
                trade_date=trade_date,
                outcome=outcome,
                unusual_bar_counts=unusual_bar_counts,
                tolerated_open_below_low=tolerated_open_below_low,
                source_corrections=source_corrections,
                action="ingest.minprice.day",
                status="failure" if failure else "success",
                started_at=started,
                finished_at=finished,
                elapsed_ms=int((time.monotonic() - started_clock) * 1000),
                input_digest=original_input_digest or input_digest,
                output_digest=output_digest,
                row_count=row_count,
                dml_count=dml_count,
                error=failure,
            )
            persist_run_log(record, paths)
