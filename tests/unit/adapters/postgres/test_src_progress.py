"""_batch 进度汇总：只读 SQL 与页速计算。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.src_progress import (
    SRC_SCHEMAS,
    TableProgress,
    src_progress,
    wind_progress,
)


@pytest.mark.unit
def test_progress_is_read_only_and_computes_page_rate() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        {
            "dataset": "src.wind.asharemoneyflow",
            "pages": 470,
            "rows": Decimal(4700000),
            "last_commit": datetime(2026, 11, 18, 9, 0, tzinfo=UTC),
            "source_cursor": '{"opdate":"2026-03-05T00:00:00","object_id":"x"}',
            "recent_pages": 11,
            "recent_span": Decimal(500),
        },
        {
            "dataset": "src.wind.asharecalendar",
            "pages": 32,
            "rows": Decimal(31483),
            "last_commit": datetime(2026, 11, 15, 9, 0, tzinfo=UTC),
            "source_cursor": None,
            "recent_pages": 0,
            "recent_span": None,
        },
    ]
    rows = wind_progress(conn, window_minutes=60)
    statement, params = cur.execute.call_args.args
    assert statement.lstrip().upper().startswith("SELECT")
    for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE"):
        assert verb not in statement.upper()
    assert params == {"window": 60}
    assert rows[0].rows == 4700000
    assert rows[0].recent_seconds_per_page == 50.0
    assert rows[1].recent_seconds_per_page is None


def _batch_row(dataset: str, when: datetime) -> dict[str, object]:
    return {
        "dataset": dataset,
        "pages": 1,
        "rows": Decimal(10),
        "last_commit": when,
        "source_cursor": None,
        "recent_pages": 0,
        "recent_span": None,
    }


def _conn_with_results(results: list[list[dict[str, object]]]) -> MagicMock:
    """每次 cursor 执行后依次返回 ``results`` 中的一项，与 schema 调用顺序一致。"""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.side_effect = results
    return conn


@pytest.mark.unit
def test_src_progress_merges_schemas_newest_commit_first() -> None:
    conn = _conn_with_results(
        [
            [_batch_row("src.wind.a", datetime(2026, 11, 18, 9, 0, tzinfo=UTC))],
            [_batch_row("src.tushare.b", datetime(2026, 11, 19, 9, 0, tzinfo=UTC))],
            [_batch_row("src.macro.c", datetime(2026, 11, 17, 9, 0, tzinfo=UTC))],
        ]
    )
    rows = src_progress(conn, schemas=("src_wind", "src_tushare", "src_macro"), window_minutes=60)
    assert [r.schema for r in rows] == ["src_tushare", "src_wind", "src_macro"]
    assert [r.dataset for r in rows] == ["src.tushare.b", "src.wind.a", "src.macro.c"]
    assert all(isinstance(r, TableProgress) for r in rows)


@pytest.mark.unit
def test_src_progress_skips_schema_without_success_batches() -> None:
    conn = _conn_with_results(
        [
            [],
            [_batch_row("src.tushare.b", datetime(2026, 11, 19, 9, 0, tzinfo=UTC))],
        ]
    )
    rows = src_progress(conn, schemas=("src_macro", "src_tushare"), window_minutes=60)
    assert [r.schema for r in rows] == ["src_tushare"]


@pytest.mark.unit
def test_src_progress_rejects_schema_outside_constant_before_querying() -> None:
    conn = MagicMock()
    with pytest.raises(ValueError, match="未知源 schema"):
        src_progress(conn, schemas=("src_wind", 'src_wind"; DROP TABLE x; --'), window_minutes=60)
    conn.cursor.assert_not_called()


@pytest.mark.unit
def test_src_progress_statements_are_read_only_and_quote_each_schema() -> None:
    conn = _conn_with_results([[] for _ in SRC_SCHEMAS])
    src_progress(conn, schemas=SRC_SCHEMAS, window_minutes=30)
    cur = conn.cursor.return_value.__enter__.return_value
    calls = cur.execute.call_args_list
    assert len(calls) == len(SRC_SCHEMAS)
    for call, schema in zip(calls, SRC_SCHEMAS, strict=True):
        statement, params = call.args
        assert params == {"window": 30}
        assert statement.lstrip().upper().startswith("SELECT")
        for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "DROP", "ALTER"):
            assert verb not in statement.upper()
        assert f'"{schema}"."_batch"' in statement


@pytest.mark.unit
def test_wind_progress_is_single_schema_wrapper() -> None:
    conn = _conn_with_results([[]])
    assert wind_progress(conn, window_minutes=60) == []
    cur = conn.cursor.return_value.__enter__.return_value
    statement, _ = cur.execute.call_args.args
    assert '"src_wind"."_batch"' in statement
    assert cur.execute.call_count == 1
