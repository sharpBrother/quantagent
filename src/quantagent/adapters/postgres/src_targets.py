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

ASHAREEODPRICES = SrcTableWriteSpec(
    # 契约 dataset 必须小写；PG 表名保持 Wind 大写原名。
    dataset="src.wind.ashareeodprices",
    pg_schema="src_wind",
    pg_table="ASHAREEODPRICES",
    native_columns=(
        "OBJECT_ID",
        "S_INFO_WINDCODE",
        "TRADE_DT",
        "CRNCY_CODE",
        "S_DQ_PRECLOSE",
        "S_DQ_OPEN",
        "S_DQ_HIGH",
        "S_DQ_LOW",
        "S_DQ_CLOSE",
        "S_DQ_CHANGE",
        "S_DQ_PCTCHANGE",
        "S_DQ_VOLUME",
        "S_DQ_AMOUNT",
        "S_DQ_ADJPRECLOSE",
        "S_DQ_ADJOPEN",
        "S_DQ_ADJHIGH",
        "S_DQ_ADJLOW",
        "S_DQ_ADJCLOSE",
        "S_DQ_ADJFACTOR",
        "S_DQ_AVGPRICE",
        "S_DQ_TRADESTATUS",
        "S_DQ_TRADESTATUSCODE",
        "S_DQ_LIMIT",
        "S_DQ_STOPPING",
        "OPDATE",
        "OPMODE",
        "S_DQ_ADJCLOSE_BACKWARD",
        "GSUPDTIME",
        "gsUTime",
        "gsCTime",
        "mopdate",
    ),
    keys=("OBJECT_ID",),
)
