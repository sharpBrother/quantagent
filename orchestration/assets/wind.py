"""Wind 日历采集、标准日历物化、分页表采集。
这些资产不按交易日分区。采集的续跑身份是 ``OPDATE + OBJECT_ID`` 页尾游标，
一页可以跨多个交易日；标准日历是整表快照，读取时才按 ``as_of`` 截断。
交易日分区留给以后按日消费的资产。
不使用 ``from __future__ import annotations``：Dagster 要在导入时解析
Config 与 ResourceParam 的注解。
"""

from datetime import date, datetime
from functools import cache

from dagster import AssetsDefinition, Config, MaterializeResult, ResourceParam, asset

from orchestration.resources.wind import TradeCalendarResource, WindIngestResource
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.errors import MissingVisibilityError
from quantagent.ingest.sources.wind.tables import WIND_PAGED_TABLES

_GROUP = "wind"
# 这些表只经股票池函数读取，不做 PIT 查询，没有可见性契约。
# 写成常量而不是放进 contracts/：它们是"明确不做 PIT"的声明，不是漏配。
NOT_PIT_WIND_TABLES: frozenset[str] = frozenset(
    {
        "ASHAREDESCRIPTION",
        "AINDEXMEMBERS",
        "AINDEXMEMBERSCITICS",
        "AINDEXMEMBERSCITICS2",
        "AINDEXMEMBERSCITICS3",
        "SWINDEXMEMBERS",
        # ST 区间只经 domain.universe.st 的 st_codes_at 读取（2026-11-17 裁定）。
        "ASHAREST",
    }
)
# 这些表的可见性规则尚未裁定。写 "unconfigured" 让资产可以物化，但 pit_grade 不冒充已配置。
UNCONFIGURED_WIND_TABLES: frozenset[str] = frozenset()


class IngestRunConfig(Config):
    as_of: str
    write_db: bool = False
    # None 表示不限页，一直读到源端没有下一页。干跑时 ingest_wind_paged 仍只读一页。
    max_pages: int | None = 1
    page_size: int = 1000


class CalendarMaterializeConfig(Config):
    as_of: str
    rebuild: bool = False
    # 追加模式：只写快照里新出现的日期，既有分片不动。日更使用此模式。
    append_only: bool = False
    # 非 None 时只保留 cal_dt <= as_of + horizon_days 的行。
    horizon_days: int | None = None


def _as_of(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"as_of 必须是 YYYY-MM-DD: {value}") from exc


@cache
def _visibilities() -> dict[str, VisibilityContract]:
    # 导入期为每个资产取 pit_grade。契约只解析一次：逐个调用 load_bundle 在执行机上要 10 秒以上。
    return dict(load_bundle().visibilities)


def _pit_grade(dataset: str) -> str:
    contract = _visibilities().get(dataset)
    if contract is None:
        raise MissingVisibilityError(dataset)
    return contract.visibility.grade


def _source_pit_grade(table: str, dataset: str) -> str:
    if table in NOT_PIT_WIND_TABLES:
        return "not_pit"
    if table in UNCONFIGURED_WIND_TABLES:
        return "unconfigured"
    # 其余表必须有契约，缺失时在导入期抛错（fail-closed）。
    return _pit_grade(dataset)


def _ingest(
    table: str,
    *,
    pit_grade: str,
    config: IngestRunConfig,
    wind_ingest: WindIngestResource,
) -> MaterializeResult[None]:
    parsed = _as_of(config.as_of)
    result = wind_ingest.ingest(
        table,
        write_db=config.write_db,
        page_size=config.page_size,
        max_pages=config.max_pages,
    )
    return MaterializeResult(
        metadata={
            "row_count": result.row_count,
            "dml_count": result.dml_count,
            "pages": result.pages,
            "replaced": result.replaced,
            "deleted": result.deleted,
            "metadata_skipped": result.metadata_skipped,
            "as_of": parsed.isoformat(),
            "pit_grade": pit_grade,
            "digest": result.output_digest,
            "source_cursor": result.source_cursor,
        }
    )


def _make_source_asset(table: str) -> AssetsDefinition:
    """每张已接入的 Wind 分页表一个资产，名字为 ``src_wind_<表名小写>``。"""
    spec = WIND_PAGED_TABLES[table].spec
    pit_grade = _source_pit_grade(table, spec.dataset)

    @asset(
        name=f"src_wind_{table.lower()}",
        group_name=_GROUP,
        metadata={
            "reads": f"wind_db.dbo.{table}",
            "checkpoint": "source_cursor",
            "pit_grade": pit_grade,
        },
    )
    def _source(
        config: IngestRunConfig,
        wind_ingest: ResourceParam[WindIngestResource],
    ) -> MaterializeResult[None]:
        return _ingest(table, pit_grade=pit_grade, config=config, wind_ingest=wind_ingest)

    return _source


_SOURCE_ASSETS_BY_TABLE: dict[str, AssetsDefinition] = {
    table: _make_source_asset(table) for table in WIND_PAGED_TABLES
}
WIND_SOURCE_ASSETS: tuple[AssetsDefinition, ...] = tuple(_SOURCE_ASSETS_BY_TABLE.values())

src_wind_asharecalendar = _SOURCE_ASSETS_BY_TABLE["ASHARECALENDAR"]
src_wind_ashareeodprices = _SOURCE_ASSETS_BY_TABLE["ASHAREEODPRICES"]


@asset(
    group_name=_GROUP,
    deps=[src_wind_asharecalendar],
    metadata={
        "reads": "src.wind.asharecalendar",
        "checkpoint": "snapshot",
        "pit_grade": _pit_grade("std.trade_calendar"),
    },
)
def std_trade_calendar(
    config: CalendarMaterializeConfig,
    trade_calendar: ResourceParam[TradeCalendarResource],
) -> MaterializeResult[None]:
    parsed = _as_of(config.as_of)
    result = trade_calendar.materialize(
        as_of=parsed,
        rebuild=config.rebuild,
        append_only=config.append_only,
        horizon_days=config.horizon_days,
    )
    return MaterializeResult(
        metadata={
            "row_count": result.row_count,
            "appended": result.appended,
            "rebuilt": result.rebuilt,
            "as_of": parsed.isoformat(),
            "pit_grade": _pit_grade("std.trade_calendar"),
            "digest": result.output_digest,
        }
    )
