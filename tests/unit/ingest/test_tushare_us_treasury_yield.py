"""Tushare us_tycr：宽转长、按月分段、日更起点、分段提交与 run log。假 client 与假存储，不联网。"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pytest

from quantagent.adapters.postgres.src_targets import US_TREASURY_YIELD
from quantagent.ingest.errors import IngestError, SourceFetchError, TargetNotAllowedError
from quantagent.ingest.jobs.tushare_us_treasury_yield import (
    daily_start_date,
    ingest_tushare_us_treasury_yield,
    month_segments,
)
from quantagent.ingest.sources.tushare.us_treasury_yield import (
    SOURCE_LABEL,
    US_TREASURY_MATURITIES,
    US_TYCR_MATURITY_COLUMNS,
    us_treasury_wide_to_long,
)
from quantagent.ingest.writers.src_follow import business_columns, write_src_follow
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.ingest.writers.tables import assert_writable
from quantagent.platform.config import Settings
from quantagent.platform.errors import ConfigError, WriteGateError
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_INGESTED = datetime(2026, 1, 2, 11, 0)
_NOW = datetime(2026, 1, 2, 11, 0, tzinfo=UTC)
_SOURCE_COLUMNS = [source for source, _ in US_TYCR_MATURITY_COLUMNS]


def _wide_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """模拟 pro.us_tycr 的宽表；缺失的期限列为 NaN。"""
    return pd.DataFrame(rows, columns=["date", *_SOURCE_COLUMNS])


_DAY_1 = {
    "date": "20241101",
    "m1": 4.75,
    "m2": 4.74,
    "m3": 4.61,
    "m4": 4.53,
    "m6": 4.42,
    "y1": 4.28,
    "y2": 4.21,
    "y3": 4.18,
    "y5": 4.22,
    "y7": 4.30,
    "y10": 4.37,
    "y20": 4.68,
    "y30": 4.57,
}
_DAY_2 = {**_DAY_1, "date": "20241104", "y3": np.nan}


@pytest.mark.unit
def test_maturity_mapping_matches_old_etl_and_wx2_labels() -> None:
    # 与旧仓 data/us_treasury_yield_etl.py 的 _MATURITY_COLUMNS、wx2 DISTINCT maturity 一致。
    assert US_TREASURY_MATURITIES == (
        "1m",
        "2m",
        "3m",
        "4m",
        "6m",
        "1y",
        "2y",
        "3y",
        "5y",
        "7y",
        "10y",
        "20y",
        "30y",
    )
    assert dict(US_TYCR_MATURITY_COLUMNS)["y10"] == "10y"


@pytest.mark.unit
def test_wide_to_long_expands_each_maturity_and_skips_empty_values() -> None:
    rows = us_treasury_wide_to_long(
        _wide_frame([_DAY_1, _DAY_2]),
        start_date="20241101",
        end_date="20241130",
        ingested_at=_INGESTED,
    )
    assert len(rows) == 13 + 12  # 第二天缺一个期限，不落行，也不补
    assert [r for r in rows if r["trade_date"] == "20241104" and r["maturity"] == "3y"] == []
    assert rows[0] == {
        "trade_date": "20241101",
        "maturity": "1m",
        "yield": Decimal("4.750"),
        "source": SOURCE_LABEL,
        "ingested_at": _INGESTED,
    }
    assert SOURCE_LABEL == "tushare.us_tycr"


@pytest.mark.unit
def test_wide_to_long_empty_frame_gives_no_rows() -> None:
    assert (
        us_treasury_wide_to_long(
            pd.DataFrame(),
            start_date="20241101",
            end_date="20241130",
            ingested_at=_INGESTED,
        )
        == []
    )


@pytest.mark.unit
def test_missing_maturity_column_is_fatal_not_empty() -> None:
    frame = _wide_frame([_DAY_1]).drop(columns=["y30"])
    with pytest.raises(SourceFetchError, match="缺列"):
        us_treasury_wide_to_long(
            frame, start_date="20241101", end_date="20241130", ingested_at=_INGESTED
        )


@pytest.mark.unit
def test_extra_interface_column_is_ignored() -> None:
    frame = _wide_frame([_DAY_1]).assign(y40=4.9)
    rows = us_treasury_wide_to_long(
        frame, start_date="20241101", end_date="20241130", ingested_at=_INGESTED
    )
    assert len(rows) == 13
    assert {str(r["maturity"]) for r in rows} == set(US_TREASURY_MATURITIES)


@pytest.mark.unit
def test_yield_with_more_than_three_decimals_is_rejected() -> None:
    frame = _wide_frame([{**_DAY_1, "y10": 4.3701}])
    with pytest.raises(SourceFetchError, match="超过 3 位小数"):
        us_treasury_wide_to_long(
            frame, start_date="20241101", end_date="20241130", ingested_at=_INGESTED
        )


@pytest.mark.unit
def test_date_outside_requested_window_is_rejected() -> None:
    with pytest.raises(SourceFetchError, match="请求区间之外"):
        us_treasury_wide_to_long(
            _wide_frame([_DAY_1]),
            start_date="20241201",
            end_date="20241231",
            ingested_at=_INGESTED,
        )


@pytest.mark.unit
def test_duplicate_date_is_rejected() -> None:
    with pytest.raises(SourceFetchError, match="重复 date"):
        us_treasury_wide_to_long(
            _wide_frame([_DAY_1, _DAY_1]),
            start_date="20241101",
            end_date="20241130",
            ingested_at=_INGESTED,
        )


@pytest.mark.unit
def test_month_segments_split_on_calendar_months() -> None:
    assert month_segments("20241115", "20250201") == [
        ("20241115", "20241130"),
        ("20241201", "20241231"),
        ("20250101", "20250131"),
        ("20250201", "20250201"),
    ]


@pytest.mark.unit
def test_month_segments_single_month_and_leap_february() -> None:
    assert month_segments("20240201", "20240229") == [("20240201", "20240229")]
    assert month_segments("20240101", "20240101") == [("20240101", "20240101")]


@pytest.mark.unit
def test_month_segments_reject_reversed_range() -> None:
    with pytest.raises(IngestError, match="晚于"):
        month_segments("20250101", "20241231")


@pytest.mark.unit
def test_daily_start_is_thirty_calendar_days_before_last_window_end() -> None:
    assert daily_start_date("20241130", end_date="20241201") == "20241031"


@pytest.mark.unit
def test_daily_start_without_successful_batch_refuses_to_guess() -> None:
    with pytest.raises(ConfigError, match="尚无成功批次"):
        daily_start_date(None, end_date="20241201")


@pytest.mark.unit
def test_daily_start_after_end_is_refused() -> None:
    # 起点 = 20241201 - 30 天 = 20241101，晚于 end_date 20241020。
    with pytest.raises(IngestError, match="晚于 end_date"):
        daily_start_date("20241201", end_date="20241020")


@pytest.mark.unit
def test_writer_only_accepts_local_profile_for_src_tushare() -> None:
    assert_writable(US_TREASURY_YIELD, profile="local")
    with pytest.raises(TargetNotAllowedError):
        assert_writable(US_TREASURY_YIELD, profile="office")


@pytest.mark.unit
def test_business_column_is_yield_only() -> None:
    assert business_columns(US_TREASURY_YIELD) == ("yield",)


class _FakeClient:
    """按 (start, end) 返回预置宽表；未预置的段返回空表。记录每次调用。"""

    def __init__(
        self,
        frames: dict[tuple[str, str], pd.DataFrame] | None = None,
        *,
        fail_on: tuple[str, str] | None = None,
    ) -> None:
        self.frames = frames or {}
        self.fail_on = fail_on
        self.calls: list[tuple[str, str]] = []

    def us_tycr(self, *, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append((start_date, end_date))
        if self.fail_on == (start_date, end_date):
            raise RuntimeError("tushare 超时")
        return self.frames.get((start_date, end_date), pd.DataFrame())


class _FakeUsStore:
    """模拟 ``PostgresSrcStore`` 的语义，只实现写入器用到的方法。
    ``state`` 是当前可见数据；``committed`` 是最近一次成功提交的快照；``rollback`` 恢复快照。
    """

    def __init__(self) -> None:
        self.state: dict[tuple[object, ...], dict[str, Any]] = {}
        self.committed: dict[tuple[object, ...], dict[str, Any]] = {}
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
        return batch_id

    def delete_keys(self, spec: object, keys: Sequence[tuple[object, ...]]) -> None:
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
                "yield": row["yield"],
                "source": row["source"],
                "ingested_at": row["ingested_at"],
                "batch": batch_id,
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
            key = (row["trade_date"], row["maturity"])
            stored = self.state.get(key)
            if stored is None or stored["yield"] != row["yield"]:
                bad.append(key)
        return bad

    def commit(self) -> None:
        self.commit_calls += 1
        self.committed = copy.deepcopy(self.state)

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.state = copy.deepcopy(self.committed)


def _settings(tmp_path: Path, *, allow_db_write: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        var_root=tmp_path / "var",
        allow_db_write=allow_db_write,
    )


def _run_logs(tmp_path: Path, settings: Settings) -> list[dict[str, object]]:
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(paths.runs.glob("*.json"))]


@pytest.mark.unit
def test_dry_run_segments_by_month_and_reports_empty_segments(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = _FakeClient({("20241101", "20241130"): _wide_frame([_DAY_1])})
    result = ingest_tushare_us_treasury_yield(
        settings=settings,
        paths=resolve_var_paths(settings, repo_root=tmp_path),
        start_date="20241101",
        end_date="20241231",
        client=client,
        now=lambda: _NOW,
    )
    assert client.calls == [("20241101", "20241130"), ("20241201", "20241231")]
    assert result.written is False
    assert result.segments == 2
    assert result.row_count == 13
    assert result.empty_segments == ("20241201",)
    assert result.inserted == 0
    assert result.batch_ids == ()
    logs = _run_logs(tmp_path, settings)
    assert len(logs) == 2
    assert {log["status"] for log in logs} == {"success"}


@pytest.mark.unit
def test_each_segment_commits_in_its_own_transaction(tmp_path: Path) -> None:
    settings = _settings(tmp_path, allow_db_write=True)
    store = _FakeUsStore()
    client = _FakeClient(
        {
            ("20241101", "20241130"): _wide_frame([_DAY_1]),
            ("20241201", "20241231"): _wide_frame([{**_DAY_1, "date": "20241202"}]),
        }
    )
    result = ingest_tushare_us_treasury_yield(
        settings=settings,
        paths=resolve_var_paths(settings, repo_root=tmp_path),
        write_db=True,
        start_date="20241101",
        end_date="20241231",
        client=client,
        store=store,
        now=lambda: _NOW,
    )
    assert store.commit_calls == 2
    assert len(result.batch_ids) == 2
    assert result.inserted == 26
    assert result.dml_count == 4  # 每段两条：批次登记与插入
    assert len(_run_logs(tmp_path, settings)) == 2


@pytest.mark.unit
def test_failure_in_second_segment_keeps_first_and_logs_both(tmp_path: Path) -> None:
    settings = _settings(tmp_path, allow_db_write=True)
    store = _FakeUsStore()
    client = _FakeClient(
        {("20241101", "20241130"): _wide_frame([_DAY_1])},
        fail_on=("20241201", "20241231"),
    )
    with pytest.raises(RuntimeError, match="超时"):
        ingest_tushare_us_treasury_yield(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            write_db=True,
            start_date="20241101",
            end_date="20241231",
            client=client,
            store=store,
            now=lambda: _NOW,
        )
    # 第一段已提交，保留；第二段没有写任何数据，也没有重试。
    assert store.commit_calls == 1
    assert len(store.state) == 13
    assert client.calls == [("20241101", "20241130"), ("20241201", "20241231")]
    logs = _run_logs(tmp_path, settings)
    assert sorted(str(log["status"]) for log in logs) == ["failure", "success"]
    failure = next(log for log in logs if log["status"] == "failure")
    assert "超时" in str(failure["error"])


@pytest.mark.unit
def test_write_gate_blocks_real_write_before_any_commit(tmp_path: Path) -> None:
    settings = _settings(tmp_path, allow_db_write=False)
    store = _FakeUsStore()
    client = _FakeClient({("20241101", "20241130"): _wide_frame([_DAY_1])})
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        ingest_tushare_us_treasury_yield(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            write_db=True,
            start_date="20241101",
            end_date="20241130",
            client=client,
            store=store,
            now=lambda: _NOW,
        )
    assert store.commit_calls == 0


@pytest.mark.unit
def test_reversed_range_is_refused_before_fetch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = _FakeClient()
    with pytest.raises(IngestError, match="晚于"):
        ingest_tushare_us_treasury_yield(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            start_date="20250101",
            end_date="20241231",
            client=client,
        )
    assert client.calls == []


@pytest.mark.unit
def test_rewrite_of_same_window_is_idempotent(tmp_path: Path) -> None:
    # 同窗重跑：指纹相同则跳过，不新增。与 SHIBOR 的幂等口径一致。
    settings = _settings(tmp_path, allow_db_write=True)
    store = _FakeUsStore()
    client = _FakeClient({("20241101", "20241130"): _wide_frame([_DAY_1])})
    kwargs: dict[str, Any] = {
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "write_db": True,
        "start_date": "20241101",
        "end_date": "20241130",
        "client": client,
        "store": store,
        "now": lambda: _NOW,
    }
    ingest_tushare_us_treasury_yield(**kwargs)
    second = ingest_tushare_us_treasury_yield(**kwargs)
    assert second.inserted == 0
    assert len(store.state) == 13
    assert store.state[("20241101", "1m")]["hash"] == row_hash(
        {
            "trade_date": "20241101",
            "maturity": "1m",
            "yield": Decimal("4.750"),
        },
        ("trade_date", "maturity", "yield"),
    )


@pytest.mark.unit
def test_write_src_follow_is_reused_unchanged_for_us_spec(tmp_path: Path) -> None:
    # 直接调用写入器也能走通：证明 US 规格只靠 native_columns 就接入了跟随源端的通用逻辑。
    settings = _settings(tmp_path, allow_db_write=True)
    store = _FakeUsStore()
    row = {
        "trade_date": "20241101",
        "maturity": "10y",
        "yield": Decimal("4.370"),
        "source": SOURCE_LABEL,
        "ingested_at": _NOW.replace(tzinfo=None),
    }
    result = write_src_follow(
        spec=US_TREASURY_YIELD,
        rows=[row],
        settings=settings,
        write_db=True,
        store=store,
        now=lambda: _NOW,
    )
    assert result.inserted == 1
