from collections.abc import Iterator
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.errors import TransactionUnknownError
from quantagent.ingest.errors import ReadbackError, ReplaceRequiredError
from quantagent.ingest.writers.minprice_manifest import register_partition
from quantagent.ingest.writers.minprice_parquet import StagedPartition
from quantagent.platform.config import Settings


def fixture() -> tuple[MagicMock, Any, StagedPartition]:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    result = StagedPartition(
        "trade_date=2026-11-20/part-abc.parquet", 10, 1, "a" * 64, "b" * 64, 100
    )
    return conn, cur, result


def test_readback_mismatch_rolls_back() -> None:
    conn, cur, result = fixture()
    cur.fetchone.side_effect = [None, (1,), ("bad",)]
    with pytest.raises(ReadbackError):
        register_partition(
            conn,
            partition=result,
            trade_date=date(2026, 11, 20),
            settings=Settings(allow_db_write=True),
            write_db=True,
        )
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_rejects_concurrent_manifest_change() -> None:
    conn, cur, result = fixture()
    cur.fetchone.return_value = ("old.parquet", "c" * 64)
    with pytest.raises(ReadbackError, match="其他任务"):
        register_partition(
            conn,
            partition=result,
            trade_date=date(2026, 11, 20),
            settings=Settings(allow_db_write=True),
            expected_digest="d" * 64,
            write_db=True,
        )
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_existing_day_is_never_automatically_replaced() -> None:
    conn, cur, result = fixture()
    cur.fetchone.return_value = ("old.parquet", "c" * 64)
    with pytest.raises(ReplaceRequiredError):
        register_partition(
            conn,
            partition=result,
            trade_date=date(2026, 11, 20),
            settings=Settings(allow_db_write=True),
            expected_digest="c" * 64,
            write_db=True,
        )
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    assert not any(call.args[0].startswith("DELETE") for call in cur.execute.call_args_list)


def test_unknown_commit_is_not_retried_or_rolled_back() -> None:
    conn, cur, result = fixture()
    values: list[object] = []

    def execute(statement: str, params: object) -> None:
        if statement.startswith("INSERT INTO src_minprice.lake_partition"):
            values.append(params)

    cur.execute.side_effect = execute
    cur.fetchone.side_effect = lambda: [None, (1,), values[0], None].pop(0)

    # 使用 iterator 保持 fetchone 的调用顺序。
    def rows() -> Iterator[object]:
        yield None
        yield (1,)
        yield values[0]
        yield None
        yield ("ashare_minute_bar", result.row_count, result.content_digest)

    cur.fetchone.side_effect = rows()
    conn.commit.side_effect = OSError("unknown")
    with pytest.raises(TransactionUnknownError):
        register_partition(
            conn,
            partition=result,
            trade_date=date(2026, 11, 20),
            settings=Settings(allow_db_write=True),
            write_db=True,
        )
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
