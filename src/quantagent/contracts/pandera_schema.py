"""把 schema YAML 编成 pandera DataFrameSchema。写入前校验会走这里。"""

from __future__ import annotations

from decimal import Decimal
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
    # Wind GSUPDTIME 一类 SQL Server rowversion，PG 存 bytea。
    "bytes": "object",
    "decimal": "object",
}


def _decimal_valid(value: object, *, precision: int, scale: int) -> bool:
    if not isinstance(value, Decimal) or not value.is_finite():
        return False
    parts = value.as_tuple()
    exponent = int(parts.exponent)
    return exponent >= -scale and max(len(parts.digits) + exponent, 0) <= precision - scale


def to_pandera(spec: DatasetSchemaSpec) -> Any:
    columns = {
        name: pa.Column(
            _PANDERA_DTYPE[col.dtype],
            nullable=col.nullable,
            coerce=True,
            checks=(
                pa.Check(
                    lambda value, p=col.precision, s=col.scale: _decimal_valid(
                        value, precision=p, scale=s
                    ),
                    element_wise=True,
                    ignore_na=True,
                )
                if col.dtype == "decimal"
                else None
            ),
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
