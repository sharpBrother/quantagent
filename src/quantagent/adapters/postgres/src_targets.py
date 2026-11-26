"""源表物理身份。写入白名单仍由 ingest 持有，避免适配器决定谁能写。"""

from __future__ import annotations

from dataclasses import dataclass

from quantagent.adapters.postgres import jydb_columns as _jydb
from quantagent.adapters.postgres import suntime_columns as _suntime
from quantagent.adapters.postgres import wind_bond_fx_columns as _bond_fx
from quantagent.adapters.postgres import wind_first_batch_columns as _first_batch
from quantagent.adapters.postgres import wind_index_description_columns as _index_description
from quantagent.adapters.postgres.wind_bond_fx_columns import BOND_FX_WIND_SYNC
from quantagent.adapters.postgres.wind_first_batch_columns import (
    FIRST_BATCH_WIND_SYNC,
)
from quantagent.adapters.postgres.wind_index_description_columns import (
    INDEX_DESCRIPTION_WIND_SYNC,
)
from quantagent.adapters.postgres.wind_large_columns import (
    AINDEXVALUATION_COLUMNS,
    ASHAREBALANCESHEET_COLUMNS,
    ASHARECASHFLOW_COLUMNS,
    ASHAREEODDERIVATIVEINDICATOR_COLUMNS,
    ASHAREINCOME_COLUMNS,
    ASHAREMONEYFLOW_COLUMNS,
)


@dataclass(frozen=True)
class SrcTableWriteSpec:
    dataset: str
    pg_schema: str
    pg_table: str
    native_columns: tuple[str, ...]
    keys: tuple[str, ...]
    # 源端系统列：版本序列与同步时间戳。它们变化不算业务修订，不进指纹与逐列比较。
    system_columns: tuple[str, ...] = ()

    @property
    def qualified_table(self) -> str:
        return f"{self.pg_schema}.{self.pg_table}"


# 聚源 JYDB P0/P1。主键一律是源端 ID；分页游标是 (JSID, ID)，
# 所以 JSID 属于游标而不是业务列，和同步时间列一起排除在业务比较之外。
JYDB_SPECS: dict[str, SrcTableWriteSpec] = {
    "C_ED_MacroIndicatorData": SrcTableWriteSpec(
        dataset="src.jydb.c_ed_macroindicatordata",
        pg_schema="src_jydb",
        pg_table="C_ED_MacroIndicatorData",
        native_columns=_jydb.C_ED_MacroIndicatorData_COLUMNS,
        keys=("ID",),
        system_columns=("JSID", "UpdateTime"),
    ),
    "C_ED_IndicatorMain": SrcTableWriteSpec(
        dataset="src.jydb.c_ed_indicatormain",
        pg_schema="src_jydb",
        pg_table="C_ED_IndicatorMain",
        native_columns=_jydb.C_ED_IndicatorMain_COLUMNS,
        keys=("ID",),
        system_columns=("JSID", "UpdateTime", "InsertTime"),
    ),
    "ED_MoneySupply": SrcTableWriteSpec(
        dataset="src.jydb.ed_moneysupply",
        pg_schema="src_jydb",
        pg_table="ED_MoneySupply",
        native_columns=_jydb.ED_MoneySupply_COLUMNS,
        keys=("ID",),
        system_columns=("JSID", "XGRQ"),
    ),
    "C_IN_IndicatorDataV": SrcTableWriteSpec(
        dataset="src.jydb.c_in_indicatordatav",
        pg_schema="src_jydb",
        pg_table="C_IN_IndicatorDataV",
        native_columns=_jydb.C_IN_IndicatorDataV_COLUMNS,
        keys=("ID",),
        system_columns=("JSID", "UpdateTime"),
    ),
    "C_IN_IndicatorMain": SrcTableWriteSpec(
        dataset="src.jydb.c_in_indicatormain",
        pg_schema="src_jydb",
        pg_table="C_IN_IndicatorMain",
        native_columns=_jydb.C_IN_IndicatorMain_COLUMNS,
        keys=("ID",),
        system_columns=("JSID", "UpdateTime", "InsertTime"),
    ),
    "QT_OSIndexQuote": SrcTableWriteSpec(
        dataset="src.jydb.qt_osindexquote",
        pg_schema="src_jydb",
        pg_table="QT_OSIndexQuote",
        native_columns=_jydb.QT_OSIndexQuote_COLUMNS,
        keys=("ID",),
        system_columns=("JSID", "UpdateTime", "InsertTime"),
    ),
}

