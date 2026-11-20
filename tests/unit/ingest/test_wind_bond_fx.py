"""债券曲线、债券回购与外汇的 Wind 接入：分页过滤、写入白名单、规格与 0019 DDL 一致。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.adapters.postgres.migrate import list_migration_files, split_sql_statements
from quantagent.adapters.postgres.src_targets import BOND_FX_WIND_SPECS
from quantagent.adapters.postgres.wind_bond_fx_columns import BOND_FX_WIND_SYNC
from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.wind.cursor import WindCursor
from quantagent.ingest.sources.wind.paged import (
    PymssqlWindPageSource,
    build_page_params,
    build_page_sql,
)
from quantagent.ingest.sources.wind.tables import WIND_PAGED_TABLES, resolve_wind_paged_table
from quantagent.ingest.writers.tables import assert_writable

if TYPE_CHECKING:
    from pathlib import Path

_TECH = {"_batch_id", "_ingested_at", "_row_hash"}
_CURVE_CNBD_FILTER = (
    ("B_ANAL_CURVENUMBER", (1232,)),
    ("B_ANAL_CURVETERM", (1, 2, 3, 5, 7, 10, 0.08, 0.17, 0.25, 0.5)),
)
_CURVE_CSI_FILTER = (("B_ANAL_CURVENUMBER", ("0901", "02502")),)


def _last_create_columns(repo_root: Path) -> dict[str, list[str]]:
    """每张表取最后一次 CREATE TABLE 的列，与 0019 之后的真实 DDL 对齐。"""
    tables: dict[str, list[str]] = {}
    for item in list_migration_files(repo_root, "src"):
        for stmt in split_sql_statements(item.path.read_text(encoding="utf-8")):
            match = re.match(r'CREATE TABLE src_wind\."(\w+)" \((.*)\)$', stmt, re.S)
            if match is None:
                continue
            cols = re.findall(r'^\s*"?(\w+)"?\s+\w', match.group(2), re.M)
            tables[match.group(1)] = [c for c in cols if c != "PRIMARY"]
    return tables


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]], log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows = rows
        self._log = log

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[Any, ...]) -> None:
        self._log.append((statement, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.log: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self, as_dict: bool = False) -> _FakeCursor:
        return _FakeCursor(self.rows, self.log)


_CURSOR = WindCursor(datetime(2024, 1, 2), "oid-1")


@pytest.mark.unit
def test_page_sql_without_filter_is_unchanged() -> None:
    sql = build_page_sql(table="CBONDREPO", columns=("OBJECT_ID", "OPDATE"), limit=100)
    assert sql == (
        "SELECT TOP (100) [OBJECT_ID], [OPDATE] FROM [dbo].[CBONDREPO] "
        "WHERE [OPDATE] IS NOT NULL AND [OBJECT_ID] IS NOT NULL "
        "AND ([OPDATE] > %s OR ([OPDATE] = %s AND [OBJECT_ID] > %s)) "
        "ORDER BY [OPDATE], [OBJECT_ID]"
    )
    assert build_page_params(_CURSOR) == (_CURSOR.opdate, _CURSOR.opdate, "oid-1")


@pytest.mark.unit
def test_page_sql_filter_uses_placeholders_and_keeps_cursor_order() -> None:
    sql = build_page_sql(
        table="CBONDCURVECNBD",
        columns=("OBJECT_ID", "B_ANAL_CURVENUMBER"),
        limit=10,
        source_filter=_CURVE_CNBD_FILTER,
    )
    # 过滤值不得拼进 SQL 文本，只能是占位符。
    assert "1232" not in sql
    assert "0.08" not in sql
    assert "AND [B_ANAL_CURVENUMBER] IN (%s)" in sql
    assert "AND [B_ANAL_CURVETERM] IN (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)" in sql
    assert sql.index("[OBJECT_ID] > %s))") < sql.index("[B_ANAL_CURVENUMBER] IN")
    assert sql.index("[B_ANAL_CURVENUMBER] IN") < sql.index("ORDER BY")
    params = build_page_params(_CURSOR, _CURVE_CNBD_FILTER)
    assert params == (
        _CURSOR.opdate,
        _CURSOR.opdate,
        "oid-1",
        1232,
        1,
        2,
        3,
        5,
        7,
        10,
        0.08,
        0.17,
        0.25,
        0.5,
    )
    # 占位符数与参数数必须一致，否则 pymssql 会在运行时报错。
    assert sql.count("%s") == len(params)


@pytest.mark.unit
def test_page_sql_filter_rejects_bad_column_and_empty_values() -> None:
    with pytest.raises(SourceFetchError, match="过滤列名非法"):
        build_page_sql(
            table="CBONDREPO",
            columns=("OBJECT_ID",),
            limit=10,
            source_filter=(("B_INFO_TERM]; DROP", (1,)),),
        )
    with pytest.raises(SourceFetchError, match="没有允许值"):
        build_page_sql(
            table="CBONDREPO",
            columns=("OBJECT_ID",),
            limit=10,
            source_filter=(("B_INFO_TERM", ()),),
        )


@pytest.mark.unit
def test_pymssql_source_passes_filter_values_as_parameters() -> None:
    row = {"OBJECT_ID": "a", "B_ANAL_CURVENUMBER": "0901", "B_ANAL_CURVENAME": "x"}
    conn = _FakeConn([row])
    source = PymssqlWindPageSource(conn)
    rows = source.fetch_page(
        table="CBONDCURVECSI",
        columns=("OBJECT_ID", "B_ANAL_CURVENUMBER", "B_ANAL_CURVENAME"),
        cursor=_CURSOR,
        limit=5,
        chi_fields=("B_ANAL_CURVENAME",),
        source_filter=_CURVE_CSI_FILTER,
    )
    assert len(rows) == 1
    statement, params = conn.log[0]
    assert "0901" not in statement
    assert "IN (%s, %s)" in statement
    assert params == (_CURSOR.opdate, _CURSOR.opdate, "oid-1", "0901", "02502")


@pytest.mark.unit
def test_six_tables_are_writable_and_paged() -> None:
    assert len(BOND_FX_WIND_SYNC) == 6
    assert set(BOND_FX_WIND_SYNC) == {
        "CBONDCURVECNBD",
        "CBONDREPOANDIBLEODPRICES",
        "CBONDCURVECSI",
        "FXEODPRICES",
        "CBONDPRICESREPO",
        "CBONDREPO",
    }
    for name in BOND_FX_WIND_SYNC:
        spec = BOND_FX_WIND_SPECS[name]
        assert spec.dataset == f"src.wind.{name.lower()}"
        assert spec.pg_schema == "src_wind"
        assert spec.pg_table == name
        assert spec.keys == ("OBJECT_ID",)
        assert "GSUPDTIME" not in spec.native_columns
        assert_writable(spec, profile="office")
        paged = resolve_wind_paged_table(name)
        assert paged.spec == spec
        assert paged.source_table == name
        assert name in WIND_PAGED_TABLES
        # 只有曲线表有子集过滤，其余四张是全表镜像。
        expected_filter = {
            "CBONDCURVECNBD": _CURVE_CNBD_FILTER,
            "CBONDCURVECSI": _CURVE_CSI_FILTER,
        }.get(name, ())
        assert paged.source_filter == expected_filter, name


@pytest.mark.unit
def test_curve_tables_chi_field_and_full_mirror_tables_have_no_chi() -> None:
    for name in ("CBONDCURVECNBD", "CBONDCURVECSI"):
        assert resolve_wind_paged_table(name).chi_fields == ("B_ANAL_CURVENAME",)
    for name in ("CBONDREPOANDIBLEODPRICES", "FXEODPRICES", "CBONDPRICESREPO", "CBONDREPO"):
        assert resolve_wind_paged_table(name).chi_fields == ()


@pytest.mark.unit
def test_bond_fx_specs_match_last_ddl(repo_root: Path) -> None:
    ddl = _last_create_columns(repo_root)
    for name in BOND_FX_WIND_SYNC:
        expected = [c for c in ddl[name] if c not in _TECH]
        assert list(BOND_FX_WIND_SPECS[name].native_columns) == expected, name


@pytest.mark.unit
def test_bond_fx_ddl_declares_object_id_primary_key(repo_root: Path) -> None:
    sql = (repo_root / "db" / "migrations" / "src" / "0019_bond_fx_wind_tables.sql").read_text(
        encoding="utf-8"
    )
    statements = split_sql_statements(sql)
    creates = {
        m.group(1): s
        for s in statements
        if (m := re.match(r'CREATE TABLE src_wind\."(\w+)" \(', s)) is not None
    }
    assert set(creates) == set(BOND_FX_WIND_SYNC)
    for name, stmt in creates.items():
        assert '"OBJECT_ID" varchar(100) NOT NULL' in stmt, name
        assert 'PRIMARY KEY ("OBJECT_ID")' in stmt, name
        assert "GSUPDTIME" not in stmt, name
