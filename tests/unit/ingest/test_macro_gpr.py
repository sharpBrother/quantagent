"""GPR 日频：解析（宽转长、版本、量化、列校验）、无更新跳过、跟随源端替换与 run log。零网络，假存储。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd
import pytest

from quantagent.adapters.postgres.src_progress import latest_written_value
from quantagent.adapters.postgres.src_targets import GPR_DAILY
from quantagent.ingest.errors import SourceFetchError, TargetNotAllowedError
from quantagent.ingest.jobs.macro_gpr import (
    GprStoredState,
    ingest_macro_gpr,
    select_changed_points,
)
from quantagent.ingest.sources.macro.gpr import (
    SOURCE_LABEL,
    GprPoint,
    _quantize,
    parse_gpr_daily_dta,
)
from quantagent.ingest.writers.src_follow import fingerprint_columns
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.ingest.writers.tables import assert_writable
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_NOW = datetime(2026, 1, 2, 11, 0, tzinfo=UTC)


def _to_dta(frame: pd.DataFrame, tmp_path: Path) -> bytes:
    path = tmp_path / "gpr.dta"
    frame.to_stata(path, write_index=False, version=118)
    return path.read_bytes()


def _base_frame() -> pd.DataFrame:
    """与真实文件同形：DAY 为字符串，GPRD* 为 float32，N10D 为 int16，另有 date 与 event。"""
    return pd.DataFrame(
        {
            "DAY": ["20240101", "20240102", "20240103"],
            "N10D": np.array([216, 315, 374], dtype=np.int16),
            "GPRD": np.array([230.5, 115.25, 97.0], dtype=np.float32),
            "GPRD_ACT": np.array([275.0, np.nan, 158.5], dtype=np.float32),
            "GPRD_THREAT": np.array([153.0, 87.5, 29.5], dtype=np.float32),
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "event": ["", "", ""],
        }
    )


def _points_by_series(payload: bytes) -> dict[str, dict[date, Decimal]]:
    parsed = parse_gpr_daily_dta(payload)
    grouped: dict[str, dict[date, Decimal]] = {}
    for point in parsed.points:
        grouped.setdefault(point.series_id, {})[point.observation_date] = point.value
    return grouped


@pytest.mark.unit
def test_wide_frame_becomes_one_series_per_numeric_column_and_nan_is_not_stored(
    tmp_path: Path,
) -> None:
    parsed = parse_gpr_daily_dta(_to_dta(_base_frame(), tmp_path))

    assert parsed.series_ids == ("N10D", "GPRD", "GPRD_ACT", "GPRD_THREAT")
    grouped = _points_by_series(_to_dta(_base_frame(), tmp_path))
    # GPRD_ACT 在 2024-01-02 为 NaN：不落行，也不补 0 或前值。
    assert date(2024, 1, 2) not in grouped["GPRD_ACT"]
    assert set(grouped["GPRD_ACT"]) == {date(2024, 1, 1), date(2024, 1, 3)}
    assert len(grouped["N10D"]) == 3
    # date 与 event 不是序列。
    assert not {"DATE", "EVENT", "DAY"} & set(grouped)


@pytest.mark.unit
def test_file_vintage_is_the_largest_day_even_when_rows_are_unsorted(tmp_path: Path) -> None:
    frame = _base_frame().iloc[::-1].reset_index(drop=True)
    parsed = parse_gpr_daily_dta(_to_dta(frame, tmp_path))

    assert parsed.file_vintage == date(2024, 1, 3)
    assert parsed.observation_min == date(2024, 1, 1)
    assert parsed.observation_max == date(2024, 1, 3)


@pytest.mark.unit
def test_file_sha256_is_taken_over_the_raw_bytes(tmp_path: Path) -> None:
    payload = _to_dta(_base_frame(), tmp_path)
    assert parse_gpr_daily_dta(payload).file_sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.unit
def test_values_quantize_to_eight_decimals_half_even(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "DAY": ["20240101", "20240102"],
            "GPRD_TEST": np.array([0.123456785, 0.123456795], dtype=np.float64),
        }
    )
    grouped = _points_by_series(_to_dta(frame, tmp_path))

    # 第 9 位为 5 时向偶数舍入：8 是偶数留住，9 是奇数进位。
    assert grouped["GPRD_TEST"][date(2024, 1, 1)] == Decimal("0.12345678")
    assert grouped["GPRD_TEST"][date(2024, 1, 2)] == Decimal("0.12345680")


@pytest.mark.unit
def test_float32_is_widened_to_float64_before_quantizing_like_wx2(tmp_path: Path) -> None:
    # wx2 历史值是 float32 加宽到 float64 后量化的结果，例如 275.19760132，而不是 float32 最短串 275.1976。
    frame = pd.DataFrame({"DAY": ["20240101"], "GPRD_ACT": np.array([275.1976], dtype=np.float32)})
    grouped = _points_by_series(_to_dta(frame, tmp_path))

    assert grouped["GPRD_ACT"][date(2024, 1, 1)] == Decimal("275.19760132")


@pytest.mark.unit
def test_non_finite_value_is_rejected_by_the_quantizer() -> None:
    # Stata 文件里写不进 inf，所以这条只能直接测取值函数。
    with pytest.raises(SourceFetchError, match="必须是有限值"):
        _quantize(float("inf"), series_id="GPRD", observation_date=date(2024, 1, 1))


@pytest.mark.unit
def test_unknown_non_numeric_column_is_rejected(tmp_path: Path) -> None:
    frame = _base_frame().assign(NOTE=["a", "b", "c"])
    with pytest.raises(SourceFetchError, match="未知非数值列 NOTE"):
        parse_gpr_daily_dta(_to_dta(frame, tmp_path))


@pytest.mark.unit
def test_unknown_numeric_column_becomes_a_series(tmp_path: Path) -> None:
    frame = _base_frame().assign(GPRD_NEW=np.array([1.0, 2.0, 3.0], dtype=np.float64))
    parsed = parse_gpr_daily_dta(_to_dta(frame, tmp_path))

    assert "GPRD_NEW" in parsed.series_ids


@pytest.mark.unit
@pytest.mark.parametrize(
    ("frame_edit", "message"),
    [
        (lambda f: f.drop(columns=["DAY"]), "缺少 DAY"),
        (lambda f: f.assign(DAY=["20240101", "20240101", "20240103"]), "DAY 有重复"),
        (lambda f: f.assign(DAY=["2024-01-01", "20240102", "20240103"]), "DAY 必须是 YYYYMMDD"),
        (lambda f: f.assign(DAY=["20241301", "20240102", "20240103"]), "不是合法日期"),
        (
            lambda f: f.assign(GPRD=np.array([1e10, 1.0, 1.0], dtype=np.float64)),
            "超过 numeric\\(18,8\\) 上限",
        ),
    ],
)
def test_structural_violations_stop_the_parse(
    tmp_path: Path, frame_edit: Any, message: str
) -> None:
    frame = frame_edit(_base_frame())
    with pytest.raises(SourceFetchError, match=message):
        parse_gpr_daily_dta(_to_dta(frame, tmp_path))


class FakeGprStore:
    """模拟 PostgresSrcStore 对 GPR 键的语义。记录所有调用，便于断言“没有写库”。"""

    def __init__(self) -> None:
        self.state: dict[tuple[object, ...], dict[str, Any]] = {}
        self.committed: dict[tuple[object, ...], dict[str, Any]] = {}
        self.calls: list[str] = []
        self.batches: list[int] = []
        self.next_batch = 1

    def _record(self, name: str) -> None:
        self.calls.append(name)

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
            key: tuple(self.state[key]["values"][name] for name in columns)
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
        self._record("insert_batch")
        batch_id = self.next_batch
        self.next_batch += 1
        self.batches.append(batch_id)
        return batch_id

    def delete_keys(self, spec: object, keys: Sequence[tuple[object, ...]]) -> None:
        self._record("delete_keys")
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
        self._record("insert_rows")
        for row, digest in zip(rows, hashes, strict=True):
            key = (row["series_id"], row["observation_date"], row["file_vintage"])
            self.state[key] = {
                "hash": digest,
                "values": dict(row),
                "batch": batch_id,
                "ingested_at": ingested_at,
            }

    def readback_hashes(
        self, spec: object, batch_id: int, keys: Sequence[tuple[object, ...]]
    ) -> list[str]:
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
            key = (row["series_id"], row["observation_date"], row["file_vintage"])
            stored = self.state.get(key)
            if stored is None or any(
                stored["values"][name] != row[name] for name in ("value", "file_sha256", "source")
            ):
                bad.append(key)
        return bad

    def commit(self) -> None:
        self._record("commit")
        self.committed = dict(self.state)

    def rollback(self) -> None:
        self._record("rollback")
        self.state = dict(self.committed)


def _state_from(store: FakeGprStore, file_vintage: date) -> GprStoredState:
    """与 ``_read_stored_state`` 同语义：每个键取 file_vintage 最大的一行，并列出本版本已有的键。"""
    latest: dict[tuple[str, date], tuple[date, Decimal | None]] = {}
    at_vintage: dict[tuple[str, date], tuple[Decimal | None, str]] = {}
    for key, entry in store.state.items():
        series_id = str(key[0])
        observed = cast("date", key[1])
        vintage = cast("date", key[2])
        values = entry["values"]
        value = cast("Decimal | None", values["value"])
        if vintage == file_vintage:
            at_vintage[(series_id, observed)] = (value, str(values["file_sha256"]))
        current = latest.get((series_id, observed))
        if current is None or vintage > current[0]:
            latest[(series_id, observed)] = (vintage, value)
    return GprStoredState(latest=latest, at_vintage=at_vintage)


def _empty_state(_: date) -> GprStoredState:
    return GprStoredState(latest={}, at_vintage={})


def _settings(tmp_path: Path, *, profile: str = "local") -> Settings:
    return Settings(
        _env_file=None,
        profile=profile,
        allow_db_write=True,
        var_root=tmp_path / "var",
    )


def _run_log_files(tmp_path: Path) -> list[dict[str, Any]]:
    paths = resolve_var_paths(_settings(tmp_path), repo_root=tmp_path)
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(paths.runs.glob("*.json"))]


@pytest.mark.unit
def test_first_run_inserts_every_row_under_one_batch_and_logs_it(tmp_path: Path) -> None:
    payload = _to_dta(_base_frame(), tmp_path)
    store = FakeGprStore()
    settings = _settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)

    result = ingest_macro_gpr(
        settings=settings,
        paths=paths,
        write_db=True,
        fetch=lambda: payload,
        last_file_sha256=lambda: None,
        store=store,
        stored_state=_empty_state,
        now=lambda: _NOW,
    )

    assert result.written is True
    assert result.unchanged is False
    assert result.row_count == 11  # 4 个序列：N10D 3 行、GPRD 3 行、GPRD_ACT 2 行、GPRD_THREAT 3 行
    assert result.inserted == 11
    assert result.replaced == 0
    assert result.batch_id == 1
    assert store.batches == [1]
    assert store.calls[-1] == "commit"
    assert result.file_vintage == date(2024, 1, 3)
    assert dict(result.series_rows) == {"N10D": 3, "GPRD": 3, "GPRD_ACT": 2, "GPRD_THREAT": 3}
    logged = _run_log_files(tmp_path)
    assert len(logged) == 1
    assert logged[0]["status"] == "success"
    assert logged[0]["inserted"] == 11
    assert logged[0]["file_vintage"] == "2024-01-03"


@pytest.mark.unit
def test_stored_row_carries_source_label_sha_and_vintage(tmp_path: Path) -> None:
    payload = _to_dta(_base_frame(), tmp_path)
    store = FakeGprStore()
    settings = _settings(tmp_path)

    ingest_macro_gpr(
        settings=settings,
        paths=resolve_var_paths(settings, repo_root=tmp_path),
        write_db=True,
        fetch=lambda: payload,
        last_file_sha256=lambda: None,
        store=store,
        stored_state=_empty_state,
        now=lambda: _NOW,
    )

    entry = store.state[("GPRD", date(2024, 1, 1), date(2024, 1, 3))]
    stored = entry["values"]
    assert stored["source"] == SOURCE_LABEL == "iacoviello.gpr_daily_recent"
    assert stored["file_sha256"] == hashlib.sha256(payload).hexdigest()
    assert stored["value"] == Decimal("230.50000000")
    # 采集时刻只经写入器参数落到 _ingested_at，行内不带 ingested_at。
    assert "ingested_at" not in stored
    assert entry["ingested_at"] == _NOW


@pytest.mark.unit
def test_same_file_sha_as_last_written_reports_no_update_and_touches_no_store(
    tmp_path: Path,
) -> None:
    payload = _to_dta(_base_frame(), tmp_path)
    sha = hashlib.sha256(payload).hexdigest()
    store = FakeGprStore()
    settings = _settings(tmp_path)

    result = ingest_macro_gpr(
        settings=settings,
        paths=resolve_var_paths(settings, repo_root=tmp_path),
        write_db=True,
        fetch=lambda: payload,
        last_file_sha256=lambda: sha,
        store=store,
        stored_state=_empty_state,
        now=lambda: _NOW,
    )

    assert result.unchanged is True
    assert result.written is False
    assert result.batch_id is None
    assert store.calls == []
    assert store.batches == []
    assert _run_log_files(tmp_path)[0]["unchanged"] is True


@pytest.mark.unit
def test_changed_content_on_same_vintage_replaces_the_whole_vintage_and_logs_it(
    tmp_path: Path,
) -> None:
    first = _to_dta(_base_frame(), tmp_path)
    revised_frame = _base_frame()
    revised_frame.loc[0, "GPRD"] = np.float32(999.0)
    second = _to_dta(revised_frame, tmp_path)
    store = FakeGprStore()
    settings = _settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)

    ingest_macro_gpr(
        settings=settings,
        paths=paths,
        write_db=True,
        fetch=lambda: first,
        last_file_sha256=lambda: None,
        store=store,
        stored_state=lambda v: _state_from(store, v),
        now=lambda: _NOW,
    )
    result = ingest_macro_gpr(
        settings=settings,
        paths=paths,
        write_db=True,
        fetch=lambda: second,
        last_file_sha256=lambda: hashlib.sha256(first).hexdigest(),
        store=store,
        stored_state=lambda v: _state_from(store, v),
        now=lambda: _NOW,
    )

    # 同一 file_vintage 的内容变了：file_sha256 是业务列，同一版本下每一行都视为变化，整键替换。
    assert result.written is True
    assert result.replaced == 11
    assert result.inserted == 0
    assert result.batch_id == 2
    assert store.state[("GPRD", date(2024, 1, 1), date(2024, 1, 3))]["values"]["value"] == (
        Decimal("999.00000000")
    )
    replay = _run_log_files(tmp_path)
    latest = max(replay, key=lambda item: item["started_at"])
    assert latest["replaced"] == 11


@pytest.mark.unit
def test_dry_run_counts_rows_without_touching_store(tmp_path: Path) -> None:
    payload = _to_dta(_base_frame(), tmp_path)
    store = FakeGprStore()
    settings = _settings(tmp_path)

    result = ingest_macro_gpr(
        settings=settings,
        paths=resolve_var_paths(settings, repo_root=tmp_path),
        write_db=False,
        fetch=lambda: payload,
        last_file_sha256=lambda: None,
        store=store,
        stored_state=_empty_state,
        now=lambda: _NOW,
    )

    assert result.written is False
    assert result.row_count == 11
    assert result.inserted == 0
    assert store.calls == []
    assert result.payload_digest is not None


@pytest.mark.unit
def test_failed_fetch_is_logged_and_reraised(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    def _boom() -> bytes:
        raise SourceFetchError("下载失败")

    with pytest.raises(SourceFetchError, match="下载失败"):
        ingest_macro_gpr(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            fetch=_boom,
            last_file_sha256=lambda: None,
        )
    logged = _run_log_files(tmp_path)
    assert logged[0]["status"] == "failure"
    assert "下载失败" in logged[0]["error"]


@pytest.mark.unit
def test_gpr_target_is_writable_only_on_local_profile() -> None:
    assert_writable(GPR_DAILY, profile="local")
    with pytest.raises(TargetNotAllowedError):
        assert_writable(GPR_DAILY, profile="office")


@pytest.mark.unit
def test_office_profile_is_refused_before_any_store_call(tmp_path: Path) -> None:
    payload = _to_dta(_base_frame(), tmp_path)
    store = FakeGprStore()
    settings = _settings(tmp_path, profile="office")

    with pytest.raises(TargetNotAllowedError):
        ingest_macro_gpr(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            write_db=True,
            fetch=lambda: payload,
            last_file_sha256=lambda: None,
            store=store,
            stored_state=_empty_state,
            now=lambda: _NOW,
        )
    assert store.calls == []


class _FakeCursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row
        self.statements: list[str] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, params: object = None) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _FakeConn:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._cursor = _FakeCursor(row)

    def cursor(self) -> _FakeCursor:
        return self._cursor


@pytest.mark.unit
def test_latest_written_value_reads_newest_batch_row_and_is_select_only() -> None:
    conn = _FakeConn(("abc",))
    value = latest_written_value(
        conn,  # type: ignore[arg-type]
        pg_schema="src_macro",
        table="gpr_daily",
        column="file_sha256",
    )
    assert value == "abc"
    statement = conn._cursor.statements[0]
    assert statement.startswith('SELECT "file_sha256" FROM "src_macro"."gpr_daily"')
    assert 'ORDER BY "_batch_id" DESC LIMIT 1' in statement


@pytest.mark.unit
def test_latest_written_value_is_none_for_empty_table() -> None:
    conn = _FakeConn(None)
    assert (
        latest_written_value(
            conn,  # type: ignore[arg-type]
            pg_schema="src_macro",
            table="gpr_daily",
            column="file_sha256",
        )
        is None
    )


@pytest.mark.unit
def test_row_hash_of_gpr_fingerprint_ignores_source_and_ingested_at() -> None:
    base: dict[str, object] = {
        "series_id": "GPRD",
        "observation_date": date(2024, 1, 1),
        "file_vintage": date(2024, 1, 3),
        "value": Decimal("1.00000000"),
        "file_sha256": "a" * 64,
        "source": "x",
        "ingested_at": datetime(2026, 1, 1),
    }
    other = {**base, "source": "y", "ingested_at": datetime(2027, 1, 1)}
    cols = fingerprint_columns(GPR_DAILY)
    assert row_hash(base, cols) == row_hash(other, cols)


def _point(series: str, observed: date, value: str) -> GprPoint:
    return GprPoint(series_id=series, observation_date=observed, value=Decimal(value))


@pytest.mark.unit
def test_select_changed_points_follows_the_four_rules() -> None:
    d1, d2 = date(2024, 1, 1), date(2024, 1, 2)
    stored = GprStoredState(
        latest={
            ("GPRD", d1): (date(2024, 1, 3), Decimal("230.50000000")),
            ("GPRD", d2): (date(2024, 1, 3), Decimal("115.25000000")),
        },
        at_vintage={("GPRD", d2): (Decimal("115.25000000"), "sha-b")},
    )
    points = [
        _point("GPRD", d1, "230.5"),  # 库里最新值相等（数值比较）：不写
        _point("GPRD", d2, "115.25"),  # 本版本已有同键行，值与 sha 都相同：不写
        _point("GPRD", date(2024, 1, 3), "9.0"),  # 库里没有该键：写
        _point("NEW", d1, "1.0"),  # 整个序列都是新的：写
    ]
    changed = select_changed_points(points, stored, file_sha256="sha-b")
    assert [(p.series_id, p.observation_date) for p in changed] == [
        ("GPRD", date(2024, 1, 3)),
        ("NEW", d1),
    ]


@pytest.mark.unit
def test_same_vintage_key_is_replaced_when_value_or_sha_differs() -> None:
    d1 = date(2024, 1, 1)
    stored = GprStoredState(
        latest={("GPRD", d1): (date(2024, 1, 3), Decimal("1.00000000"))},
        at_vintage={("GPRD", d1): (Decimal("1.00000000"), "sha-old")},
    )
    # 同一版本，值没变但文件 sha 变了：file_sha256 是业务列，整键替换。
    assert select_changed_points([_point("GPRD", d1, "1")], stored, file_sha256="sha-new") != []
    assert select_changed_points([_point("GPRD", d1, "1")], stored, file_sha256="sha-old") == []


@pytest.mark.unit
def test_select_changed_points_writes_when_latest_value_moved() -> None:
    d1 = date(2024, 1, 1)
    stored = GprStoredState(
        latest={("GPRD", d1): (date(2024, 1, 3), Decimal("1.00000000"))},
        at_vintage={},
    )
    assert select_changed_points([_point("GPRD", d1, "1.00000001")], stored, file_sha256="x") != []
    assert select_changed_points([_point("GPRD", d1, "1.00000000")], stored, file_sha256="x") == []


@pytest.mark.unit
def test_second_vintage_writes_only_changed_and_new_rows(tmp_path: Path) -> None:
    store = FakeGprStore()
    settings = _settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    first = _to_dta(_base_frame(), tmp_path)
    ingest_macro_gpr(
        settings=settings,
        paths=paths,
        write_db=True,
        fetch=lambda: first,
        last_file_sha256=lambda: None,
        stored_state=lambda v: _state_from(store, v),
        store=store,
        now=lambda: _NOW,
    )
    # 新文件多一天（2024-01-04），并且 2024-01-02 的 GPRD 被修订；其余数值与历史完全相同。
    second_frame = pd.DataFrame(
        {
            "DAY": ["20240101", "20240102", "20240103", "20240104"],
            "N10D": np.array([216, 315, 374, 111], dtype=np.int16),
            "GPRD": np.array([230.5, 116.0, 97.0, 60.0], dtype=np.float32),
            "GPRD_ACT": np.array([275.0, np.nan, 158.5, 40.0], dtype=np.float32),
            "GPRD_THREAT": np.array([153.0, 87.5, 29.5, 12.0], dtype=np.float32),
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
            "event": ["", "", "", ""],
        }
    )
    second = _to_dta(second_frame, tmp_path)
    result = ingest_macro_gpr(
        settings=settings,
        paths=paths,
        write_db=True,
        fetch=lambda: second,
        last_file_sha256=lambda: hashlib.sha256(first).hexdigest(),
        stored_state=lambda v: _state_from(store, v),
        store=store,
        now=lambda: _NOW,
    )
    new_vintage = date(2024, 1, 4)
    written = sorted((key[0], key[1]) for key in store.state if key[2] == new_vintage)
    # 修订的 GPRD 2024-01-02 + 新日期 2024-01-04 的四个序列（GPRD_ACT 与 N10D 等都有值）。
    assert written == [
        ("GPRD", date(2024, 1, 2)),
        ("GPRD", date(2024, 1, 4)),
        ("GPRD_ACT", date(2024, 1, 4)),
        ("GPRD_THREAT", date(2024, 1, 4)),
        ("N10D", date(2024, 1, 4)),
    ]
    assert result.row_count == 5
    # 修订后的 GPRD 2024-01-02 在新版本下是新键，所以也算插入。
    assert result.inserted == 5
    assert result.replaced == 0
    # 第二个文件共 15 个非缺失点，写了 5 个，其余 10 个是库里已有的相同值。
    assert result.unchanged_points == 15 - 5
    assert store.batches == [1, 2]


@pytest.mark.unit
def test_rerun_with_recorded_sha_missing_writes_nothing(tmp_path: Path) -> None:
    store = FakeGprStore()
    settings = _settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    payload = _to_dta(_base_frame(), tmp_path)
    ingest_macro_gpr(
        settings=settings,
        paths=paths,
        write_db=True,
        fetch=lambda: payload,
        last_file_sha256=lambda: None,
        stored_state=lambda v: _state_from(store, v),
        store=store,
        now=lambda: _NOW,
    )
    calls_before = list(store.calls)
    # 库里 sha 记录丢失（例如手工清过），但数值都已在库里：不登记批次，不写任何行。
    result = ingest_macro_gpr(
        settings=settings,
        paths=paths,
        write_db=True,
        fetch=lambda: payload,
        last_file_sha256=lambda: None,
        stored_state=lambda v: _state_from(store, v),
        store=store,
        now=lambda: _NOW,
    )
    assert result.unchanged is True
    assert result.written is False
    assert result.batch_id is None
    assert store.calls == calls_before
    assert result.unchanged_points == 11
