"""``feature.value`` 三类代表性查询与湖仓储。

读取接口不提供不带 ``as_of`` 的路径。PIT 截止列来自 ``domain.pit``，SQL
只执行 ``{visibility_column} <= $visible_on_or_before``，不得把规则名或
``knowledge_dt`` 写死在 WHERE 里。训练矩阵先把 PIT 过滤落入临时表，再
PIVOT——DuckDB 不允许带参数的自动透视列发现。
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import TYPE_CHECKING

from quantagent.adapters.lake.errors import EmptyDomainError as LakeEmptyDomainError
from quantagent.adapters.lake.errors import LakeAdapterError
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.domain.errors import (
    EmptyDomainError,
    FeatureLookupError,
    MissingVisibilityError,
)
from quantagent.domain.feature_value import FeatureMatrixRow, FeatureValue
from quantagent.domain.pit import pit_cutoff
from quantagent.platform.duck import assert_ident, duck_session, register_parquet

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import duckdb
    import pyarrow as pa

    from quantagent.contracts.spec import VisibilityContract

DATASET = "feature.value"
FEATURE_VALUE_VIEW = "feature_value"

_LONG_COLUMNS = """
event_dt, asset_id, asset_class, feature_id, definition_version, param_hash,
value, knowledge_dt, pit_grade, computed_at, run_id
"""

_SINGLE_SQL = """
SELECT {columns}
FROM {view}
WHERE feature_id = $feature_id
  AND definition_version = $definition_version
  AND param_hash = $param_hash
  AND event_dt BETWEEN $start AND $end
  AND {visibility_column} <= $visible_on_or_before
ORDER BY asset_id, event_dt
"""

_CROSS_SECTION_SQL = """
SELECT {columns}
FROM {view}
WHERE event_dt = $event_dt
  AND {visibility_column} <= $visible_on_or_before
ORDER BY asset_id, feature_id, definition_version, param_hash
"""

_MATRIX_SRC_SQL = """
CREATE OR REPLACE TEMP TABLE {tmp} AS
SELECT asset_id, event_dt, feature_id, value
FROM {view}
WHERE {visibility_column} <= $visible_on_or_before
  AND event_dt BETWEEN $start AND $end
  AND feature_id IN (SELECT UNNEST($feature_ids))
  AND asset_id IN (SELECT UNNEST($asset_ids))
