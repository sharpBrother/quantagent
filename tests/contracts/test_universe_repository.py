"""UniverseRepository：memory 与 lake 对同一组行、同一个 as_of 行为一致。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.universe_member import LakeUniverseRepository
from quantagent.adapters.memory.universe_member import MemoryUniverseRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import EmptyDomainError, InvalidQueryError
from quantagent.domain.universe import UniverseMember

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.domain.ports.universe import UniverseRepository


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "mart.universe_member",
            "doc_ref": "docs/architecture/derived-datasets.md",
            "temporal_kind": "interval",
            "visibility": {
                "rule": "source_field",
                "field": "knowledge_dt",
                "grade": "B",
                "rationale": "契约测试用的可见性规则说明必须足够长",
            },
            "pit_recoverable": True,
        }
    )


_ROWS = (
    UniverseMember(
        universe_id="u1",
        asset_id="A0000",
        valid_from=date(2024, 1, 2),
        valid_to=date(2024, 3, 1),
        member_weight=None,
        knowledge_dt=date(2024, 1, 2),
        pit_grade="B",
    ),
    UniverseMember(
        universe_id="u1",
        asset_id="A0001",
        valid_from=date(2024, 1, 2),
        valid_to=None,
        member_weight=None,
        knowledge_dt=date(2024, 1, 15),
        pit_grade="B",
    ),
    UniverseMember(
        universe_id="u2",
        asset_id="A0002",
        valid_from=date(2024, 1, 2),
        valid_to=None,
        member_weight=0.5,
        knowledge_dt=date(2024, 1, 2),
        pit_grade="B",
    ),
)


def _write(path: Path) -> Path:
    table = pa.table(
        {
            "universe_id": [row.universe_id for row in _ROWS],
            "asset_id": [row.asset_id for row in _ROWS],
            "valid_from": pa.array([row.valid_from for row in _ROWS], type=pa.date32()),
            "valid_to": pa.array([row.valid_to for row in _ROWS], type=pa.date32()),
            "member_weight": pa.array([row.member_weight for row in _ROWS], type=pa.float64()),
            "knowledge_dt": pa.array([row.knowledge_dt for row in _ROWS], type=pa.date32()),
            "pit_grade": [row.pit_grade for row in _ROWS],
        }
    )
    dest = path / "part-00000.parquet"
    pq.write_table(table, dest)
    return path


def _members(repo: UniverseRepository, *, as_of: date, dt: date) -> tuple[UniverseMember, ...]:
    return repo.members_at(as_of=as_of, dt=dt, universe_id="u1")


@pytest.mark.contracts
def test_universe_memory_and_lake_match(tmp_path: Path) -> None:
    contract = _contract()
    memory = MemoryUniverseRepository(_ROWS, contract=contract)
    lake = LakeUniverseRepository(_write(tmp_path), contract=contract)
    as_of = date(2024, 1, 10)
    dt = date(2024, 2, 1)
    visible = _members(memory, as_of=as_of, dt=dt)
    assert [row.asset_id for row in visible] == ["A0000"]
    assert all(row.knowledge_dt <= as_of for row in visible)
    assert visible[0].valid_to == date(2024, 3, 1)
    assert visible[0].member_weight is None
    later = _members(memory, as_of=date(2024, 1, 15), dt=dt)
    assert [row.asset_id for row in later] == ["A0000", "A0001"]
    on_exit = _members(memory, as_of=date(2024, 1, 15), dt=date(2024, 3, 1))
    assert [row.asset_id for row in on_exit] == ["A0000", "A0001"]
    with pytest.raises(EmptyDomainError):
        _members(memory, as_of=as_of, dt=date(2024, 3, 2))
    with pytest.raises(EmptyDomainError):
        _members(memory, as_of=date(2024, 1, 1), dt=dt)
    with pytest.raises(InvalidQueryError):
        memory.members_at(as_of=as_of, dt=dt, universe_id=" ")
    assert _members(lake, as_of=as_of, dt=dt) == visible
    assert _members(lake, as_of=date(2024, 1, 15), dt=dt) == later
    assert _members(lake, as_of=date(2024, 1, 15), dt=date(2024, 3, 1)) == on_exit
