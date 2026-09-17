"""源表 insert-only 写入的六条铁律。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.errors import SrcConflictError, TransactionUnknownError
from quantagent.adapters.postgres.src_targets import SrcTableWriteSpec
from quantagent.ingest.errors import (
    DuplicateKeyError,
    EmptyPayloadError,
    ReadbackError,
    TargetNotAllowedError,
)
from quantagent.ingest.writers.src_insert import write_src_snapshot
from quantagent.ingest.writers.tables import TRADE_CAL, assert_writable
from quantagent.platform.config import Settings
from quantagent.platform.errors import WriteGateError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

ROWS = (
    {
        "exchange": "SSE",
        "cal_date": "20260105",
        "is_open": 1,
        "pretrade_date": "20260102",
    },
    {
        "exchange": "SZSE",
        "cal_date": "20260105",
        "is_open": 1,
        "pretrade_date": "20260102",
    },
)


class FakeSrcStore:
    def __init__(
        self,
        *,
        existing: set[tuple[object, ...]] | None = None,
        readback: list[str] | None = None,
        commit_error: Exception | None = None,
        rollback_error: Exception | None = None,
        conflict_on_insert: bool = False,
    ) -> None:
        self.existing = existing or set()
        self._forced_readback = readback
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.conflict_on_insert = conflict_on_insert
        self.existing_calls = 0
        self.insert_batch_calls = 0
        self.insert_row_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self.hashes: list[str] = []

    def existing_keys(
        self,
        spec: SrcTableWriteSpec,
        keys: Sequence[tuple[object, ...]],
    ) -> set[tuple[object, ...]]:
        self.existing_calls += 1
        return set(self.existing)

    def insert_batch(
        self,
        *,
        spec: SrcTableWriteSpec,
        window_start: str | None,
        window_end: str | None,
        row_count: int,
        payload_digest: str,
        started_at: datetime,
        finished_at: datetime,
    ) -> int:
        self.insert_batch_calls += 1
        return 7

    def insert_rows(
        self,
        spec: SrcTableWriteSpec,
        rows: Sequence[Mapping[str, object]],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None:
        self.insert_row_calls += 1
        if self.conflict_on_insert:
            raise SrcConflictError("pk")
        self.hashes = list(hashes)

    def readback_hashes(self, spec: SrcTableWriteSpec, batch_id: int) -> list[str]:
        if self._forced_readback is not None:
            return list(self._forced_readback)
        return list(self.hashes)

    def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self.rollback_error is not None:
            raise self.rollback_error


def _settings(*, allow_db_write: bool) -> Settings:
    return Settings(_env_file=None, allow_db_write=allow_db_write)


@pytest.mark.unit
def test_write_db_false_does_not_touch_store() -> None:
    store = FakeSrcStore()
    result = write_src_snapshot(
        spec=TRADE_CAL,
        rows=ROWS,
        settings=_settings(allow_db_write=False),
        write_db=False,
        store=store,
    )
    assert result.written is False
    assert result.dml_count == 0
    assert result.row_count == 2
    assert result.batch_id is None
    assert store.existing_calls == 0
    assert store.insert_batch_calls == 0
    assert store.insert_row_calls == 0
    assert store.commit_calls == 0


@pytest.mark.unit
def test_write_gate_blocks_before_any_insert() -> None:
    store = FakeSrcStore()
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        write_src_snapshot(
            spec=TRADE_CAL,
            rows=ROWS,
            settings=_settings(allow_db_write=False),
            write_db=True,
            store=store,
        )
    assert store.insert_batch_calls == 0
    assert store.insert_row_calls == 0


@pytest.mark.unit
def test_whitelist_rejects_other_tushare_table() -> None:
    spec = SrcTableWriteSpec(
        dataset="src.tushare.fund_share",
        pg_schema="src_tushare",
        pg_table="fund_share",
        native_columns=("ts_code", "trade_date"),
        keys=("ts_code", "trade_date"),
    )
    with pytest.raises(TargetNotAllowedError, match=r"禁写|白名单"):
        assert_writable(spec)
    with pytest.raises(TargetNotAllowedError):
        write_src_snapshot(
            spec=spec,
            rows=[{"ts_code": "1", "trade_date": "20260105"}],
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=FakeSrcStore(),
        )


@pytest.mark.unit
def test_forbidden_batch_table_is_explicit() -> None:
    spec = SrcTableWriteSpec(
        dataset="src.tushare.trade_cal",
        pg_schema="src_tushare",
        pg_table="_batch",
        native_columns=TRADE_CAL.native_columns,
        keys=TRADE_CAL.keys,
    )
    with pytest.raises(TargetNotAllowedError, match=r"禁写|不一致"):
        assert_writable(spec)


@pytest.mark.unit
def test_payload_duplicate_keys_fail_closed() -> None:
    dup = (ROWS[0], dict(ROWS[0]))
    with pytest.raises(DuplicateKeyError, match="载荷内主键重复"):
        write_src_snapshot(
            spec=TRADE_CAL,
            rows=dup,
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=FakeSrcStore(),
        )


@pytest.mark.unit
def test_existing_keys_are_not_overwritten() -> None:
    store = FakeSrcStore(existing={("SSE", "20260105")})
    with pytest.raises(DuplicateKeyError, match="已存在"):
        write_src_snapshot(
            spec=TRADE_CAL,
            rows=ROWS,
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=store,
        )
    assert store.insert_batch_calls == 0
    assert store.insert_row_calls == 0
    assert store.commit_calls == 0


@pytest.mark.unit
def test_readback_mismatch_rolls_back() -> None:
    store = FakeSrcStore(readback=["deadbeef"])
    with pytest.raises(ReadbackError, match="回读不一致"):
        write_src_snapshot(
            spec=TRADE_CAL,
            rows=ROWS,
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=store,
        )
    assert store.rollback_calls == 1
    assert store.commit_calls == 0


@pytest.mark.unit
def test_insert_conflict_rolls_back() -> None:
    store = FakeSrcStore(conflict_on_insert=True)
    with pytest.raises(DuplicateKeyError, match="已回滚"):
        write_src_snapshot(
            spec=TRADE_CAL,
            rows=ROWS,
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=store,
        )
    assert store.rollback_calls == 1
    assert store.commit_calls == 0


@pytest.mark.unit
def test_unknown_commit_does_not_retry() -> None:
    store = FakeSrcStore(commit_error=TransactionUnknownError("提交结果未知"))
    with pytest.raises(TransactionUnknownError, match="提交结果未知"):
        write_src_snapshot(
            spec=TRADE_CAL,
            rows=ROWS,
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=store,
        )
    assert store.commit_calls == 1
    assert store.rollback_calls == 0


@pytest.mark.unit
def test_unknown_rollback_does_not_retry() -> None:
    store = FakeSrcStore(
        readback=["nope"],
        rollback_error=TransactionUnknownError("回滚结果未知"),
    )
    with pytest.raises(TransactionUnknownError, match="回滚结果未知"):
        write_src_snapshot(
            spec=TRADE_CAL,
            rows=ROWS,
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=store,
        )
    assert store.rollback_calls == 1
    assert store.commit_calls == 0


@pytest.mark.unit
def test_empty_payload_fail_closed() -> None:
    with pytest.raises(EmptyPayloadError):
        write_src_snapshot(
            spec=TRADE_CAL,
            rows=[],
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=FakeSrcStore(),
        )


@pytest.mark.unit
def test_successful_write_commits_once() -> None:
    store = FakeSrcStore()
    clock = datetime(2026, 9, 17, tzinfo=UTC)
    result = write_src_snapshot(
        spec=TRADE_CAL,
        rows=ROWS,
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
        window_start="19900101",
        window_end="20260917",
        now=lambda: clock,
    )
    assert result.written is True
    assert result.batch_id == 7
    assert result.dml_count == 2
    assert result.row_count == 2
    assert store.insert_batch_calls == 1
    assert store.insert_row_calls == 1
    assert store.commit_calls == 1
    assert store.rollback_calls == 0
