"""CalendarRepository：memory 与 lake 对同一组行、同一个 as_of 行为一致。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.memory.calendar import MemoryCalendarRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.calendar.types import CalendarDay
from quantagent.domain.errors import EmptyDomainError

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.domain.ports.calendar import CalendarRepository

_ROWS = (
    CalendarDay(date(2026, 9, 11), "SSE", True, date(2026, 9, 10)),
    CalendarDay(date(2026, 9, 12), "SSE", False, date(2026, 9, 11)),
    CalendarDay(date(2026, 9, 14), "SSE", True, date(2026, 9, 11)),
    CalendarDay(date(2026, 9, 15), "SSE", True, date(2026, 9, 14)),
    CalendarDay(date(2026, 9, 14), "SZSE", True, date(2026, 9, 11)),
)


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "std.trade_calendar",
            "doc_ref": "docs/contracts/trade-calendar.md",
            "temporal_kind": "point_event",
            "event_field": "cal_dt",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "契约测试用的交易日历可见性规则说明足够长",
            },
            "pit_recoverable": True,
        }
    )


def _write_parquet(path: Path) -> Path:
    table = pa.table(
        {
            "cal_dt": pa.array([row.cal_dt for row in _ROWS], type=pa.date32()),
            "exchange": [row.exchange for row in _ROWS],
            "is_open": [row.is_open for row in _ROWS],
            "prev_trade_dt": pa.array(
                [row.prev_trade_dt for row in _ROWS],
                type=pa.date32(),
            ),
        }
    )
    dest = path / "part-00000.parquet"
    pq.write_table(table, dest)
    return path


def _assert_repo(repo: CalendarRepository) -> None:
    as_of = date(2026, 9, 14)
    visible = repo.list_days(
        as_of=as_of,
        exchange="SSE",
        start=date(2026, 9, 11),
        end=date(2026, 9, 15),
    )
    assert [row.cal_dt for row in visible] == [
        date(2026, 9, 11),
        date(2026, 9, 12),
        date(2026, 9, 14),
    ]
    assert all(row.exchange == "SSE" for row in visible)
    with pytest.raises(EmptyDomainError):
        repo.list_days(
            as_of=as_of,
            exchange="SSE",
            start=date(2026, 9, 15),
            end=date(2026, 9, 15),
        )


@pytest.mark.contracts
def test_memory_calendar_applies_same_day_close() -> None:
    _assert_repo(MemoryCalendarRepository(_ROWS, contract=_contract()))


@pytest.mark.contracts
def test_lake_calendar_matches_memory(tmp_path: Path) -> None:
    source = _write_parquet(tmp_path)
    lake = LakeCalendarRepository(source, contract=_contract())
    memory = MemoryCalendarRepository(_ROWS, contract=_contract())
    _assert_repo(lake)
    as_of = date(2026, 9, 14)
    assert lake.list_days(
        as_of=as_of,
        exchange="SSE",
        start=date(2026, 9, 11),
        end=date(2026, 9, 15),
    ) == memory.list_days(
        as_of=as_of,
        exchange="SSE",
        start=date(2026, 9, 11),
        end=date(2026, 9, 15),
    )