# 朝阳永续 P0/P1。主键一律是源端 id；分页游标是 (tmstamp, id)，
# 所以 tmstamp 属于游标而不是业务列。entrytime、updatetime 是源端同步时间，
# 变化不算业务修订。rpt_earnings_adjust 只建镜像，不写可见性契约。
SUNTIME_SPECS: dict[str, SrcTableWriteSpec] = {
    name: SrcTableWriteSpec(
        dataset=f"src.suntime.{name}",
        pg_schema="src_suntime",
        pg_table=name,
        native_columns=getattr(_suntime, f"{name}_COLUMNS"),
        keys=("id",),
        system_columns=("entrytime", "updatetime", "tmstamp"),
    )
    for name in _suntime.SUNTIME_SYNC
}

TRADE_CAL = SrcTableWriteSpec(
    dataset="src.tushare.trade_cal",
    pg_schema="src_tushare",
    pg_table="trade_cal",
    native_columns=("exchange", "cal_date", "is_open", "pretrade_date"),
    keys=("exchange", "cal_date"),
)

# Tushare shibor 是长表：一行一个 (trade_date, maturity)。源端不给版本身份，按
# ADR 2026-11-18 全自动跟随源端。native_columns 顺序与 0004_tushare.sql 的列序一致。
SHIBOR = SrcTableWriteSpec(
    dataset="src.tushare.shibor",
    pg_schema="src_tushare",
    pg_table="shibor",
    native_columns=("trade_date", "maturity", "rate", "source", "ingested_at"),
    keys=("trade_date", "maturity"),
)

# Tushare us_tycr 同为长表：一行一个 (trade_date, maturity)，源端不给版本身份，同样跟随源端。
# native_columns 顺序与 0004_tushare.sql 的列序一致。
US_TREASURY_YIELD = SrcTableWriteSpec(
    dataset="src.tushare.us_treasury_yield",
    pg_schema="src_tushare",
    pg_table="us_treasury_yield",
    native_columns=("trade_date", "maturity", "yield", "source", "ingested_at"),
    keys=("trade_date", "maturity"),
)
# FRED／ALFRED 带版本观测。主键含 realtime_start，一个 (序列, 观测日) 可有多行历史版本。
# 同一版本的 realtime_end 在源端被新版本取代后会从 9999-12-31 改成具体日期，这是同键值变，
# 由写入器按跟随源端规则替换（计入 replaced）。native_columns 顺序与 0018_macro_source_tables.sql 一致。
# 0018 起的新表不再建原生 ingested_at 列，采集时刻只写 _ingested_at。
FRED_OBSERVATION_VINTAGE = SrcTableWriteSpec(
    dataset="src.macro.fred_observation_vintage",
    pg_schema="src_macro",
    pg_table="fred_observation_vintage",
    native_columns=(
        "series_id",
        "observation_date",
        "realtime_start",
        "realtime_end",
        "value",
        "source",
    ),
    keys=("series_id", "observation_date", "realtime_start"),
)

# GPR 日频是长表：一行一个 (series_id, observation_date, file_vintage)。文件没有版本字段，
# file_vintage 是文件内最大 DAY 的近似，所以版本身份由 file_vintage 与 file_sha256 共同表达。
# 同一 file_vintage 被源端改写时，file_sha256 变化，按跟随源端规则整键替换。
# native_columns 顺序与 0018_macro_source_tables.sql 的列序一致。
GPR_DAILY = SrcTableWriteSpec(
    dataset="src.macro.gpr_daily",
    pg_schema="src_macro",
    pg_table="gpr_daily",
    native_columns=(
        "series_id",
        "observation_date",
        "file_vintage",
        "value",
        "file_sha256",
        "source",
    ),
    keys=("series_id", "observation_date", "file_vintage"),
)

