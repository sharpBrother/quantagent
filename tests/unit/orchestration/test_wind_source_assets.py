"""Wind 分页表的资产工厂：覆盖范围、命名、pit_grade 常量与 max_pages 透传。假源，不连接数据库。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import pytest
from dagster import AssetsDefinition, materialize
from orchestration.assets.wind import (
    NOT_PIT_WIND_TABLES,
    UNCONFIGURED_WIND_TABLES,
    WIND_SOURCE_ASSETS,
    src_wind_asharecalendar,
    src_wind_ashareeodprices,
    std_trade_calendar,
)
from orchestration.resources.wind import TradeCalendarResource, WindIngestResource
from tests.unit.ingest.test_wind_job import FakeSrcStore, FakeWindSource

from quantagent.contracts.loader import load_bundle
from quantagent.ingest.jobs.wind_paged import WindPagedIngestResult
from quantagent.ingest.sources.wind.tables import WIND_PAGED_TABLES
from quantagent.ingest.writers.tables import ASHARECALENDAR
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import VarPaths, resolve_var_paths

if TYPE_CHECKING:
    from pathlib import Path

    from dagster import ExecuteInProcessResult

    from quantagent.lake.materialize.trade_calendar import TradeCalendarMaterializeResult

ASHAREDESCRIPTION = WIND_PAGED_TABLES["ASHAREDESCRIPTION"].spec

SRC_ROWS = (
    {"exchange": "SSE", "cal_date": "20260105", "is_open": 1, "pretrade_date": "20260102"},
    {"exchange": "SSE", "cal_date": "20260101", "is_open": 0, "pretrade_date": None},
)


def _paths(tmp_path: Path, *, allow_db_write: bool) -> tuple[Settings, VarPaths]:
    settings = Settings(
        _env_file=None,
        profile="office",
        var_root=tmp_path / "var",
        allow_db_write=allow_db_write,
    )
    return settings, resolve_var_paths(settings, repo_root=tmp_path)


def _source_asset(table: str) -> AssetsDefinition:
    name = f"src_wind_{table.lower()}"
    for asset in WIND_SOURCE_ASSETS:
        if asset.key.path[-1] == name:
            return asset
    raise AssertionError(f"缺少资产 {name}")


def _pit_grade_of(asset: AssetsDefinition) -> object:
    return asset.metadata_by_key[asset.key]["pit_grade"]


def _asset_meta(result: ExecuteInProcessResult, asset_name: str) -> dict[str, object]:
    matched = [
        event
        for event in result.get_asset_materialization_events()
        if event.asset_key is not None and event.asset_key.path[-1] == asset_name
    ]
    assert len(matched) == 1
    raw = matched[0].materialization.metadata
    return {key: raw[key].value for key in raw}


def _description_row(object_id: str) -> dict[str, object]:
    payload = dict.fromkeys(ASHAREDESCRIPTION.native_columns)
    payload.update(
        {
            "OBJECT_ID": object_id,
            "S_INFO_WINDCODE": "000001.SZ",
            "OPDATE": datetime(2024, 1, 2, 10, 0, 0),
            "OPMODE": "0",
        }
    )
    return payload


class _RecordingWindIngest(WindIngestResource):
    """记录 ``ingest`` 收到的参数，并返回一个真实的结果对象。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ingest(
        self,
        table: str,
        *,
        write_db: bool,
        page_size: int,
        max_pages: int | None,
        stop_run_id: str | None = None,
    ) -> WindPagedIngestResult:
        self.calls.append(
            {
                "table": table,
                "write_db": write_db,
                "page_size": page_size,
                "max_pages": max_pages,
            }
        )
        return WindPagedIngestResult(
            dataset="src.wind.fake",
            table=table,
            written=False,
            pages=0,
            row_count=0,
            inserted=0,
            replaced=0,
            deleted=0,
            skipped=0,
            metadata_skipped=0,
            dml_count=0,
            payload_digest="",
            output_digest="out",
            source_cursor="cursor",
        )


@pytest.mark.unit
def test_source_assets_cover_every_paged_table_with_stable_names() -> None:
    names = [asset.key.path[-1] for asset in WIND_SOURCE_ASSETS]
    assert names == [f"src_wind_{table.lower()}" for table in WIND_PAGED_TABLES]
    assert src_wind_asharecalendar.key.path[-1] == "src_wind_asharecalendar"
    assert src_wind_ashareeodprices.key.path[-1] == "src_wind_ashareeodprices"


@pytest.mark.unit
def test_source_assets_have_no_synthetic_ordering_dependencies() -> None:
    # 源表之间不存在数据依赖；初始化回填的优先级不能改变日更血缘。
    assert all(not asset.dependency_keys for asset in WIND_SOURCE_ASSETS)


