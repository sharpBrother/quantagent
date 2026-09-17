"""源表 DML 动词白名单。"""

from __future__ import annotations

import pytest

from quantagent.adapters.postgres.errors import ForbiddenSqlError
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql


@pytest.mark.unit
def test_insert_and_select_are_allowed() -> None:
    assert_src_dml_sql('INSERT INTO src_tushare."trade_cal" (exchange) VALUES (%s)')
    assert_src_dml_sql('SELECT _row_hash FROM src_tushare."trade_cal" WHERE _batch_id = %s')


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE src_tushare._batch SET status = 'x'",
        "DELETE FROM src_tushare.trade_cal",
        "MERGE INTO src_tushare.trade_cal AS t USING s ON TRUE WHEN MATCHED THEN UPDATE SET x = 1",
        "TRUNCATE src_tushare.trade_cal",
        "DROP TABLE src_tushare.trade_cal",
        "ALTER TABLE src_tushare.trade_cal ADD COLUMN x int",
        'INSERT INTO src_tushare."trade_cal" VALUES (%s) ON CONFLICT DO NOTHING',
        "COPY src_tushare.trade_cal FROM STDIN",
    ],
)
def test_forbidden_verbs_are_rejected(sql: str) -> None:
    with pytest.raises(ForbiddenSqlError):
        assert_src_dml_sql(sql)
