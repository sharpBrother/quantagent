"""Wind 一页写入：insert-only、显式替换、OPMODE=2。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import psycopg
import pytest

from quantagent.adapters.postgres.errors import TransactionUnknownError
from quantagent.ingest.errors import IngestError, ReadbackError, SourceFetchError
from quantagent.ingest.sources.wind.cursor import cursor_from_row
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.ingest.writers.tables import ASHAREEODPRICES
from quantagent.ingest.writers.wind_page import parse_opmode, write_wind_page
from quantagent.platform.config import Settings
from quantagent.platform.errors import WriteGateError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class FakeSrcStore:
    def __init__(
        self,
        *,
        hashes: dict[tuple[object, ...], str] | None = None,
        values: dict[tuple[object, ...], Mapping[str, object]] | None = None,
        cursor: str | None = None,
        readback: list[str] | None = None,
        commit_error: Exception | None = None,
    ) -> None:
        self.hashes = dict(hashes or {})
        self.values: dict[tuple[object, ...], Mapping[str, object]] = dict(values or {})
        self.cursor = cursor
        self._forced_readback = readback
        self.commit_error = commit_error
        self.deleted: list[tuple[object, ...]] = []
        self.inserted: list[Mapping[str, object]] = []
        self.batch_cursors: list[str | None] = []
        self.readback_calls: list[tuple[int, list[tuple[object, ...]]]] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self._last_hashes: list[str] = []

    def existing_keys(
        self,
        spec: object,
        keys: Sequence[tuple[object, ...]],
    ) -> set[tuple[object, ...]]:
        return set(self.hashes)

    def existing_hashes(
        self,
        spec: object,
        keys: Sequence[tuple[object, ...]],
    ) -> dict[tuple[object, ...], str]:
        return {key: self.hashes[key] for key in keys if key in self.hashes}

    def existing_values(
        self,
        spec: object,
        keys: Sequence[tuple[object, ...]],
        columns: Sequence[str],
    ) -> dict[tuple[object, ...], tuple[object, ...]]:
        return {
            key: tuple(self.values[key][name] for name in columns)
            for key in keys
            if key in self.values
        }

    def latest_source_cursor(self, spec: object) -> str | None:
        return self.cursor

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
        self.batch_cursors.append(source_cursor)
        self.cursor = source_cursor
        return 11

    def delete_keys(self, spec: object, keys: Sequence[tuple[object, ...]]) -> None:
        self.deleted.extend(keys)
        for key in keys:
            self.hashes.pop(key, None)

    def insert_rows(
        self,
        spec: object,
        rows: Sequence[Mapping[str, object]],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None:
        self.inserted.extend(rows)
        self._last_hashes = list(hashes)
        for row, digest in zip(rows, hashes, strict=True):
            self.hashes[(row["OBJECT_ID"],)] = digest

    def readback_hashes(
        self, spec: object, batch_id: int, keys: Sequence[tuple[object, ...]]
    ) -> list[str]:
        self.readback_calls.append((batch_id, list(keys)))
        if self._forced_readback is not None:
            return list(self._forced_readback)
        return list(self._last_hashes)

    def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollback_calls += 1


def _settings(*, allow_db_write: bool) -> Settings:
    return Settings(_env_file=None, allow_db_write=allow_db_write)


def _row(
    *,
    object_id: str = "oid-1",
    trade_dt: str = "20240102",
    opmode: str = "0",
    close: float = 10.0,
    status: str = "交易",
    opdate: datetime | None = None,
) -> dict[str, object]:
    payload = dict.fromkeys(ASHAREEODPRICES.native_columns)
    payload.update(
        {
            "OBJECT_ID": object_id,
            "S_INFO_WINDCODE": "000001.SZ",
            "TRADE_DT": trade_dt,
            "S_DQ_CLOSE": close,
            "S_DQ_TRADESTATUS": status,
            "OPDATE": opdate or datetime(2024, 1, 2, 16, 0, 0),
            "OPMODE": opmode,
        }
    )
    return payload


@pytest.mark.unit
def test_parse_opmode_accepts_int_str_bytes() -> None:
    assert parse_opmode(0) == 0
    assert parse_opmode("1") == 1
    assert parse_opmode(b"2") == 2
    with pytest.raises(SourceFetchError, match="非法"):
        parse_opmode("9")
    with pytest.raises(SourceFetchError, match="为空"):
        parse_opmode(None)


@pytest.mark.unit
def test_dry_run_does_not_touch_store() -> None:
    store = FakeSrcStore()
    row = _row()
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[row],
        settings=_settings(allow_db_write=False),
        write_db=False,
        store=store,
    )
    assert result.written is False
    assert result.inserted == 1
    assert result.dml_count == 0
    assert result.source_cursor == cursor_from_row(row).encode()
    assert store.commit_calls == 0
    assert store.batch_cursors == []


@pytest.mark.unit
def test_write_gate_blocks_wind_page() -> None:
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        write_wind_page(
            spec=ASHAREEODPRICES,
            rows=[_row()],
            settings=_settings(allow_db_write=False),
            write_db=True,
            store=FakeSrcStore(),
        )


@pytest.mark.unit
def test_insert_only_new_keys_commits_cursor() -> None:
    store = FakeSrcStore()
    row = _row()
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[row],
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
        now=lambda: datetime(2026, 9, 19, tzinfo=UTC),
    )
    assert result.written is True
    assert result.inserted == 1
    assert result.replaced == 0
    assert store.deleted == []
    assert store.commit_calls == 1
    assert store.batch_cursors == [cursor_from_row(row).encode()]
    assert result.dml_count == 2


@pytest.mark.unit
def test_same_hash_is_skipped_and_cursor_still_advances() -> None:
    row = _row()
    digest = row_hash(row, ASHAREEODPRICES.native_columns)
    store = FakeSrcStore(hashes={("oid-1",): digest})
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[row],
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
    )
    assert result.skipped == 1
    assert result.inserted == 0
    assert store.inserted == []
    assert store.deleted == []
    assert store.batch_cursors[-1] == cursor_from_row(row).encode()
    assert result.dml_count == 1


@pytest.mark.unit
def test_business_change_is_replaced_automatically() -> None:
    row = _row(close=11.0)
    store = FakeSrcStore(hashes={("oid-1",): "old"})
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[row],
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
    )
    assert (result.replaced, result.inserted, result.metadata_skipped) == (1, 0, 0)
    assert store.deleted == [("oid-1",)]
    assert store.inserted == [row]
    assert result.dml_count == 3
    assert store.commit_calls == 1
    # 回读只按本页写入的主键查，不扫全表。
    assert [keys for _, keys in store.readback_calls] == [[("oid-1",)]]


def _wind_resend(stored: dict[str, object]) -> dict[str, object]:
    """Wind 重发同一行：业务字段不变，只刷新系统列。"""
    resent = dict(stored)
    resent.update(
        {
            "OPDATE": datetime(2026, 11, 16, 15, 11, 9),
            "OPMODE": "1",
            "gsUTime": datetime(2026, 11, 16, 15, 25, 31),
        }
    )
    return resent


@pytest.mark.unit
def test_system_column_only_revision_is_skipped_not_written() -> None:
    stored = _row(close=10.0, opdate=datetime(2026, 7, 14, 15, 11, 45))
    store = FakeSrcStore(
        hashes={("oid-1",): row_hash(stored, ASHAREEODPRICES.native_columns)},
        values={("oid-1",): stored},
    )
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[_wind_resend(stored)],
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
    )
    assert result.metadata_skipped == 1
    assert (result.inserted, result.replaced, result.skipped) == (0, 0, 0)
    assert store.deleted == []
    assert store.inserted == []
    # 游标照常推进到本页最后一行。
    assert store.commit_calls == 1
    assert result.source_cursor == cursor_from_row(_wind_resend(stored)).encode()


@pytest.mark.unit
def test_system_column_only_revision_compares_decimals_by_value() -> None:
    # 库里 numeric(20,4) 读回 Decimal('10.5000')，源端可能给 Decimal('10.5')。
    stored = _row(opdate=datetime(2026, 7, 14, 15, 11, 45))
    stored["S_DQ_CLOSE"] = Decimal("10.5000")
    resent = _wind_resend(stored)
    resent["S_DQ_CLOSE"] = Decimal("10.5")
    store = FakeSrcStore(hashes={("oid-1",): "old"}, values={("oid-1",): stored})
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[resent],
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
    )
    assert result.metadata_skipped == 1
    assert store.inserted == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("column", "old", "new"),
    [
        # 2026-11-16 Wind 改写 601881.SH 整段后复权收盘，例如 20210305 由 9.3488 改为 9.2272。
        ("S_DQ_ADJCLOSE_BACKWARD", Decimal("9.3488"), Decimal("9.2272")),
        ("S_DQ_CLOSE", Decimal("10.00"), Decimal("10.01")),
    ],
)
def test_resend_with_business_change_follows_source(
    column: str, old: Decimal, new: Decimal
) -> None:
    stored = _row(opdate=datetime(2026, 7, 14, 15, 11, 45))
    stored[column] = old
    resent = _wind_resend(stored)
    resent[column] = new
    store = FakeSrcStore(hashes={("oid-1",): "old"}, values={("oid-1",): stored})
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[resent],
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
    )
    assert (result.replaced, result.metadata_skipped) == (1, 0)
    assert store.deleted == [("oid-1",)]
    assert store.inserted == [resent]
    assert store.commit_calls == 1


@pytest.mark.unit
def test_opmode_2_dry_run_counts_delete_without_store() -> None:
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[_row(opmode="2")],
        settings=_settings(allow_db_write=False),
        write_db=False,
        store=FakeSrcStore(),
    )
    assert (result.deleted, result.inserted, result.dml_count) == (1, 0, 0)


@pytest.mark.unit
def test_opmode_2_deletes_existing_key_without_insert() -> None:
    row = _row(opmode="2")
    digest = row_hash({**row, "OPMODE": "0"}, ASHAREEODPRICES.native_columns)
    store = FakeSrcStore(hashes={("oid-1",): digest})
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[row],
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
    )
    assert result.deleted == 1
    assert result.inserted == 0
    assert store.deleted == [("oid-1",)]
    assert store.inserted == []
    assert ("oid-1",) not in store.hashes


@pytest.mark.unit
def test_opmode_2_for_missing_key_issues_no_delete() -> None:
    store = FakeSrcStore()
    result = write_wind_page(
        spec=ASHAREEODPRICES,
        rows=[_row(opmode="2")],
        settings=_settings(allow_db_write=True),
        write_db=True,
        store=store,
    )
    assert result.deleted == 1
    assert store.deleted == []
    assert result.dml_count == 1


@pytest.mark.unit
def test_readback_mismatch_rolls_back() -> None:
    store = FakeSrcStore(readback=["deadbeef"])
    with pytest.raises(ReadbackError):
        write_wind_page(
            spec=ASHAREEODPRICES,
            rows=[_row()],
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
        write_wind_page(
            spec=ASHAREEODPRICES,
            rows=[_row()],
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=store,
        )
    assert store.commit_calls == 1
    assert store.rollback_calls == 0


@pytest.mark.unit
def test_readback_mismatch_reports_missing_keys() -> None:
    store = FakeSrcStore(readback=[])
    with pytest.raises(ReadbackError, match="缺失样例") as info:
        write_wind_page(
            spec=ASHAREEODPRICES,
            rows=[_row()],
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=store,
        )
    assert "oid-1" in str(info.value)
    assert store.rollback_calls == 1
    assert store.commit_calls == 0


class _RejectingInsertStore(FakeSrcStore):
    def insert_rows(self, *args: object, **kwargs: object) -> None:
        raise psycopg.errors.CharacterNotInRepertoire("invalid byte sequence")


@pytest.mark.unit
def test_pg_data_error_names_suspicious_value_and_rolls_back() -> None:
    row = _row()
    row["S_INFO_WINDCODE"] = b"\x8d"
    store = _RejectingInsertStore()
    with pytest.raises(IngestError, match=r"S_INFO_WINDCODE@\('oid-1',\)=bytes"):
        write_wind_page(
            spec=ASHAREEODPRICES,
            rows=[row],
            settings=_settings(allow_db_write=True),
            write_db=True,
            store=store,
        )
    assert store.rollback_calls == 1
    assert store.commit_calls == 0
