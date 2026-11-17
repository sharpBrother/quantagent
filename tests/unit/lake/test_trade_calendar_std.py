"""std.trade_calendar 只做改名与类型，不改口径、不覆盖既有分区。"""

from __future__ import annotations

import hashlib
import os
from datetime import date
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest

from quantagent.lake.materialize.trade_calendar import materialize_trade_calendar, src_rows_to_std
from quantagent.lake.partitions.layout import LakeLayoutError
from quantagent.platform.config import Settings
from quantagent.platform.identity import digest_file
from quantagent.platform.storage.paths import VarPaths

if TYPE_CHECKING:
    from pathlib import Path

SRC_ROWS = (
    {
        "exchange": "SSE",
        "cal_date": "20260105",
        "is_open": 1,
        "pretrade_date": "20260102",
    },
    {
        "exchange": "SSE",
        "cal_date": "20260101",
        "is_open": 0,
        "pretrade_date": None,
    },
)


def _paths(root: Path) -> VarPaths:
    return VarPaths(
        root=root,
        lake=root / "lake",
        logs=root / "logs",
        runs=root / "logs" / "runs",
        cache=root / "cache",
    )


@pytest.mark.unit
def test_src_rows_to_std_renames_and_types() -> None:
    table = src_rows_to_std(SRC_ROWS)
    assert table.column_names == ["cal_dt", "exchange", "is_open", "prev_trade_dt"]
    assert table.num_rows == 2
    first = {name: table[name][0].as_py() for name in table.column_names}
    assert first["cal_dt"] == date(2026, 1, 1)
    assert first["is_open"] is False
    assert first["prev_trade_dt"] is None


@pytest.mark.unit
def test_null_is_open_is_not_filled() -> None:
    with pytest.raises(LakeLayoutError, match="is_open"):
        src_rows_to_std(
            [
                {
                    "exchange": "SSE",
                    "cal_date": "20260105",
                    "is_open": None,
                    "pretrade_date": None,
                }
            ]
        )


@pytest.mark.unit
def test_materialize_writes_parquet_and_refuses_overwrite(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    as_of = date(2026, 9, 17)
    first = materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=as_of,
        src_rows=SRC_ROWS,
    )
    assert first.path.exists()
    table = pq.read_table(first.path)
    assert table.num_rows == 2
    with pytest.raises(LakeLayoutError, match="拒绝覆盖"):
        materialize_trade_calendar(
            settings=settings,
            paths=paths,
            as_of=as_of,
            src_rows=SRC_ROWS,
        )
    second = materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=as_of,
        src_rows=SRC_ROWS,
        rebuild=True,
    )
    assert second.path.exists()
    assert second.rebuilt is True


@pytest.mark.unit
def test_skip_if_unchanged_does_not_touch_file_when_content_matches(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    as_of = date(2026, 9, 17)
    first = materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=as_of,
        src_rows=SRC_ROWS,
    )
    before = first.path.stat()
    before_sha = hashlib.sha256(first.path.read_bytes()).hexdigest()
    # 改写 mtime 为过去，若第二次误写文件，mtime 会变回当前时间。
    os.utime(first.path, ns=(before.st_atime_ns, before.st_mtime_ns - 10**10))
    before = first.path.stat()

    second = materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=as_of,
        src_rows=tuple(reversed(SRC_ROWS)),
        skip_if_unchanged=True,
    )

    assert second.rebuilt is False
    assert second.row_count == 2
    assert second.output_digest == digest_file(first.path)
    assert first.path.stat().st_mtime_ns == before.st_mtime_ns
    assert hashlib.sha256(first.path.read_bytes()).hexdigest() == before_sha


@pytest.mark.unit
def test_skip_if_unchanged_still_refuses_when_content_changed(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    as_of = date(2026, 9, 17)
    materialize_trade_calendar(settings=settings, paths=paths, as_of=as_of, src_rows=SRC_ROWS)
    changed = (
        *SRC_ROWS,
        {
            "exchange": "SSE",
            "cal_date": "20260106",
            "is_open": 1,
            "pretrade_date": "20260105",
        },
    )
    with pytest.raises(LakeLayoutError, match="拒绝覆盖"):
        materialize_trade_calendar(
            settings=settings,
            paths=paths,
            as_of=as_of,
            src_rows=changed,
            skip_if_unchanged=True,
        )
