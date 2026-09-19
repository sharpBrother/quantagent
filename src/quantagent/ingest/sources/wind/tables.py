"""Wind 分页表白名单。源表名必须来自这里，不能从运行时 SQL 拼出来。"""

from __future__ import annotations

from dataclasses import dataclass

from quantagent.adapters.postgres.src_targets import ASHAREEODPRICES, SrcTableWriteSpec
from quantagent.ingest.errors import TargetNotAllowedError


@dataclass(frozen=True)
class WindPagedTable:
    source_table: str
    spec: SrcTableWriteSpec
    chi_fields: tuple[str, ...]


WIND_PAGED_TABLES: dict[str, WindPagedTable] = {
    "ASHAREEODPRICES": WindPagedTable(
        source_table="ASHAREEODPRICES",
        spec=ASHAREEODPRICES,
        # 旧仓 update_stock_daily_paged(chi_field=['S_DQ_TRADESTATUS'])
        chi_fields=("S_DQ_TRADESTATUS",),
    ),
}


def resolve_wind_paged_table(name: str) -> WindPagedTable:
    table = WIND_PAGED_TABLES.get(name)
    if table is None:
        raise TargetNotAllowedError(f"Wind 分页表不在白名单: {name}")
    return table