# wx2 中的 record_hash 是源表主键；保留原有字段以便逐行对账。
WGC_GOLD_DEMAND = SrcTableWriteSpec(
    dataset="src.macro.macro_wgc_gold_demand",
    pg_schema="src_macro",
    pg_table="macro_wgc_gold_demand",
    native_columns=(
        "period_end",
        "geography",
        "category",
        "value_tonnes",
        "publish_date",
        "source",
        "file_sha256",
        "record_hash",
        "ingested_at",
    ),
    keys=("record_hash",),
)

# 源事件身份由金十指标、发布日期和事件 ID 共同确定，不能用采集时间代替版本。
JIN10_ECONOMIC_CALENDAR = SrcTableWriteSpec(
    dataset="src.macro.jin10_economic_calendar",
    pg_schema="src_macro",
    pg_table="jin10_economic_calendar",
    native_columns=(
        "indicator_id",
        "publish_date",
        "data_id",
        "period_end",
        "time_period",
        "published_at",
        "actual_value",
        "forecast_value",
        "previous_value",
        "revised_value",
        "source",
    ),
    keys=("indicator_id", "publish_date", "data_id"),
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


def _wind_table(name: str, columns: tuple[str, ...]) -> SrcTableWriteSpec:
    return SrcTableWriteSpec(
        dataset=f"src.wind.{name.lower()}",
        pg_schema="src_wind",
        pg_table=name,
        native_columns=columns,
        keys=("OBJECT_ID",),
    )


ASHAREMONEYFLOW = _wind_table("ASHAREMONEYFLOW", ASHAREMONEYFLOW_COLUMNS)
ASHAREEODDERIVATIVEINDICATOR = _wind_table(
    "ASHAREEODDERIVATIVEINDICATOR",
    ASHAREEODDERIVATIVEINDICATOR_COLUMNS,
)
ASHARECASHFLOW = _wind_table("ASHARECASHFLOW", ASHARECASHFLOW_COLUMNS)
ASHAREINCOME = _wind_table("ASHAREINCOME", ASHAREINCOME_COLUMNS)
ASHAREBALANCESHEET = _wind_table("ASHAREBALANCESHEET", ASHAREBALANCESHEET_COLUMNS)
AINDEXVALUATION = _wind_table("AINDEXVALUATION", AINDEXVALUATION_COLUMNS)


# 第一批其余常规 Wind 表，按 FIRST_BATCH_WIND_SYNC 顺序。名字即 PG 表名与源表名。
FIRST_BATCH_WIND_SPECS: dict[str, SrcTableWriteSpec] = {
    name: _wind_table(name, getattr(_first_batch, f"{name}_COLUMNS"))
    for name in FIRST_BATCH_WIND_SYNC
}
# 债券曲线、债券回购与外汇。曲线表只是源表的子集镜像，过滤条件在 ingest 的分页白名单里，
# 不在这里：写入规格只描述列与主键。
BOND_FX_WIND_SPECS: dict[str, SrcTableWriteSpec] = {
    name: _wind_table(name, getattr(_bond_fx, f"{name}_COLUMNS")) for name in BOND_FX_WIND_SYNC
}
# 指数基本资料两张表全表镜像。AINDEXDESCRIPTION 是 AINDEXINDUSTRIESCITICS 视图的源（0020）。
INDEX_DESCRIPTION_WIND_SPECS: dict[str, SrcTableWriteSpec] = {
    name: _wind_table(name, getattr(_index_description, f"{name}_COLUMNS"))
    for name in INDEX_DESCRIPTION_WIND_SYNC
}
