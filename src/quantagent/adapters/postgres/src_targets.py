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

ASHARECALENDAR = SrcTableWriteSpec(
    dataset="src.wind.asharecalendar",
    pg_schema="src_wind",
    pg_table="ASHARECALENDAR",
    native_columns=(
        "OBJECT_ID",
        "TRADE_DAYS",
        "S_INFO_EXCHMARKET",
        "OPDATE",
        "OPMODE",
        "gsCTime",
        "gsUTime",
        "mopdate",
    ),
    keys=("OBJECT_ID",),
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
        # GSUPDTIME 是 SQL Server rowversion，当前 wind_db 全库不提供（列清单由公司端核对）。
        # 物理表仍保留该 nullable 列以匹配已应用的 0003_wind.sql，故不进读取、写入与内容指纹。
        "gsUTime",
        "gsCTime",
        "mopdate",
    ),
    keys=("OBJECT_ID",),
)

AINDEXEODPRICES = SrcTableWriteSpec(
    dataset="src.wind.aindexeodprices",
    pg_schema="src_wind",
    pg_table="AINDEXEODPRICES",
    # 只采集 wind_db.dbo.AINDEXEODPRICES 的列。物理表多出的 19 个简介列
    # 来自已应用的 0003_wind.sql，源表没有，不读、不写、不进内容指纹。
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
        "SEC_ID",
        "OPDATE",
        "OPMODE",
        "gsCTime",
        "gsUTime",
        "mopdate",
    ),
    keys=("OBJECT_ID",),
)
