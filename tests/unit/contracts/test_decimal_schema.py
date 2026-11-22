from decimal import Decimal

import pandas as pd
import pandera as pa
import pytest

from quantagent.contracts.pandera_schema import to_pandera
from quantagent.contracts.spec import ColumnSpec, DatasetSchemaSpec


def schema():
    return DatasetSchemaSpec.model_validate(
        {
            "dataset": "src.example.prices",
            "layer": "lake",
            "doc_ref": "example.md",
            "temporal_kind": "point_event",
            "event_field": "day",
            "keys": ["day"],
            "columns": {
                "day": {"dtype": "int64"},
                "value": {"dtype": "decimal", "precision": 6, "scale": 2},
            },
        }
    )


def test_decimal_preserves_precision():
    output = to_pandera(schema()).validate(
        pd.DataFrame({"day": [1], "value": [Decimal("1234.56")]})
    )
    assert output["value"].iloc[0] == Decimal("1234.56")
    assert isinstance(output["value"].iloc[0], Decimal)


@pytest.mark.parametrize("value", [1.2, Decimal("12345.67"), Decimal("1.234"), Decimal("NaN")])
def test_decimal_rejects_invalid_values(value):
    with pytest.raises(pa.errors.SchemaError):
        to_pandera(schema()).validate(pd.DataFrame({"day": [1], "value": [value]}))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dtype": "decimal"},
        {"dtype": "decimal", "precision": 2, "scale": 3},
        {"dtype": "float64", "precision": 2, "scale": 1},
    ],
)
def test_invalid_decimal_specs(kwargs):
    with pytest.raises(ValueError):
        ColumnSpec(**kwargs)
