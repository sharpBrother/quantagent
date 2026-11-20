"""列注释防漂移：契约 description 与 db/migrations/src/ 中的 COMMENT ON COLUMN 必须一致。

期望值与迁移文件都由同一个解析规则读取；迁移按出现顺序归并，后出现的覆盖先出现的。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from quantagent.adapters.postgres.migrate import list_migration_files, split_sql_statements
from quantagent.contracts.loader import ContractBundle
from quantagent.contracts.spec import DatasetSchemaSpec
from quantagent.ingest.writers.column_comments import (
    ColumnCommentError,
    build_column_comments,
    render_comment_sql,
)

if TYPE_CHECKING:
    from pathlib import Path

_COMMENT = re.compile(r"COMMENT ON COLUMN (\w+)\.\"([^\"]+)\"\.\"([^\"]+)\" IS '((?:[^']|'')*)'")


def _parse_comment(statement: str) -> tuple[tuple[str, str, str], str] | None:
    match = _COMMENT.fullmatch(statement)
    if match is None:
        return None
    schema, table, column, literal = match.groups()
    return (schema, table, column), literal.replace("''", "'")


def _bundle(*schemas: dict[str, object]) -> ContractBundle:
    specs = {str(raw["dataset"]): DatasetSchemaSpec.model_validate(raw) for raw in schemas}
    return ContractBundle(schemas=specs, visibilities={}, schema_paths={}, visibility_paths={})


def _schema(dataset: str, columns: dict[str, str]) -> dict[str, object]:
    return {
        "dataset": dataset,
        "layer": "pg",
        "doc_ref": "docs/contracts/src-wind-first-batch.md",
        "temporal_kind": "snapshot",
        "keys": [next(iter(columns))],
        "columns": {
            name: {"dtype": "string", "nullable": True, "description": text}
            for name, text in columns.items()
        },
    }


@pytest.mark.unit
def test_migrations_match_contract_descriptions(repo_root: Path) -> None:
    expected = {comment.key: comment.description for comment in build_column_comments()}
    merged: dict[tuple[str, str, str], str] = {}
    for item in list_migration_files(repo_root, "src"):
        for statement in split_sql_statements(item.path.read_text(encoding="utf-8")):
            parsed = _parse_comment(statement)
            if parsed is not None:
                key, description = parsed
                merged[key] = description
    missing = sorted(expected.keys() - merged.keys())
    stale = sorted(merged.keys() - expected.keys())
    differ = sorted(k for k in expected.keys() & merged.keys() if expected[k] != merged[k])
    problems = [
        *(f"迁移缺少: {'.'.join(k)}" for k in missing[:20]),
        *(f"迁移多出（契约已无说明）: {'.'.join(k)}" for k in stale[:20]),
        *(f"说明不一致: {'.'.join(k)}" for k in differ[:20]),
    ]
    assert not problems, (
        "列注释与契约 YAML 不一致。运行 `uv run quantagent contracts emit-comments "
        "--out db/migrations/src/<下一个编号>_column_comments.sql` 生成新一条迁移。\n"
        + "\n".join(problems)
    )


@pytest.mark.unit
def test_single_quote_is_doubled_in_comment_literal() -> None:
    bundle = _bundle(_schema("src.wind.asharecalendar", {"OBJECT_ID": 'O\'Neil; "x"'}))
    sql = render_comment_sql(build_column_comments(bundle))
    statements = split_sql_statements(sql)
    assert statements == (
        'COMMENT ON COLUMN src_wind."ASHARECALENDAR"."OBJECT_ID" IS \'O\'\'Neil; "x"\'',
    )


@pytest.mark.unit
def test_empty_description_is_not_emitted() -> None:
    bundle = _bundle(_schema("src.wind.asharecalendar", {"OBJECT_ID": "", "TRADE_DAYS": "  "}))
    assert build_column_comments(bundle) == ()


@pytest.mark.unit
def test_unknown_dataset_is_rejected() -> None:
    bundle = _bundle(_schema("src.wind.not_in_whitelist", {"A": "说明"}))
    with pytest.raises(ColumnCommentError, match="不在写入白名单"):
        build_column_comments(bundle)


@pytest.mark.unit
def test_multiline_description_is_rejected() -> None:
    bundle = _bundle(_schema("src.wind.asharecalendar", {"OBJECT_ID": "第一行\n第二行"}))
    with pytest.raises(ColumnCommentError, match="换行"):
        build_column_comments(bundle)


@pytest.mark.unit
def test_output_is_deterministic_and_sorted_by_schema_table_column_order() -> None:
    # 故意把 src_wind 的契约放在前面，输出仍按 schema、表排序。
    bundle = _bundle(
        _schema("src.wind.asharecalendar", {"TRADE_DAYS": "交易日", "OBJECT_ID": "对象"}),
        _schema("src.tushare.trade_cal", {"exchange": "交易所", "cal_date": "日期"}),
    )
    first = render_comment_sql(build_column_comments(bundle))
    second = render_comment_sql(build_column_comments(bundle))
    assert first == second
    statements = split_sql_statements(first)
    parsed = [_parse_comment(s) for s in statements]
    assert all(item is not None for item in parsed)
    assert [item[0] for item in parsed if item is not None] == [
        ("src_tushare", "trade_cal", "exchange"),
        ("src_tushare", "trade_cal", "cal_date"),
        ("src_wind", "ASHARECALENDAR", "TRADE_DAYS"),
        ("src_wind", "ASHARECALENDAR", "OBJECT_ID"),
    ]