@pytest.mark.unit
def test_pit_grade_metadata_for_tables_without_a_contract() -> None:
    assert NOT_PIT_WIND_TABLES.isdisjoint(UNCONFIGURED_WIND_TABLES)
    for table in NOT_PIT_WIND_TABLES:
        assert _pit_grade_of(_source_asset(table)) == "not_pit"
    for table in UNCONFIGURED_WIND_TABLES:
        assert _pit_grade_of(_source_asset(table)) == "unconfigured"


@pytest.mark.unit
def test_contracted_table_keeps_its_grade_in_metadata() -> None:
    meta = src_wind_ashareeodprices.metadata_by_key[src_wind_ashareeodprices.key]
    assert meta["pit_grade"] == "A"
    assert meta["reads"] == "wind_db.dbo.ASHAREEODPRICES"
    assert meta["checkpoint"] == "source_cursor"


@pytest.mark.unit
def test_non_pit_asset_reports_replaced_deleted_and_metadata_skipped(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path, allow_db_write=True)
    source = FakeWindSource([[_description_row("a")]], spec=ASHAREDESCRIPTION)
    resource = WindIngestResource(
        settings=settings,
        paths=paths,
        source=source,
        store=FakeSrcStore(),
    )
    asset = _source_asset("ASHAREDESCRIPTION")
    result = materialize(
        [asset],
        resources={"wind_ingest": resource},
        run_config={
            "ops": {
                asset.op.name: {
                    "config": {"as_of": "2026-11-15", "write_db": False, "max_pages": 1}
                }
            }
        },
    )
    assert result.success
    meta = _asset_meta(result, "src_wind_asharedescription")
    assert meta["pit_grade"] == "not_pit"
    assert meta["as_of"] == "2026-11-15"
    assert meta["pages"] == 1
    assert meta["replaced"] == 0
    assert meta["deleted"] == 0
    assert meta["metadata_skipped"] == 0


@pytest.mark.unit
def test_max_pages_none_reaches_ingest_unchanged() -> None:
    recorder = _RecordingWindIngest()
    asset = _source_asset("ASHAREMONEYFLOW")
    result = materialize(
        [asset],
        resources={"wind_ingest": recorder},
        run_config={
            "ops": {
                asset.op.name: {
                    "config": {
                        "as_of": "2026-11-15",
                        "write_db": True,
                        "max_pages": None,
                        "page_size": 10000,
                    }
                }
            }
        },
    )
    assert result.success
    assert recorder.calls == [
        {
            "table": "ASHAREMONEYFLOW",
            "write_db": True,
            "page_size": 10000,
            "max_pages": None,
        }
    ]


@pytest.mark.unit
def test_calendar_asset_passes_append_flags_through(tmp_path: Path) -> None:
    settings, paths = _paths(tmp_path, allow_db_write=False)
    seen: list[tuple[bool, bool, int | None]] = []

    class _Calendar(TradeCalendarResource):
        def materialize(
            self,
            *,
            as_of: date,
            rebuild: bool,
            append_only: bool = False,
            horizon_days: int | None = None,
        ) -> TradeCalendarMaterializeResult:
            seen.append((rebuild, append_only, horizon_days))
            return super().materialize(
                as_of=as_of,
                rebuild=rebuild,
                append_only=append_only,
                horizon_days=horizon_days,
            )

    result = materialize(
        [src_wind_asharecalendar, std_trade_calendar],
        resources={
            "wind_ingest": WindIngestResource(
                settings=settings,
                paths=paths,
                source=FakeWindSource([[]], spec=ASHARECALENDAR),
                store=FakeSrcStore(),
            ),
            "trade_calendar": _Calendar(settings=settings, paths=paths, src_rows=SRC_ROWS),
        },
        run_config={
            "ops": {
                "src_wind_asharecalendar": {
                    "config": {"as_of": "2026-11-15", "write_db": False, "max_pages": 1}
                },
                "std_trade_calendar": {
                    "config": {
                        "as_of": "2026-11-15",
                        "rebuild": False,
                        "append_only": True,
                        "horizon_days": 7,
                    }
                },
            }
        },
    )
    assert result.success
    assert seen == [(False, True, 7)]


@pytest.mark.unit
def test_unconfigured_tables_really_lack_visibility() -> None:
    # 补了契约的表必须移出 unconfigured，否则资产 metadata 会把已有等级写成 unconfigured。
    visibilities = load_bundle().visibilities
    for table in UNCONFIGURED_WIND_TABLES:
        assert f"src.wind.{table.lower()}" not in visibilities, table
