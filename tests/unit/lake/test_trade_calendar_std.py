"""std.trade_calendar 的物化：整快照写入、远期截断、按日追加。日历用临时 Parquet，不连接数据库。"""

from __future__ import annotations

import hashlib
import os
from datetime import date
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.lake.materialize.trade_calendar import materialize_trade_calendar, src_rows_to_std
from quantagent.lake.partitions.layout import LakeLayoutError
from quantagent.platform.config import Settings
from quantagent.platform.identity import digest_file, digest_json
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

# 第一天的快照：2026-01-01 休市，01-02 开市，01-05 开市。
DAY1_ROWS = (
    {"exchange": "SSE", "cal_date": "20260101", "is_open": 0, "pretrade_date": None},
    {"exchange": "SSE", "cal_date": "20260102", "is_open": 1, "pretrade_date": None},
    {"exchange": "SSE", "cal_date": "20260105", "is_open": 1, "pretrade_date": "20260102"},
)
# 第二天的快照：源端在 DAY1 基础上新增 01-06，历史行不变。
DAY2_ROWS = (
    *DAY1_ROWS,
    {"exchange": "SSE", "cal_date": "20260106", "is_open": 1, "pretrade_date": "20260105"},
)


def _paths(root: Path) -> VarPaths:
    return VarPaths(
        root=root,
        lake=root / "lake",
        logs=root / "logs",
        runs=root / "logs" / "runs",
        cache=root / "cache",
    )


def _dest(paths: VarPaths) -> Path:
    return paths.lake / "std" / "trade_calendar"


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
def test_horizon_drops_rows_after_as_of_plus_days(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    rows = (
        *DAY1_ROWS,
        # as_of + 7 天 = 2026-01-12，恰好在边界上应保留。
        {"exchange": "SSE", "cal_date": "20260112", "is_open": 1, "pretrade_date": "20260105"},
        {"exchange": "SSE", "cal_date": "20260113", "is_open": 1, "pretrade_date": "20260112"},
        {"exchange": "SSE", "cal_date": "20400101", "is_open": 0, "pretrade_date": None},
    )
    result = materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=rows,
        horizon_days=7,
    )
    kept = pq.read_table(result.path)["cal_dt"].to_pylist()
    assert kept == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 12)]
    assert result.row_count == 4


@pytest.mark.unit
def test_horizon_that_leaves_no_rows_raises(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    with pytest.raises(LakeLayoutError, match="截断后为空"):
        materialize_trade_calendar(
            settings=settings,
            paths=paths,
            as_of=date(2026, 1, 1),
            src_rows=(
                {"exchange": "SSE", "cal_date": "20400101", "is_open": 0, "pretrade_date": None},
            ),
            horizon_days=7,
        )
    # 截断发生在写入之前，失败时不应创建目录。
    assert not _dest(paths).exists()


@pytest.mark.unit
def test_negative_horizon_raises(tmp_path: Path) -> None:
    with pytest.raises(LakeLayoutError, match="不能为负"):
        materialize_trade_calendar(
            settings=Settings(_env_file=None),
            paths=_paths(tmp_path),
            as_of=date(2026, 1, 5),
            src_rows=SRC_ROWS,
            horizon_days=-1,
        )


@pytest.mark.unit
def test_append_only_and_rebuild_together_raise(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(LakeLayoutError, match="互斥"):
        materialize_trade_calendar(
            settings=Settings(_env_file=None),
            paths=paths,
            as_of=date(2026, 1, 5),
            src_rows=SRC_ROWS,
            append_only=True,
            rebuild=True,
        )
    assert not _dest(paths).exists()


@pytest.mark.unit
def test_append_only_requires_horizon(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(LakeLayoutError, match="horizon_days"):
        materialize_trade_calendar(
            settings=Settings(_env_file=None),
            paths=paths,
            as_of=date(2026, 1, 5),
            src_rows=SRC_ROWS,
            append_only=True,
        )
    assert not _dest(paths).exists()


@pytest.mark.unit
def test_first_append_writes_part_00000(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = materialize_trade_calendar(
        settings=Settings(_env_file=None),
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=DAY1_ROWS,
        append_only=True,
        horizon_days=7,
    )
    shard = _dest(paths) / "part-00000.parquet"
    assert shard.is_file()
    assert result.rebuilt is False
    assert result.appended == 3
    assert result.row_count == 3
    assert result.output_digest == digest_file(shard)


@pytest.mark.unit
def test_next_day_appends_only_new_dates_and_leaves_existing_shard_untouched(
    tmp_path: Path,
) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=DAY1_ROWS,
        append_only=True,
        horizon_days=7,
    )
    first = _dest(paths) / "part-00000.parquet"
    before_sha = hashlib.sha256(first.read_bytes()).hexdigest()
    # 把 mtime 改到过去；若第二次误写 part-00000，mtime 会变回当前时间。
    old_ns = first.stat().st_mtime_ns - 10**10
    os.utime(first, ns=(first.stat().st_atime_ns, old_ns))

    result = materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 6),
        src_rows=DAY2_ROWS,
        append_only=True,
        horizon_days=7,
    )

    second = _dest(paths) / "part-00001.parquet"
    assert second.is_file()
    assert pq.read_table(second)["cal_dt"].to_pylist() == [date(2026, 1, 6)]
    assert result.appended == 1
    assert result.row_count == 1
    assert result.output_digest == digest_file(second)
    assert first.stat().st_mtime_ns == old_ns
    assert hashlib.sha256(first.read_bytes()).hexdigest() == before_sha


@pytest.mark.unit
def test_same_as_of_rerun_writes_nothing(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=DAY1_ROWS,
        append_only=True,
        horizon_days=7,
    )
    shard = _dest(paths) / "part-00000.parquet"
    before = shard.stat().st_mtime_ns

    result = materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=tuple(reversed(DAY1_ROWS)),
        append_only=True,
        horizon_days=7,
    )

    assert sorted(path.name for path in _dest(paths).glob("*.parquet")) == ["part-00000.parquet"]
    assert shard.stat().st_mtime_ns == before
    assert result.rebuilt is False
    assert result.appended == 0
    assert result.row_count == 0
    assert result.output_digest == digest_json([digest_file(shard)])


