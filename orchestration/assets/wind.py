"""Wind 日历采集、标准日历物化、日行情采集。

这三个资产不按交易日分区。采集的续跑身份是 ``OPDATE + OBJECT_ID`` 页尾游标，
一页可以跨多个交易日；标准日历是整表快照，读取时才按 ``as_of`` 截断。
交易日分区留给以后按日消费的资产。

不使用 ``from __future__ import annotations``：Dagster 要在导入时解析
Config 与 ResourceParam 的注解。
"""

from datetime import date, datetime

from dagster import Config, MaterializeResult, ResourceParam, asset

from orchestration.resources.wind import TradeCalendarResource, WindIngestResource
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import MissingVisibilityError

_GROUP = "wind"


class IngestRunConfig(Config):
    as_of: str
    write_db: bool = False
    max_pages: int = 1
    page_size: int = 1000


class CalendarMaterializeConfig(Config):
    as_of: str
    rebuild: bool = False


def _as_of(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"as_of 必须是 YYYY-MM-DD: {value}") from exc


def _pit_grade(dataset: str) -> str:
    contract = load_bundle().visibilities.get(dataset)
    if contract is None:
        raise MissingVisibilityError(dataset)
    return contract.visibility.grade


def _ingest(
    table: str,
    dataset: str,
    *,
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
            "as_of": parsed.isoformat(),
            "pit_grade": _pit_grade(dataset),
            "digest": result.output_digest,
            "source_cursor": result.source_cursor,
        }
    )


@asset(
    group_name=_GROUP,
    metadata={
        "reads": "wind_db.dbo.ASHARECALENDAR",
        "checkpoint": "source_cursor",
        "pit_grade": _pit_grade("src.wind.asharecalendar"),
    },
)
def src_wind_asharecalendar(
    config: IngestRunConfig,
    wind_ingest: ResourceParam[WindIngestResource],
) -> MaterializeResult[None]:
    return _ingest(
        "ASHARECALENDAR",
        "src.wind.asharecalendar",
        config=config,
        wind_ingest=wind_ingest,
    )


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
    result = trade_calendar.materialize(as_of=parsed, rebuild=config.rebuild)
    return MaterializeResult(
        metadata={
            "row_count": result.row_count,
            "as_of": parsed.isoformat(),
            "pit_grade": _pit_grade("std.trade_calendar"),
            "digest": result.output_digest,
        }
    )


@asset(
    group_name=_GROUP,
    metadata={
        "reads": "wind_db.dbo.ASHAREEODPRICES",
        "checkpoint": "source_cursor",
        "pit_grade": _pit_grade("src.wind.ashareeodprices"),
    },
)
def src_wind_ashareeodprices(
    config: IngestRunConfig,
    wind_ingest: ResourceParam[WindIngestResource],
) -> MaterializeResult[None]:
    return _ingest(
        "ASHAREEODPRICES",
        "src.wind.ashareeodprices",
        config=config,
        wind_ingest=wind_ingest,
    )
