"""Tushare shibor：宽转长、按月分段、日更起点、分段提交与 run log。假 client，不联网。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest
from tests.unit.ingest.test_src_follow import FakeShiborStore

from quantagent.ingest.errors import IngestError, SourceFetchError
from quantagent.ingest.jobs.tushare_shibor import (
    daily_start_date,
    ingest_tushare_shibor,
    month_segments,
)
from quantagent.ingest.sources.tushare.shibor import (
    SHIBOR_MATURITIES,
    SOURCE_LABEL,
    shibor_wide_to_long,
)
from quantagent.platform.config import Settings
from quantagent.platform.errors import ConfigError, WriteGateError
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from pathlib import Path

_INGESTED = datetime(2026, 1, 2, 11, 0)
_NOW = datetime(2026, 1, 2, 11, 0, tzinfo=UTC)


def _wide_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """模拟 pro.shibor 的宽表；缺失的期限列为 NaN。"""
    return pd.DataFrame(rows, columns=["date", *SHIBOR_MATURITIES])


_DAY_1 = {
    "date": "20241101",
    "on": 1.36,
    "1w": 1.507,
    "2w": 1.768,
    "1m": 1.818,
    "3m": 1.879,
    "6m": 1.917,
    "9m": 1.933,
    "1y": 1.943,
}
_DAY_2 = {**_DAY_1, "date": "20241104", "1w": np.nan}


@pytest.mark.unit
def test_wide_to_long_expands_each_maturity_and_skips_empty_values() -> None:
    rows = shibor_wide_to_long(
        _wide_frame([_DAY_1, _DAY_2]),
        start_date="20241101",
        end_date="20241130",
        ingested_at=_INGESTED,
    )
    assert len(rows) == 8 + 7  # 第二天缺一个期限，不落行，也不补
    missing = [r for r in rows if r["trade_date"] == "20241104" and r["maturity"] == "1w"]
    assert missing == []
    first = rows[0]
    assert first == {
        "trade_date": "20241101",
        "maturity": "on",
        "rate": Decimal("1.3600"),
        "source": SOURCE_LABEL,
        "ingested_at": _INGESTED,
    }
    assert SOURCE_LABEL == "tushare.shibor"


@pytest.mark.unit
def test_wide_to_long_keeps_maturity_names_as_in_wx2() -> None:
    rows = shibor_wide_to_long(
        _wide_frame([_DAY_1]),
        start_date="20241101",
        end_date="20241101",
        ingested_at=_INGESTED,
    )
    assert {str(r["maturity"]) for r in rows} == {"on", "1w", "2w", "1m", "3m", "6m", "9m", "1y"}


@pytest.mark.unit
def test_wide_to_long_empty_frame_gives_no_rows() -> None:
    assert (
        shibor_wide_to_long(
            pd.DataFrame(),
            start_date="20241101",
            end_date="20241130",
            ingested_at=_INGESTED,
        )
        == []
    )


@pytest.mark.unit
def test_missing_maturity_column_is_fatal_not_empty() -> None:
    frame = _wide_frame([_DAY_1]).drop(columns=["9m"])
    with pytest.raises(SourceFetchError, match="缺列"):
        shibor_wide_to_long(
            frame, start_date="20241101", end_date="20241130", ingested_at=_INGESTED
        )


@pytest.mark.unit
def test_rate_with_more_than_four_decimals_is_rejected() -> None:
    frame = _wide_frame([{**_DAY_1, "1m": 1.81801}])
    with pytest.raises(SourceFetchError, match="超过 4 位小数"):
        shibor_wide_to_long(
            frame, start_date="20241101", end_date="20241130", ingested_at=_INGESTED
        )


@pytest.mark.unit
def test_date_outside_requested_window_is_rejected() -> None:
    with pytest.raises(SourceFetchError, match="请求区间之外"):
        shibor_wide_to_long(
            _wide_frame([_DAY_1]),
            start_date="20241201",
            end_date="20241231",
            ingested_at=_INGESTED,
        )


@pytest.mark.unit
def test_duplicate_date_is_rejected() -> None:
    with pytest.raises(SourceFetchError, match="重复 date"):
        shibor_wide_to_long(
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

    def shibor(self, *, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append((start_date, end_date))
        if self.fail_on == (start_date, end_date):
            raise RuntimeError("tushare 超时")
        return self.frames.get((start_date, end_date), pd.DataFrame())


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
    client = _FakeClient(
        {
            ("20241101", "20241130"): _wide_frame([_DAY_1]),
        }
    )
    result = ingest_tushare_shibor(
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
    assert result.row_count == 8
    assert result.empty_segments == ("20241201",)
    assert result.inserted == 0
    assert result.batch_ids == ()
    logs = _run_logs(tmp_path, settings)
    assert len(logs) == 2
    assert {log["status"] for log in logs} == {"success"}


@pytest.mark.unit
def test_each_segment_commits_in_its_own_transaction(tmp_path: Path) -> None:
    settings = _settings(tmp_path, allow_db_write=True)
    store = FakeShiborStore()
    client = _FakeClient(
        {
            ("20241101", "20241130"): _wide_frame([_DAY_1]),
            ("20241201", "20241231"): _wide_frame([{**_DAY_1, "date": "20241202"}]),
        }
    )
    result = ingest_tushare_shibor(
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
    assert result.inserted == 16
    assert result.dml_count == 4  # 每段两条：批次登记与插入
    assert len(_run_logs(tmp_path, settings)) == 2


@pytest.mark.unit
def test_failure_in_second_segment_keeps_first_and_logs_both(tmp_path: Path) -> None:
    settings = _settings(tmp_path, allow_db_write=True)
    store = FakeShiborStore()
    client = _FakeClient(
        {("20241101", "20241130"): _wide_frame([_DAY_1])},
        fail_on=("20241201", "20241231"),
    )
    with pytest.raises(RuntimeError, match="超时"):
        ingest_tushare_shibor(
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
    assert len(store.state) == 8
    assert client.calls == [("20241101", "20241130"), ("20241201", "20241231")]
    logs = _run_logs(tmp_path, settings)
    assert sorted(str(log["status"]) for log in logs) == ["failure", "success"]
    failure = next(log for log in logs if log["status"] == "failure")
    assert "超时" in str(failure["error"])


@pytest.mark.unit
def test_write_gate_blocks_real_write_before_any_commit(tmp_path: Path) -> None:
    settings = _settings(tmp_path, allow_db_write=False)
    store = FakeShiborStore()
    client = _FakeClient({("20241101", "20241130"): _wide_frame([_DAY_1])})
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        ingest_tushare_shibor(
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
        ingest_tushare_shibor(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            start_date="20250101",
            end_date="20241231",
            client=client,
        )
    assert client.calls == []