"""


class LakeFeatureRepository:
    """``feature.value`` 的 Parquet 读取。

    可见性截止列来自 ``domain.pit``，不用 ``event_dt``：截面日可以早于源
    字段给出的可见日，用事件日过滤会把尚未可知的值放进研究样本。
    """

    def __init__(self, source: Path, *, contract: VisibilityContract | None = None) -> None:
        self._source = source
        self._contract = contract if contract is not None else load_feature_value_visibility()

    def scan_window(
        self,
        *,
        as_of: date,
        feature_id: str,
        definition_version: str,
        param_hash: str,
        start: date,
        end: date,
    ) -> tuple[FeatureValue, ...]:
        _require_identity(feature_id, definition_version, param_hash)
        if start > end:
            raise FeatureLookupError("start 晚于 end")
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        with duck_session() as conn:
            register_parquet(conn, FEATURE_VALUE_VIEW, self._source)
            table = scan_feature_window(
                conn,
                visibility_column=cutoff.column,
                visible_on_or_before=cutoff.on_or_before,
                feature_id=feature_id,
                definition_version=definition_version,
                param_hash=param_hash,
                start=start,
                end=end,
            )
        return _long_rows_or_empty(
            table,
            message=(
                f"因子窗口为空: feature_id={feature_id} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            ),
        )

    def scan_cross_section(
        self,
        *,
        as_of: date,
        event_dt: date,
    ) -> tuple[FeatureValue, ...]:
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        with duck_session() as conn:
            register_parquet(conn, FEATURE_VALUE_VIEW, self._source)
            table = scan_feature_cross_section(
                conn,
                visibility_column=cutoff.column,
                visible_on_or_before=cutoff.on_or_before,
                event_dt=event_dt,
            )
        return _long_rows_or_empty(
            table,
            message=(f"因子截面为空: event_dt={event_dt.isoformat()} as_of={as_of.isoformat()}"),
        )

    def build_training_matrix(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        feature_ids: Sequence[str],
        asset_ids: Sequence[str],
    ) -> tuple[FeatureMatrixRow, ...]:
        if start > end:
            raise FeatureLookupError("start 晚于 end")
        cutoff = pit_cutoff(self._contract, as_of=as_of)
        features = list(feature_ids)
        try:
            with duck_session() as conn:
                register_parquet(conn, FEATURE_VALUE_VIEW, self._source)
                table = build_training_matrix(
                    conn,
                    visibility_column=cutoff.column,
                    visible_on_or_before=cutoff.on_or_before,
                    start=start,
                    end=end,
                    feature_ids=features,
                    asset_ids=list(asset_ids),
                )
        except LakeEmptyDomainError as exc:
            raise EmptyDomainError(str(exc)) from exc
        return _matrix_from_arrow(table, feature_ids=features)


def load_feature_value_visibility() -> VisibilityContract:
    bundle = load_bundle()
    vis = bundle.visibilities.get(DATASET)
    schema = bundle.schemas.get(DATASET)
    if vis is None or schema is None:
        raise MissingVisibilityError(DATASET)
    return vis


def scan_feature_window(
    conn: duckdb.DuckDBPyConnection,
    *,
    visibility_column: str,
    visible_on_or_before: date,
    feature_id: str,
    definition_version: str,
    param_hash: str,
    start: date,
    end: date,
    view: str = FEATURE_VALUE_VIEW,
) -> pa.Table:
    """单因子长区间。截止列由调用方从 ``pit_cutoff`` 传入，不是 ``event_dt``。"""
    ident = assert_ident(view)
    column = assert_ident(visibility_column)
    return conn.execute(
        _SINGLE_SQL.format(view=ident, columns=_LONG_COLUMNS, visibility_column=column),
        {
            "feature_id": feature_id,
            "definition_version": definition_version,
            "param_hash": param_hash,
            "start": start,
            "end": end,
            "visible_on_or_before": visible_on_or_before,
        },
    ).to_arrow_table()


def scan_feature_cross_section(
    conn: duckdb.DuckDBPyConnection,
    *,
    visibility_column: str,
    visible_on_or_before: date,
    event_dt: date,
    view: str = FEATURE_VALUE_VIEW,
) -> pa.Table:
    """某一天的全因子截面。"""
    ident = assert_ident(view)
    column = assert_ident(visibility_column)
    return conn.execute(
        _CROSS_SECTION_SQL.format(view=ident, columns=_LONG_COLUMNS, visibility_column=column),
        {"event_dt": event_dt, "visible_on_or_before": visible_on_or_before},
    ).to_arrow_table()


def build_training_matrix(
    conn: duckdb.DuckDBPyConnection,
    *,
    visibility_column: str,
    visible_on_or_before: date,
    start: date,
    end: date,
    feature_ids: Sequence[str],
    asset_ids: Sequence[str],
    view: str = FEATURE_VALUE_VIEW,
) -> pa.Table:
    """指定股票池与因子集合上的训练宽表。空域 fail-closed。"""
    ident = assert_ident(view)
    column = assert_ident(visibility_column)
    features = _require_nonempty("feature_ids", feature_ids)
    assets = _require_nonempty("asset_ids", asset_ids)
    tmp = assert_ident("_feature_matrix_src")
    conn.execute(
        _MATRIX_SRC_SQL.format(view=ident, tmp=tmp, visibility_column=column),
        {
            "visible_on_or_before": visible_on_or_before,
            "start": start,
            "end": end,
            "feature_ids": features,
            "asset_ids": assets,
        },
    )
    n_src = conn.execute(f"SELECT count(*) FROM {tmp}").fetchone()
    if n_src is None or n_src[0] == 0:
        raise LakeEmptyDomainError("训练矩阵源行为空，拒绝 pivot")
    in_list = ", ".join(_sql_string(fid) for fid in features)
    return conn.execute(
        f"""
        SELECT * FROM (
            PIVOT {tmp} ON feature_id IN ({in_list})
            USING first(value)
            GROUP BY asset_id, event_dt
        )
        ORDER BY asset_id, event_dt
        """
    ).to_arrow_table()


def _require_nonempty(name: str, values: Sequence[str]) -> list[str]:
    items = list(values)
    if not items:
        raise LakeEmptyDomainError(f"{name} 为空，拒绝查询")
    return items


def _sql_string(value: str) -> str:
    if "\x00" in value:
        raise LakeAdapterError("因子 id 含 NUL，拒绝拼进 PIVOT 列表")
    return "'" + value.replace("'", "''") + "'"


def _require_identity(feature_id: str, definition_version: str, param_hash: str) -> None:
    if not feature_id.strip() or not definition_version.strip() or not param_hash.strip():
        raise FeatureLookupError("feature_id / definition_version / param_hash 为空")


def _long_rows_or_empty(table: pa.Table, *, message: str) -> tuple[FeatureValue, ...]:
    if table.num_rows == 0:
        raise EmptyDomainError(message)
    frame = table.to_pandas(date_as_object=True, timestamp_as_object=True)
    spec = load_bundle().schemas[DATASET]
    to_pandera(spec).validate(frame)
    return tuple(_feature_from_raw(raw) for raw in table.to_pylist())


def _matrix_from_arrow(
    table: pa.Table, *, feature_ids: Sequence[str]
) -> tuple[FeatureMatrixRow, ...]:
    rows: list[FeatureMatrixRow] = []
    for raw in table.to_pylist():
        values = {fid: _optional_float(raw.get(fid)) for fid in feature_ids}
        rows.append(
            FeatureMatrixRow(
                asset_id=str(raw["asset_id"]),
                event_dt=_as_date(raw["event_dt"]),
                values=values,
            )
        )
    return tuple(rows)


def _feature_from_raw(raw: dict[str, object]) -> FeatureValue:
    return FeatureValue(
        event_dt=_as_date(raw["event_dt"]),
        asset_id=str(raw["asset_id"]),
        asset_class=str(raw["asset_class"]),
        feature_id=str(raw["feature_id"]),
        definition_version=str(raw["definition_version"]),
        param_hash=str(raw["param_hash"]),
        value=_require_float(raw["value"]),
        knowledge_dt=_as_date(raw["knowledge_dt"]),
        pit_grade=str(raw["pit_grade"]),
        computed_at=_as_datetime(raw["computed_at"]),
        run_id=str(raw["run_id"]),
    )


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise FeatureLookupError(f"无法转为 date: {value!r}")


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    raise FeatureLookupError(f"无法转为 datetime: {value!r}")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FeatureLookupError(f"无法转为 float: {value!r}")
    number = float(value)
    if math.isnan(number):
        return None
    return number


def _require_float(value: object) -> float:
    number = _optional_float(value)
    if number is None:
        raise FeatureLookupError("value 缺失，长表不得补 0")
    return number
