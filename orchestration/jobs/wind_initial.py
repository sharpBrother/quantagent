"""初始化回填作业：只改变执行顺序，不改变日更资产血缘。"""

from collections.abc import Iterator
from typing import TYPE_CHECKING

from dagster import (
    AssetKey,
    AssetMaterialization,
    In,
    Nothing,
    OpDefinition,
    OpExecutionContext,
    Out,
    Output,
    job,
    op,
)

from orchestration.assets.wind import IngestRunConfig, _ingest, _source_pit_grade
from quantagent.ingest.sources.wind.tables import WIND_PAGED_TABLES

if TYPE_CHECKING:
    from orchestration.resources.wind import WindIngestResource

# 负责人给定的初始化优先级；日常增量不使用这个顺序。
INITIAL_BACKFILL_ORDER = (
    "ASHAREST",
    "ASHAREEODDERIVATIVEINDICATOR",
    "ASHAREDESCRIPTION",
    "ASHARECALENDAR",
    "AINDEXMEMBERSCITICS",
    "AINDEXMEMBERSCITICS2",
    "AINDEXMEMBERSCITICS3",
    "AINDEXMEMBERS",
    "SWINDEXMEMBERS",
    "ASHAREEODPRICES",
    "AINDEXEODPRICES",
    "ASHAREPROFITNOTICE",
    "ASHAREDIVIDEND",
    "ASHAREFINANCIALINDICATOR",
    "ASHAREBALANCESHEET",
    "ASHAREINCOME",
    "ASHARECASHFLOW",
    "ASHAREMARGINTRADESUM",
    "ASHARETRADINGSUSPENSION",
    "AINDEXINDUSTRIESEODCITICS",
    "AINDEXVALUATION",
    "ASHAREMARGINTRADE",
    "CHINAMUTUALFUNDSTOCKPORTFOLIO",
    "ASHAREMONEYFLOW",
)
if len(INITIAL_BACKFILL_ORDER) != len(set(INITIAL_BACKFILL_ORDER)) or set(
    INITIAL_BACKFILL_ORDER
) != set(WIND_PAGED_TABLES):
    raise ValueError("Wind 初始化回填顺序必须完整覆盖分页表且不能重复")


def _make_initial_op(table: str, *, first: bool) -> OpDefinition:
    spec = WIND_PAGED_TABLES[table].spec
    pit_grade = _source_pit_grade(table, spec.dataset)

    @op(
        name=f"initial_{table.lower()}",
        ins={} if first else {"previous": In(Nothing)},
        out=Out(Nothing),
        required_resource_keys={"wind_ingest"},
    )
    def _initial(
        context: OpExecutionContext, config: IngestRunConfig
    ) -> Iterator[AssetMaterialization | Output[None]]:
        resource: WindIngestResource = context.resources.wind_ingest
        result = _ingest(
            table,
            pit_grade=pit_grade,
            config=config,
            wind_ingest=resource,
            stop_run_id=context.run_id,
        )
        yield AssetMaterialization(
            asset_key=AssetKey(f"src_wind_{table.lower()}"), metadata=result.metadata
        )
        yield Output(None)

    return _initial


_INITIAL_OPS = tuple(
    _make_initial_op(table, first=index == 0) for index, table in enumerate(INITIAL_BACKFILL_ORDER)
)


def initial_run_config(today: str) -> dict[str, object]:
    """显式真写和每页 1000 行，数据库写闸仍由采集函数检查。"""
    return {
        "ops": {
            f"initial_{table.lower()}": {
                "config": {"as_of": today, "write_db": True, "max_pages": None, "page_size": 1000}
            }
            for table in INITIAL_BACKFILL_ORDER
        }
    }


@job
def wind_initial_backfill() -> None:
    previous = _INITIAL_OPS[0]()
    for initial_op in _INITIAL_OPS[1:]:
        previous = initial_op(previous=previous)
