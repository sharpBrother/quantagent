"""源镜像跟随源端写入器：插入、跳过、替换、元数据跳过、回读与提交的失败路径。"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.adapters.postgres.errors import TransactionUnknownError
from quantagent.adapters.postgres.src_targets import SHIBOR
from quantagent.ingest.errors import (
    DuplicateKeyError,
    IngestError,
    ReadbackError,
    TargetNotAllowedError,
)
from quantagent.ingest.writers.src_follow import (
    business_columns,
    fingerprint_columns,
    write_src_follow,
)
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.platform.config import Settings
from quantagent.platform.errors import WriteGateError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_NOW = datetime(2026, 1, 2, 11, 0, tzinfo=UTC)
_NAIVE_NOW = _NOW.replace(tzinfo=None)
_EARLIER = datetime(2025, 12, 31, 11, 0, tzinfo=UTC).replace(tzinfo=None)


class FakeShiborStore:
    """模拟 ``PostgresSrcStore`` 的语义。

    ``state`` 是当前可见数据；``committed`` 是最近一次成功提交的快照。
    ``rollback`` 把 ``state`` 恢复成快照，所以失败路径可以直接比较库状态。
    """

    def __init__(
        self,
        *,
        rows: Sequence[Mapping[str, object]] = (),
        commit_error: Exception | None = None,
        forced_readback: list[str] | None = None,
    ) -> None:
        self.state: dict[tuple[object, ...], dict[str, Any]] = {}
        for row in rows:
            key = (row["trade_date"], row["maturity"])
            self.state[key] = {
                "hash": row_hash(row, fingerprint_columns(SHIBOR)),
                "rate": row["rate"],
                "source": row["source"],
                "ingested_at": row["ingested_at"],
                "batch": 0,
            }
        self.committed = copy.deepcopy(self.state)
        self.commit_error = commit_error
        self.forced_readback = forced_readback
        self.batches: list[dict[str, Any]] = []
        self.deleted: list[tuple[object, ...]] = []
        self.inserted: list[Mapping[str, object]] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.next_batch = 7

    def existing_keys(
        self, spec: object, keys: Sequence[tuple[object, ...]]
    ) -> set[tuple[object, ...]]:
        return {key for key in keys if key in self.state}

    def latest_source_cursor(self, spec: object) -> str | None:
        return None

    def existing_hashes(
        self, spec: object, keys: Sequence[tuple[object, ...]]
    ) -> dict[tuple[object, ...], str]:
        return {key: self.state[key]["hash"] for key in keys if key in self.state}

    def existing_values(
        self,
        spec: object,
        keys: Sequence[tuple[object, ...]],
        columns: Sequence[str],
    ) -> dict[tuple[object, ...], tuple[object, ...]]:
        return {
            key: tuple(self.state[key][name] for name in columns)
            for key in keys
            if key in self.state
        }

    def insert_batch(
        self,
        *,
        spec: object,
        window_start: str | None,
        window_end: str | None,
        row_count: int,
        payload_digest: str,
        started_at: datetime,
        finished_at: datetime,
        source_cursor: str | None = None,
    ) -> int:
        batch_id = self.next_batch
        self.next_batch += 1
        self.batches.append(
            {"id": batch_id, "window_start": window_start, "window_end": window_end}
        )
        return batch_id

    def delete_keys(self, spec: object, keys: Sequence[tuple[object, ...]]) -> None:
        self.deleted.extend(keys)
        for key in keys:
            self.state.pop(key, None)

    def insert_rows(
        self,
        spec: object,
        rows: Sequence[Mapping[str, object]],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None:
        for row, digest in zip(rows, hashes, strict=True):
            key = (row["trade_date"], row["maturity"])
            self.state[key] = {
                "hash": digest,
                "rate": row["rate"],
                "source": row["source"],
                "ingested_at": row["ingested_at"],
                "batch": batch_id,
            }
        self.inserted.extend(rows)

    def readback_hashes(
        self, spec: object, batch_id: int, keys: Sequence[tuple[object, ...]]
    ) -> list[str]:
        if self.forced_readback is not None:
            return list(self.forced_readback)
        return [
            self.state[key]["hash"]
            for key in keys
            if key in self.state and self.state[key]["batch"] == batch_id
        ]

    def mismatched_rows(
        self, spec: object, batch_id: int, rows: Sequence[Mapping[str, object]]
    ) -> list[tuple[object, ...]]:
        bad: list[tuple[object, ...]] = []
        for row in rows:
            key = (row["trade_date"], row["maturity"])
            stored = self.state.get(key)
            if stored is None or stored["rate"] != row["rate"] or stored["source"] != row["source"]:
                bad.append(key)
        return bad

    def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = copy.deepcopy(self.state)

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.state = copy.deepcopy(self.committed)


def _settings(*, profile: str = "local", allow_db_write: bool = True) -> Settings:
    return Settings(_env_file=None, profile=profile, allow_db_write=allow_db_write)


def _row(
    trade_date: str = "20241101",
    maturity: str = "1m",
    rate: str = "1.8180",
    *,
    source: str = "tushare.shibor",
    ingested_at: datetime = _NAIVE_NOW,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "maturity": maturity,
        "rate": Decimal(rate),
        "source": source,
        "ingested_at": ingested_at,
    }


def _write(
    store: FakeShiborStore,
    rows: list[dict[str, object]],
    *,
    settings: Settings | None = None,
    write_db: bool = True,
) -> Any:
    return write_src_follow(
        spec=SHIBOR,
        rows=rows,
        settings=settings or _settings(),
        write_db=write_db,
        store=store,
        window_start="20241101",
        window_end="20241130",
        now=lambda: _NOW,
    )


@pytest.mark.unit
def test_column_split_excludes_system_columns_from_fingerprint() -> None:
    # 指纹与业务比较都不能含 source 与 ingested_at，否则每次采集都会被当成变化。
    assert business_columns(SHIBOR) == ("rate",)
    assert fingerprint_columns(SHIBOR) == ("trade_date", "maturity", "rate")


@pytest.mark.unit
def test_new_keys_are_inserted_and_batch_is_registered() -> None:
    store = FakeShiborStore()
    result = _write(store, [_row(maturity="1m"), _row(maturity="3m")])
    assert result.written is True
    assert (result.inserted, result.replaced, result.skipped) == (2, 0, 0)
    assert result.batch_id == 7
    assert result.dml_count == 2  # 批次登记 + 插入
    assert store.commit_calls == 1
    assert store.batches == [{"id": 7, "window_start": "20241101", "window_end": "20241130"}]
    assert set(store.state) == {("20241101", "1m"), ("20241101", "3m")}


@pytest.mark.unit
def test_identical_rows_are_skipped_but_batch_still_registered() -> None:
    # 无变化的日更也要登记批次，日更起点靠最近成功批次的 window_end 推出。
    existing = _row()
    store = FakeShiborStore(rows=[existing])
    result = _write(store, [_row()])
    assert (result.inserted, result.replaced, result.skipped) == (0, 0, 1)
    assert result.dml_count == 1
    assert store.deleted == []
    assert store.inserted == []
    assert len(store.batches) == 1
    assert store.commit_calls == 1


@pytest.mark.unit
def test_change_only_in_source_or_ingested_at_is_not_a_change() -> None:
    store = FakeShiborStore(rows=[_row(source="tushare.shibor", ingested_at=_EARLIER)])
    result = _write(store, [_row(source="tushare.shibor", ingested_at=_NAIVE_NOW)])
    assert (result.inserted, result.replaced, result.skipped) == (0, 0, 1)
    assert store.deleted == []


@pytest.mark.unit
def test_business_change_replaces_by_key_in_one_transaction() -> None:
    store = FakeShiborStore(rows=[_row(rate="1.8180")])
    result = _write(store, [_row(rate="1.8200")])
    assert (result.inserted, result.replaced, result.skipped) == (0, 1, 0)
    assert store.deleted == [("20241101", "1m")]
    assert store.state[("20241101", "1m")]["rate"] == Decimal("1.8200")
    assert result.dml_count == 3  # 批次 + 删除 + 插入
    assert store.commit_calls == 1


@pytest.mark.unit
def test_fingerprint_differs_but_values_equal_counts_as_metadata_skip() -> None:
    # 库里的指纹与当前算法不一致（例如算法升级前写入），但业务列逐列相等：不写库。
    store = FakeShiborStore(rows=[_row()])
    store.state[("20241101", "1m")]["hash"] = "f" * 64
    result = _write(store, [_row()])
    assert (result.inserted, result.replaced, result.skipped) == (0, 0, 0)
    assert result.metadata_skipped == 1
    assert store.deleted == []
    assert store.inserted == []


@pytest.mark.unit
def test_rows_missing_from_payload_are_not_deleted() -> None:
    # Tushare 没有删除标记。接口缺行不等于源端删除。
    store = FakeShiborStore(rows=[_row(maturity="1m"), _row(maturity="3m")])
    result = _write(store, [_row(maturity="1m")])
    assert result.skipped == 1
    assert ("20241101", "3m") in store.state
    assert store.deleted == []


@pytest.mark.unit
def test_fingerprint_readback_mismatch_rolls_back() -> None:
    store = FakeShiborStore(forced_readback=["0" * 64])
    before = copy.deepcopy(store.state)
    with pytest.raises(ReadbackError, match="回读不一致"):
        _write(store, [_row()])
    assert store.rollback_calls == 1
    assert store.commit_calls == 0
    assert store.state == before


@pytest.mark.unit
def test_column_readback_mismatch_rolls_back() -> None:
    # 指纹一致但某列被改坏：只有逐列核对能发现。
    store = FakeShiborStore()
    original = store.mismatched_rows

    def _corrupt(
        spec: object, batch_id: int, rows: Sequence[Mapping[str, object]]
    ) -> list[tuple[object, ...]]:
        store.state[("20241101", "1m")]["rate"] = Decimal("9.9999")
        return original(spec, batch_id, rows)

    store.mismatched_rows = _corrupt  # type: ignore[method-assign]
    before = copy.deepcopy(store.committed)
    with pytest.raises(ReadbackError, match="逐列核对不一致"):
        _write(store, [_row()])
    assert store.rollback_calls == 1
    assert store.commit_calls == 0
    assert store.committed == before


@pytest.mark.unit
def test_unknown_commit_is_not_retried_or_rolled_back() -> None:
    store = FakeShiborStore(commit_error=TransactionUnknownError("提交结果未知"))
    with pytest.raises(TransactionUnknownError):
        _write(store, [_row()])
    assert store.commit_calls == 1
    assert store.rollback_calls == 0


@pytest.mark.unit
def test_office_profile_is_rejected_before_touching_store() -> None:
    store = FakeShiborStore()
    with pytest.raises(TargetNotAllowedError, match="profile=office"):
        _write(store, [_row()], settings=_settings(profile="office"))
    assert store.commit_calls == 0
    assert store.batches == []


@pytest.mark.unit
def test_duplicate_payload_key_is_rejected() -> None:
    with pytest.raises(DuplicateKeyError, match="载荷内主键重复"):
        _write(FakeShiborStore(), [_row(), _row(rate="1.9000")])


@pytest.mark.unit
def test_dry_run_only_counts_and_does_not_touch_store() -> None:
    store = FakeShiborStore()
    result = _write(store, [_row(), _row(maturity="3m")], write_db=False)
    assert result.written is False
    assert result.row_count == 2
    assert result.dml_count == 0
    assert store.batches == []
    assert store.commit_calls == 0


@pytest.mark.unit
def test_write_gate_blocks_real_write_without_env_switch() -> None:
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        _write(FakeShiborStore(), [_row()], settings=_settings(allow_db_write=False))


@pytest.mark.unit
def test_ingested_at_must_match_writer_clock() -> None:
    store = FakeShiborStore()
    with pytest.raises(IngestError, match="ingested_at"):
        _write(store, [_row(ingested_at=_EARLIER)])
    assert store.batches == []


@pytest.mark.unit
def test_empty_payload_is_rejected() -> None:
    with pytest.raises(IngestError, match="载荷为空"):
        _write(FakeShiborStore(), [])
