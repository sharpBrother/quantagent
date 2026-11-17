"""Wind 分页表白名单。源表名必须来自这里，不能从运行时 SQL 拼出来。"""

from __future__ import annotations

from dataclasses import dataclass

from quantagent.adapters.postgres.src_targets import (
    AINDEXEODPRICES,
    AINDEXVALUATION,
    ASHAREBALANCESHEET,
    ASHARECALENDAR,
    ASHARECASHFLOW,
    ASHAREEODDERIVATIVEINDICATOR,
    ASHAREEODPRICES,
    ASHAREINCOME,
    ASHAREMONEYFLOW,
    SrcTableWriteSpec,
)
from quantagent.ingest.errors import TargetNotAllowedError


@dataclass(frozen=True)
class WindPagedTable:
    source_table: str
    spec: SrcTableWriteSpec
    chi_fields: tuple[str, ...]


WIND_PAGED_TABLES: dict[str, WindPagedTable] = {
    "ASHARECALENDAR": WindPagedTable(
        source_table="ASHARECALENDAR",
        spec=ASHARECALENDAR,
        chi_fields=(),
    ),
    "ASHAREEODPRICES": WindPagedTable(
        source_table="ASHAREEODPRICES",
        spec=ASHAREEODPRICES,
        # 旧仓 update_stock_daily_paged(chi_field=['S_DQ_TRADESTATUS'])
        chi_fields=("S_DQ_TRADESTATUS",),
    ),
    "AINDEXEODPRICES": WindPagedTable(
        source_table="AINDEXEODPRICES",
        spec=AINDEXEODPRICES,
        chi_fields=(),
    ),
    "ASHAREMONEYFLOW": WindPagedTable(
        source_table="ASHAREMONEYFLOW",
        spec=ASHAREMONEYFLOW,
        chi_fields=(),
    ),
    "ASHAREEODDERIVATIVEINDICATOR": WindPagedTable(
        source_table="ASHAREEODDERIVATIVEINDICATOR",
        spec=ASHAREEODDERIVATIVEINDICATOR,
        chi_fields=(),
    ),
    "ASHARECASHFLOW": WindPagedTable(
        source_table="ASHARECASHFLOW",
        spec=ASHARECASHFLOW,
        chi_fields=(),
    ),
    "ASHAREINCOME": WindPagedTable(
        source_table="ASHAREINCOME",
        spec=ASHAREINCOME,
        chi_fields=(),
    ),
    "ASHAREBALANCESHEET": WindPagedTable(
        source_table="ASHAREBALANCESHEET",
        spec=ASHAREBALANCESHEET,
        chi_fields=(),
    ),
    "AINDEXVALUATION": WindPagedTable(
        source_table="AINDEXVALUATION",
        spec=AINDEXVALUATION,
        chi_fields=(),
    ),
}


def resolve_wind_paged_table(name: str) -> WindPagedTable:
    table = WIND_PAGED_TABLES.get(name)
    if table is None:
        raise TargetNotAllowedError(f"Wind 分页表不在白名单: {name}")
    return table
