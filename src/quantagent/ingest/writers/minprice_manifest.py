"""分钟源 manifest 的单日事务；仅写入固定的两张表。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from quantagent.adapters.postgres.errors import TransactionUnknownError
from quantagent.ingest.errors import ReadbackError, ReplaceRequiredError
from quantagent.platform.config import assert_db_write_allowed

if TYPE_CHECKING:
    from datetime import date

    from quantagent.ingest.writers.minprice_parquet import StagedPartition
    from quantagent.platform.config import Settings

_DATASET = "ashare_minute_bar"


def register_partition(
    conn: Any,
    *,
    partition: StagedPartition,
    trade_date: date,
    settings: Settings,
    expected_digest: str | None = None,
    source_table: str | None = None,
    write_db: bool = False,
) -> None:
    """锁住已有日记录，写后回读再提交；已有记录不自动覆盖。"""
    assert_db_write_allowed(settings=settings, write_db=write_db)
    source = source_table or ("m" + trade_date.strftime("%Y%m%d"))
    if source not in {"m" + trade_date.strftime("%Y%m%d"), "eastmoney.trends2"}:
        raise ValueError("分钟行情来源不在白名单")
    now = datetime.now(UTC)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT file_name, content_digest FROM src_minprice.lake_partition "
                "WHERE dataset = %s AND trade_date = %s FOR UPDATE",
                (_DATASET, trade_date),
            )
            old = cur.fetchone()
            if (old[1] if old is not None else None) != expected_digest:
                raise ReadbackError("分钟分区在处理期间被其他任务修改")
            if old is not None:
                raise ReplaceRequiredError("分钟分区已存在，禁止自动覆盖")
            cur.execute(
                "INSERT INTO src_minprice._batch "
                "(dataset, window_start, window_end, source_cursor, row_count, payload_digest, "
                "status, started_at, finished_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "RETURNING _batch_id",
                (
                    _DATASET,
                    str(trade_date),
                    str(trade_date),
                    source,
                    partition.row_count,
                    partition.content_digest,
                    "success",
                    now,
                    now,
                ),
            )
            batch_id = cur.fetchone()[0]
            expected = (
                _DATASET,
                trade_date,
                partition.file_name,
                partition.row_count,
                partition.code_count,
                partition.content_digest,
                partition.file_sha256,
                partition.file_bytes,
                source,
                batch_id,
                now,
            )
            cur.execute(
                "INSERT INTO src_minprice.lake_partition "
                "(dataset,trade_date,file_name,row_count,code_count,content_digest,file_sha256,"
                "file_bytes,source_table,_batch_id,_ingested_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                expected,
            )
            cur.execute(
                "SELECT dataset,trade_date,file_name,row_count,code_count,content_digest,"
                "file_sha256,file_bytes,source_table,_batch_id,_ingested_at "
                "FROM src_minprice.lake_partition WHERE dataset=%s AND trade_date=%s",
                (_DATASET, trade_date),
            )
            if cur.fetchone() != expected or cur.fetchone() is not None:
                raise ReadbackError("分钟分区 manifest 回读不一致")
            cur.execute(
                "SELECT dataset,row_count,payload_digest FROM src_minprice._batch WHERE _batch_id=%s",
                (batch_id,),
            )
            if cur.fetchone() != (_DATASET, partition.row_count, partition.content_digest):
                raise ReadbackError("分钟批次回读不一致")
    except BaseException:
        try:
            conn.rollback()
        except BaseException as exc:
            raise TransactionUnknownError("分钟分区回滚状态未知，禁止重试") from exc
        raise
    try:
        conn.commit()
    except BaseException as exc:
        raise TransactionUnknownError("分钟分区提交状态未知，禁止重试") from exc
