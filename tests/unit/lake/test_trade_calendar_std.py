"""std.trade_calendar 只做改名与类型，不改口径、不覆盖既有分区。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest

from quantagent.lake.materialize.trade_calendar import materialize_trade_calendar, src_rows_to_std
from quantagent.lake.partitions.layout import LakeLayoutError
from quantagent.platform.config import Settings
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
