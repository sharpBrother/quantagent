"""指数基本资料两张表在编排层：明确不做 PIT，且初始化回填紧跟 SWINDEXMEMBERS。"""

from __future__ import annotations

import pytest
from orchestration.assets.wind import NOT_PIT_WIND_TABLES, UNCONFIGURED_WIND_TABLES
from orchestration.jobs.wind_initial import INITIAL_BACKFILL_ORDER


@pytest.mark.unit
def test_index_description_tables_are_not_pit() -> None:
    assert {"AINDEXDESCRIPTION", "AINDEXDESCRIPTIONZL"} <= NOT_PIT_WIND_TABLES
    assert NOT_PIT_WIND_TABLES.isdisjoint(UNCONFIGURED_WIND_TABLES)


@pytest.mark.unit
def test_initial_backfill_runs_index_description_after_swindexmembers() -> None:
    index = INITIAL_BACKFILL_ORDER.index("SWINDEXMEMBERS")
    assert INITIAL_BACKFILL_ORDER[index + 1 : index + 3] == (
        "AINDEXDESCRIPTION",
        "AINDEXDESCRIPTIONZL",
    )
