"""分钟源分区暂存；文件只有进入 manifest 后才能被研究读取。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from quantagent.domain.errors import EmptyDomainError
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.jobs.minprice_validation import content_digest, validate_day
from quantagent.platform.config import assert_db_write_allowed
from quantagent.platform.duck import duck_session
from quantagent.platform.identity import digest_file

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.ports.calendar import CalendarRepository
    from quantagent.platform.config import Settings
    from quantagent.platform.storage.paths import VarPaths

_DATASET_PATH = ("src", "minprice", "ashare_minute_bar")


@dataclass(frozen=True)
class StagedPartition:
    file_name: str
    row_count: int
    code_count: int
    content_digest: str
    file_sha256: str
    file_bytes: int


def stage_partition(
    table: pa.Table,
    *,
    trade_date: date,
    calendar: CalendarRepository,
    settings: Settings,
    paths: VarPaths,
    write_db: bool = False,
) -> StagedPartition:
    """只写唯一暂存文件并校验，提交清单必须由后续事务完成。"""
    assert_db_write_allowed(settings=settings, write_db=write_db)
    days = calendar.list_days(as_of=trade_date, exchange="SSE", start=trade_date, end=trade_date)
    if len(days) != 1 or days[0].cal_dt != trade_date or not days[0].is_open:
        raise EmptyDomainError(f"非交易日或日历不可用: {trade_date}")
    checked = validate_day(table, trade_date=trade_date)
    expected = content_digest(checked)
    root = paths.lake.joinpath(*_DATASET_PATH)
    directory = root / f"trade_date={trade_date.isoformat()}"
    directory.mkdir(parents=True, exist_ok=True)
    stage = directory / f".staging-{uuid.uuid4().hex}.parquet"
    pq.write_table(
        checked,
        stage,
        compression="zstd",
        compression_level=3,
        use_dictionary=["ts_code"],
        row_group_size=120_000,
        write_statistics=True,
        write_page_index=True,
    )
    with duck_session() as conn:
        retrieved = conn.execute(
            "SELECT * FROM read_parquet(?, hive_partitioning=false) ORDER BY ts_code, trade_time",
            [str(stage)],
        ).to_arrow_table()
    if retrieved.num_rows != checked.num_rows or content_digest(retrieved) != expected:
        raise SourceFetchError(f"分钟行情 Parquet 回读不一致: {trade_date}")
    dest = directory / f"part-{expected[:16]}.parquet"
    # hard link 不覆盖既有文件；残留文件留给 verify 人工核实。
    dest.hardlink_to(stage)
    stage.unlink()
    return StagedPartition(
        file_name=dest.relative_to(root).as_posix(),
        row_count=checked.num_rows,
        code_count=len(set(checked["ts_code"].to_pylist())),
        content_digest=expected,
        file_sha256=digest_file(dest),
        file_bytes=dest.stat().st_size,
    )
