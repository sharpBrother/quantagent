"""源表物理身份。写入白名单仍由 ingest 持有，避免适配器决定谁能写。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SrcTableWriteSpec:
    dataset: str
    pg_schema: str
    pg_table: str
    native_columns: tuple[str, ...]
    keys: tuple[str, ...]

    @property
    def qualified_table(self) -> str:
        return f"{self.pg_schema}.{self.pg_table}"


TRADE_CAL = SrcTableWriteSpec(
    dataset="src.tushare.trade_cal",
    pg_schema="src_tushare",
    pg_table="trade_cal",
    native_columns=("exchange", "cal_date", "is_open", "pretrade_date"),
    keys=("exchange", "cal_date"),
)
