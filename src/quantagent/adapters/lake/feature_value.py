"""``feature.value`` 三类代表性查询。

读取接口不提供不带 ``as_of`` 的路径。``knowledge_dt <= as_of`` 写进 SQL，
不是调用方可关的优化。训练矩阵先把 PIT 过滤落入临时表，再 PIVOT——DuckDB
不允许带参数的自动透视列发现。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.lake.errors import EmptyDomainError, LakeAdapterError
from quantagent.platform.duck import assert_ident

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    import duckdb
    import pyarrow as pa

FEATURE_VALUE_VIEW = "feature_value"

_SINGLE_SQL = """
SELECT event_dt, asset_id, value, knowledge_dt, pit_grade
FROM {view}
WHERE feature_id = $feature_id
  AND definition_version = $definition_version
  AND param_hash = $param_hash
  AND event_dt BETWEEN $start AND $end
  AND knowledge_dt <= $as_of
ORDER BY asset_id, event_dt
"""

_CROSS_SECTION_SQL = """
SELECT event_dt, asset_id, feature_id, definition_version, param_hash,
       value, knowledge_dt, pit_grade
FROM {view}
WHERE event_dt = $event_dt
  AND knowledge_dt <= $as_of
ORDER BY asset_id, feature_id, definition_version, param_hash
"""

_MATRIX_SRC_SQL = """
CREATE OR REPLACE TEMP TABLE {tmp} AS
SELECT asset_id, event_dt, feature_id, value
FROM {view}
WHERE knowledge_dt <= $as_of
  AND event_dt BETWEEN $start AND $end
  AND feature_id IN (SELECT UNNEST($feature_ids))
  AND asset_id IN (SELECT UNNEST($asset_ids))
"""


def scan_feature_window(
    conn: duckdb.DuckDBPyConnection,
    *,
    as_of: date,
    feature_id: str,
    definition_version: str,
    param_hash: str,
    start: date,
    end: date,
    view: str = FEATURE_VALUE_VIEW,
) -> pa.Table:
    """单因子长区间。"""
    ident = assert_ident(view)
    return conn.execute(
        _SINGLE_SQL.format(view=ident),
        {
            "as_of": as_of,
            "feature_id": feature_id,
            "definition_version": definition_version,
            "param_hash": param_hash,
            "start": start,
            "end": end,
        },
    ).to_arrow_table()


def scan_feature_cross_section(
    conn: duckdb.DuckDBPyConnection,
    *,
    as_of: date,
    event_dt: date,
    view: str = FEATURE_VALUE_VIEW,
) -> pa.Table:
    """某一天的全因子截面。"""
    ident = assert_ident(view)
    return conn.execute(
        _CROSS_SECTION_SQL.format(view=ident),
        {"as_of": as_of, "event_dt": event_dt},
    ).to_arrow_table()


def build_training_matrix(
    conn: duckdb.DuckDBPyConnection,
    *,
    as_of: date,
    start: date,
    end: date,
    feature_ids: Sequence[str],
    asset_ids: Sequence[str],
    view: str = FEATURE_VALUE_VIEW,
) -> pa.Table:
    """指定股票池与因子集合上的训练宽表。空域 fail-closed。"""
    ident = assert_ident(view)
    features = _require_nonempty("feature_ids", feature_ids)
    assets = _require_nonempty("asset_ids", asset_ids)
    tmp = "_feature_matrix_src"
    conn.execute(
        _MATRIX_SRC_SQL.format(view=ident, tmp=tmp),
        {
            "as_of": as_of,
            "start": start,
            "end": end,
            "feature_ids": features,
            "asset_ids": assets,
        },
    )
    n_src = conn.execute(f"SELECT count(*) FROM {tmp}").fetchone()
    if n_src is None or n_src[0] == 0:
        raise EmptyDomainError("训练矩阵源行为空，拒绝 pivot")
    in_list = ", ".join(_sql_string(fid) for fid in features)
    return conn.execute(
        f"""
        PIVOT {tmp} ON feature_id IN ({in_list})
        USING first(value)
        GROUP BY asset_id, event_dt
        """
    ).to_arrow_table()


def _require_nonempty(name: str, values: Sequence[str]) -> list[str]:
    items = list(values)
    if not items:
        raise EmptyDomainError(f"{name} 为空，拒绝查询")
    return items


def _sql_string(value: str) -> str:
    if "\x00" in value:
        raise LakeAdapterError("因子 id 含 NUL，拒绝拼进 PIVOT 列表")
    return "'" + value.replace("'", "''") + "'"
