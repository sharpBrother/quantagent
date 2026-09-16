"""把 schema YAML 编成 pandera DataFrameSchema。写入前校验会走这里。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandera as pa

if TYPE_CHECKING:
    from quantagent.contracts.spec import DatasetSchemaSpec

_PANDERA_DTYPE: dict[str, Any] = {
    "date": "datetime64[ns]",
    "datetime": "datetime64[ns]",
    "string": "string",
    "bool": "bool",
    "int64": "int64",
    "float64": "float64",
}


def to_pandera(spec: DatasetSchemaSpec) -> Any:
    columns = {
        name: pa.Column(
            _PANDERA_DTYPE[col.dtype],
            nullable=col.nullable,
            coerce=True,
            description=col.description or None,
        )
        for name, col in spec.columns.items()
    }
    return pa.DataFrameSchema(
        columns,
        unique=list(spec.keys),
        strict=True,
        coerce=True,
    )
