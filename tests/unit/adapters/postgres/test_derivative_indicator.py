"""衍生指标换手的 PostgreSQL 适配器：SQL 形状与行解析。不连库。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantagent.adapters.postgres.derivative_indicator import (
    _decimal,
    _row_from_mapping,
    _select_sql,
)
from quantagent.domain.errors import DerivativeIndicatorLookupError


def test_select_sql_reads_only_the_cutoff_range_and_code_list() -> None:
    sql = _select_sql("TRADE_DT")
    assert 'FROM "src_wind"."ASHAREEODDERIVATIVEINDICATOR"' in sql
    assert '"TRADE_DT" BETWEEN %s AND %s' in sql
    assert '"S_INFO_WINDCODE" = ANY(%s)' in sql
    assert '"S_DQ_TURN"' in sql
    assert sql.rstrip().endswith('ORDER BY "TRADE_DT", "S_INFO_WINDCODE"')


def test_row_keeps_null_turnover_and_exact_decimal() -> None:
    row = _row_from_mapping(
        {"TRADE_DT": "20240102", "S_INFO_WINDCODE": "000001.SZ", "S_DQ_TURN": Decimal("0.5969")}
    )
    assert row.turnover == Decimal("0.5969")
    empty = _row_from_mapping(
        {"TRADE_DT": "20240102", "S_INFO_WINDCODE": "000001.SZ", "S_DQ_TURN": None}
    )
    assert empty.turnover is None


def test_float_turnover_is_rejected_not_coerced() -> None:
    # numeric(20,4) 应当以 Decimal 返回；若驱动给出 float，说明列类型或驱动配置变了，直接拒绝。
    with pytest.raises(DerivativeIndicatorLookupError):
        _decimal(0.5969, "S_DQ_TURN")