@pytest.mark.unit
def test_changed_is_open_on_written_row_raises_and_writes_nothing(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=DAY1_ROWS,
        append_only=True,
        horizon_days=7,
    )
    flipped = tuple(
        {**row, "is_open": 0} if row["cal_date"] == "20260105" else row for row in DAY2_ROWS
    )

    with pytest.raises(LakeLayoutError, match="发生变化") as info:
        materialize_trade_calendar(
            settings=settings,
            paths=paths,
            as_of=date(2026, 1, 6),
            src_rows=flipped,
            append_only=True,
            horizon_days=7,
        )

    assert "2026-01-05/SSE" in str(info.value)
    assert sorted(path.name for path in _dest(paths).glob("*.parquet")) == ["part-00000.parquet"]


@pytest.mark.unit
def test_changed_prev_trade_dt_on_written_row_raises(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=DAY1_ROWS,
        append_only=True,
        horizon_days=7,
    )
    moved = tuple(
        {**row, "pretrade_date": "20260101"} if row["cal_date"] == "20260105" else row
        for row in DAY2_ROWS
    )
    with pytest.raises(LakeLayoutError, match="发生变化"):
        materialize_trade_calendar(
            settings=settings,
            paths=paths,
            as_of=date(2026, 1, 6),
            src_rows=moved,
            append_only=True,
            horizon_days=7,
        )
    assert sorted(path.name for path in _dest(paths).glob("*.parquet")) == ["part-00000.parquet"]


@pytest.mark.unit
def test_source_deleting_a_written_date_raises(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=DAY1_ROWS,
        append_only=True,
        horizon_days=7,
    )
    # 源端删掉了 01-02，但新快照上限 01-06 已覆盖它。
    without_0102 = tuple(row for row in DAY2_ROWS if row["cal_date"] != "20260102")

    with pytest.raises(LakeLayoutError, match="源端删除") as info:
        materialize_trade_calendar(
            settings=settings,
            paths=paths,
            as_of=date(2026, 1, 6),
            src_rows=without_0102,
            append_only=True,
            horizon_days=7,
        )

    assert "2026-01-02/SSE" in str(info.value)
    assert sorted(path.name for path in _dest(paths).glob("*.parquet")) == ["part-00000.parquet"]


@pytest.mark.unit
def test_rerun_with_earlier_as_of_ignores_rows_beyond_snapshot_range(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 6),
        src_rows=DAY2_ROWS,
        append_only=True,
        horizon_days=7,
    )
    # 较早的 as_of 把快照截到 01-05；既有的 01-06 超出上限，不算源端删除。
    result = materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=DAY1_ROWS,
        append_only=True,
        horizon_days=0,
    )
    assert result.appended == 0
    assert sorted(path.name for path in _dest(paths).glob("*.parquet")) == ["part-00000.parquet"]


@pytest.mark.unit
def test_repository_reads_continuous_dates_across_shards(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    paths = _paths(tmp_path)
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 5),
        src_rows=DAY1_ROWS,
        append_only=True,
        horizon_days=7,
    )
    materialize_trade_calendar(
        settings=settings,
        paths=paths,
        as_of=date(2026, 1, 6),
        src_rows=DAY2_ROWS,
        append_only=True,
        horizon_days=7,
    )

    repo = LakeCalendarRepository(_dest(paths))
    days = repo.list_days(
        as_of=date(2026, 1, 6),
        exchange="SSE",
        start=date(2026, 1, 1),
        end=date(2026, 1, 6),
    )
    assert [day.cal_dt for day in days] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
    ]
