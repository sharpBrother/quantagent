"""PostgreSQL all_a 适配器：假连接，只验证 SQL 形态、PIT 截止与失败路径。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres import universe as universe_module
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import (
    EmptyDomainError,
    InvalidQueryError,
    MissingVisibilityError,
)

AS_OF = date(2024, 1, 5)


def _contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "src.wind.ashareeodderivativeindicator",
            "doc_ref": "docs/contracts/src-wind-first-batch.md",
            "temporal_kind": "point_event",
            "event_field": "TRADE_DT",
            "visibility": {
                "rule": "same_day_close",
                "grade": "A",
                "rationale": "单元测试用的衍生指标可见性规则说明足够长，满足校验",
            },
            "pit_recoverable": True,
        }
    )


def _conn(
    description: list[dict[str, object]],
    observed: list[dict[str, object]],
) -> MagicMock:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.side_effect = [description, observed]
    return conn


def _desc(
    code: str, listed: str | None, delisted: str | None, exchange: str | None
) -> dict[str, object]:
    return {
        "S_INFO_WINDCODE": code,
        "S_INFO_LISTDATE": listed,
        "S_INFO_DELISTDATE": delisted,
        "S_INFO_EXCHMARKET": exchange,
    }


def _obs(code: str) -> dict[str, object]:
    return {"S_INFO_WINDCODE": code}


@pytest.mark.unit
def test_members_are_read_with_readonly_sql_and_pit_fields() -> None:
    conn = _conn(
        description=[
            _desc("000002.SZ", "20000101", None, "SZSE"),
            _desc("000001.SZ", "20000101", None, "SZSE"),
        ],
        observed=[_obs("000001.SZ"), _obs("000002.SZ")],
    )
    members = PostgresUniverseRepository(conn, contract=_contract()).members_at(
        as_of=AS_OF,
        dt=AS_OF,
        universe_id="all_a",
    )
    cur = conn.cursor.return_value.__enter__.return_value
    statements = [call.args[0] for call in cur.execute.call_args_list]
    assert len(statements) == 2
    for statement in statements:
        assert statement.lstrip().upper().startswith("SELECT")
        assert "UPDATE" not in statement.upper()
        assert "INSERT" not in statement.upper()
    assert '"src_wind"."ASHAREDESCRIPTION"' in statements[0]
    assert '"src_wind"."ASHAREEODDERIVATIVEINDICATOR"' in statements[1]
    assert '"S_VAL_MV" IS NOT NULL' in statements[1]
    assert '"S_DQ_MV" IS NOT NULL' in statements[1]
    assert cur.execute.call_args_list[1].args[1] == ("20240105",)

    assert [m.asset_id for m in members] == ["000001.SZ", "000002.SZ"]
    for member in members:
        assert member.universe_id == "all_a"
        assert member.valid_from == AS_OF
        assert member.valid_to == AS_OF
        assert member.knowledge_dt == AS_OF
        assert member.member_weight is None
        assert member.pit_grade == "B"


@pytest.mark.unit
def test_dt_after_as_of_fails_without_touching_db() -> None:
    conn = MagicMock()
    with pytest.raises(EmptyDomainError):
        PostgresUniverseRepository(conn, contract=_contract()).members_at(
            as_of=date(2024, 1, 4),
            dt=date(2024, 1, 5),
            universe_id="all_a",
        )
    conn.cursor.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("universe_id", ["ashare", "ALL_A", ""])
def test_unknown_universe_id_is_rejected(universe_id: str) -> None:
    conn = MagicMock()
    with pytest.raises(InvalidQueryError):
        PostgresUniverseRepository(conn, contract=_contract()).members_at(
            as_of=AS_OF,
            dt=AS_OF,
            universe_id=universe_id,
        )
    conn.cursor.assert_not_called()


@pytest.mark.unit
def test_duplicate_observed_code_fails_closed() -> None:
    conn = _conn(
        description=[_desc("000001.SZ", "20000101", None, "SZSE")],
        observed=[_obs("000001.SZ"), _obs("000001.SZ")],
    )
    with pytest.raises(InvalidQueryError, match="同日代码重复"):
        PostgresUniverseRepository(conn, contract=_contract()).members_at(
            as_of=AS_OF,
            dt=AS_OF,
            universe_id="all_a",
        )


@pytest.mark.unit
def test_duplicate_description_code_fails_closed() -> None:
    conn = _conn(
        description=[
            _desc("000001.SZ", "20000101", None, "SZSE"),
            _desc("000001.SZ", "20000101", None, "SZSE"),
        ],
        observed=[_obs("000001.SZ")],
    )
    with pytest.raises(InvalidQueryError, match="代码重复"):
        PostgresUniverseRepository(conn, contract=_contract()).members_at(
            as_of=AS_OF,
            dt=AS_OF,
            universe_id="all_a",
        )


@pytest.mark.unit
def test_empty_date_string_is_invalid_not_null() -> None:
    conn = _conn(
        description=[_desc("000001.SZ", "", None, "SZSE")],
        observed=[_obs("000001.SZ")],
    )
    with pytest.raises(InvalidQueryError, match="S_INFO_LISTDATE"):
        PostgresUniverseRepository(conn, contract=_contract()).members_at(
            as_of=AS_OF,
            dt=AS_OF,
            universe_id="all_a",
        )


@pytest.mark.unit
def test_empty_result_fails_closed() -> None:
    conn = _conn(
        description=[_desc("000001.SZ", "20000101", None, "BSE")],
        observed=[_obs("000001.SZ")],
    )
    with pytest.raises(EmptyDomainError):
        PostgresUniverseRepository(conn, contract=_contract()).members_at(
            as_of=AS_OF,
            dt=AS_OF,
            universe_id="all_a",
        )


@pytest.mark.unit
def test_missing_visibility_contract_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        universe_module,
        "load_bundle",
        lambda: SimpleNamespace(visibilities={}),
    )
    conn = MagicMock()
    with pytest.raises(MissingVisibilityError):
        PostgresUniverseRepository(conn).members_at(
            as_of=AS_OF,
            dt=AS_OF,
            universe_id="all_a",
        )
    conn.cursor.assert_not_called()


@pytest.mark.unit
def test_description_is_cached_per_instance() -> None:
    conn = _conn(
        description=[_desc("000001.SZ", "20000101", None, "SZSE")],
        observed=[_obs("000001.SZ")],
    )
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.side_effect = [
        [_desc("000001.SZ", "20000101", None, "SZSE")],
        [_obs("000001.SZ")],
        [_obs("000001.SZ")],
    ]
    repo = PostgresUniverseRepository(conn, contract=_contract())
    repo.members_at(as_of=AS_OF, dt=AS_OF, universe_id="all_a")
    repo.members_at(as_of=AS_OF, dt=AS_OF, universe_id="all_a")
    statements = [call.args[0] for call in cur.execute.call_args_list]
    description_reads = [s for s in statements if "ASHAREDESCRIPTION" in s]
    assert len(description_reads) == 1
