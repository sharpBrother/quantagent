"""三个 Wind 资产的依赖、有界回填和续跑。假源，不连接数据库。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from dagster import materialize
from orchestration.assets.wind import (
    src_wind_asharecalendar,
    src_wind_ashareeodprices,
    std_trade_calendar,
)
from orchestration.jobs.wind import wind_source_refresh
from orchestration.resources.wind import TradeCalendarResource, WindIngestResource
from tests.unit.ingest.test_wind_job import FakeSrcStore, FakeWindSource, _row

from quantagent.ingest.sources.wind.cursor import decode_cursor, initial_cursor
from quantagent.ingest.writers.tables import ASHARECALENDAR
from quantagent.platform.config import Settings
from quantagent.platform.errors import WriteGateError
from quantagent.platform.storage.paths import VarPaths, resolve_var_paths

if TYPE_CHECKING:
    from pathlib import Path

    from dagster import ExecuteInProcessResult


def _paths(tmp_path: Path, *, allow_db_write: bool) -> tuple[Settings, VarPaths]:
    settings = Settings(
        _env_file=None,
        var_root=tmp_path / "var",
        allow_db_write=allow_db_write,
    )
    return settings, resolve_var_paths(settings, repo_root=tmp_path)


def _meta(result: ExecuteInProcessResult, asset_name: str) -> dict[str, object]:
    matched = []
    for event in result.get_asset_materialization_events():
        key = event.asset_key
        assert key is not None
        if key.path[-1] == asset_name:
            matched.append(event)
    assert len(matched) == 1
    raw = matched[0].materialization.metadata
    return {key: raw[key].value for key in raw}


def _ingest_config(*, write_db: bool, max_pages: int = 1) -> dict[str, object]:
    return {
        "ops": {
            "src_wind_ashareeodprices": {
                "config": {
                    "as_of": "2026-11-15",
                    "write_db": write_db,
                    "max_pages": max_pages,
                }
            }
        }
    }


@pytest.mark.unit
def test_price_backfill_is_bounded_and_resume_uses_batch_cursor(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path, allow_db_write=True)
    first = _row("a", datetime(2024, 1, 2, 10, 0, 0))
    second = _row("b", datetime(2024, 1, 2, 11, 0, 0))
    source = FakeWindSource([[first], [second], []])
    store = FakeSrcStore()
    resource = WindIngestResource(
        settings=settings,
        paths=paths,
        source=source,
        store=store,
    )
    first_run = materialize(
        [src_wind_ashareeodprices],
        resources={"wind_ingest": resource},
        run_config=_ingest_config(write_db=True, max_pages=1),
    )
    assert first_run.success
    first_meta = _meta(first_run, "src_wind_ashareeodprices")
    assert first_meta["pages"] == 1
    assert first_meta["row_count"] == 1
    assert first_meta["dml_count"] == 2
    assert first_meta["as_of"] == "2026-11-15"
    assert first_meta["pit_grade"] == "A"
    assert decode_cursor(str(first_meta["source_cursor"])).object_id == "a"
    assert source.seen[0] == initial_cursor()
    assert len(store.batch_cursors) == 1

    second_run = materialize(
        [src_wind_ashareeodprices],
        resources={"wind_ingest": resource},
        run_config=_ingest_config(write_db=True, max_pages=1),
    )
    assert second_run.success
    assert source.seen[1].object_id == "a"
    assert (
        decode_cursor(str(_meta(second_run, "src_wind_ashareeodprices")["source_cursor"])).object_id
        == "b"
    )
    assert [decode_cursor(cursor).object_id for cursor in store.batch_cursors if cursor] == [
        "a",
        "b",
    ]


@pytest.mark.unit
def test_asset_write_stays_behind_the_gate(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path, allow_db_write=False)
    source = FakeWindSource([[_row("a", datetime(2024, 1, 2, 10, 0, 0))]])
    store = FakeSrcStore()
    resource = WindIngestResource(
        settings=settings,
        paths=paths,
        source=source,
        store=store,
    )
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        materialize(
            [src_wind_ashareeodprices],
            resources={"wind_ingest": resource},
            run_config=_ingest_config(write_db=True),
        )
    assert store.inserted == 0


@pytest.mark.unit
def test_calendar_asset_depends_on_ingest_and_prices_do_not(tmp_path: Path) -> None:
    assert list(std_trade_calendar.dependency_keys) == [src_wind_asharecalendar.key]
    assert list(src_wind_ashareeodprices.dependency_keys) == []
    selected = set(
        wind_source_refresh.selection.resolve(
            [
                src_wind_asharecalendar,
                std_trade_calendar,
                src_wind_ashareeodprices,
            ]
        )
    )
    assert selected == {
        src_wind_asharecalendar.key,
        std_trade_calendar.key,
        src_wind_ashareeodprices.key,
    }

    settings, paths = _paths(tmp_path, allow_db_write=True)
    row = dict.fromkeys(ASHARECALENDAR.native_columns)
    row.update(
        OBJECT_ID="a",
        TRADE_DAYS="20240103",
        S_INFO_EXCHMARKET="SSE",
        OPDATE=datetime(2024, 1, 2, 10, 0, 0),
        OPMODE="0",
    )
    store = FakeSrcStore()
    result = materialize(
        [src_wind_asharecalendar, std_trade_calendar],
        resources={
            "wind_ingest": WindIngestResource(
                settings=settings,
                paths=paths,
                source=FakeWindSource([[row]], spec=ASHARECALENDAR),
                store=store,
            ),
            "trade_calendar": TradeCalendarResource(
                settings=settings,
                paths=paths,
                src_rows=(
                    {
                        "exchange": "SSE",
                        "cal_date": "20260105",
                        "is_open": 1,
                        "pretrade_date": "20260102",
                    },
                    {
                        "exchange": "SSE",
                        "cal_date": "20260101",
                        "is_open": 0,
                        "pretrade_date": None,
                    },
                ),
            ),
        },
        run_config={
            "ops": {
                "src_wind_asharecalendar": {
                    "config": {"as_of": "2026-11-15", "write_db": True, "max_pages": 1}
                },
                "std_trade_calendar": {"config": {"as_of": "2026-11-15"}},
            }
        },
    )
    assert result.success
    assert len(store.batch_cursors) == 1
    calendar = _meta(result, "std_trade_calendar")
    assert calendar["row_count"] == 2
    assert calendar["as_of"] == "2026-11-15"
    assert calendar["pit_grade"] == "A"
    assert (tmp_path / "var" / "lake" / "std" / "trade_calendar" / "part-00000.parquet").is_file()
