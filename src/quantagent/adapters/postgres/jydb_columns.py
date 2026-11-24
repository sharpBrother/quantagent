"""聚源 JYDB P0/P1 源表采集列。

列与源端 ``INFORMATION_SCHEMA.COLUMNS`` 在 2026-11-23 核对一致，顺序保持
``ordinal_position``。技术列 ``_batch_id`` / ``_ingested_at`` / ``_row_hash``
不在这里，由写入器追加。
"""

from __future__ import annotations

JYDB_SYNC: tuple[str, ...] = (
    "C_ED_MacroIndicatorData",
    "C_ED_IndicatorMain",
    "ED_MoneySupply",
    "C_IN_IndicatorDataV",
    "C_IN_IndicatorMain",
    "QT_OSIndexQuote",
)

C_ED_MacroIndicatorData_COLUMNS: tuple[str, ...] = (
    "ID",
    "IndicatorCode",
    "InfoPublDate",
    "EndDate",
    "DataValue",
    "PowerNumber",
    "UpdateTime",
    "JSID",
)

C_ED_IndicatorMain_COLUMNS: tuple[str, ...] = (
    "ID",
    "IndicatorCode",
    "IndicatorName",
    "InfoSourceCode",
    "InfoSource",
    "PowerNumber",
    "IndiDimension",
    "IndiCategory",
    "IndiState",
    "BeginDate",
    "EndDate",
    "UnitCode",
    "UnitCodeReport",
    "DisclosureFrequency",
    "IndiRemark",
    "UpdateTime",
    "JSID",
    "DataTable",
    "InsertTime",
)

ED_MoneySupply_COLUMNS: tuple[str, ...] = (
    "ID",
    "EndDate",
    "InfoSource",
    "AdjustMark",
    "DataType",
    "ReportArea",
    "M2",
    "M1",
    "M0",
    "DemandDeposits",
    "QuasiMoney",
    "QMTimeDep",
    "QMSavingDep",
    "QMOtherDep",
    "NetIssueMonthly",
    "AvgOfferedRateMonthly",
    "OfferedTurnoverMonthly",
    "M2GrowthYoY",
    "M1GrowthYoY",
    "M0GrowthYoY",
    "DemandDepositsGrowthYoY",
    "QuasiMoneyGrowthYoY",
    "QMTimeDepGrowthYoY",
    "QMSavingDepGrowthYoY",
    "QMOtherDepGrowthYoY",
    "Remarks",
    "XGRQ",
    "JSID",
    "InfoPublDate",
)

C_IN_IndicatorDataV_COLUMNS: tuple[str, ...] = (
    "ID",
    "IndicatorCode",
    "InfoPublDate",
    "BeginDate",
    "EndDate",
    "DataValue",
    "PowerNumber",
    "UpdateTime",
    "JSID",
)

C_IN_IndicatorMain_COLUMNS: tuple[str, ...] = (
    "ID",
    "IndicatorCode",
    "IndicatorName",
    "InfoSourceCode",
    "InfoSource",
    "PowerNumber",
    "IndiState",
    "BeginDate",
    "EndDate",
    "UnitCode",
    "UnitCodeReport",
    "DisclosureFrequency",
    "IndiRemark",
    "UpdateTime",
    "JSID",
    "InsertTime",
)

QT_OSIndexQuote_COLUMNS: tuple[str, ...] = (
    "ID",
    "IndexCode",
    "TradingDay",
    "RevealIndices",
    "RevealInstiCode",
    "TransCurrency",
    "PrevClosePrice",
    "OpenPrice",
    "HighPrice",
    "LowPrice",
    "ClosePrice",
    "TurnoverVolume",
    "TurnoverValue",
    "ChangeOF",
    "ChangePCT",
    "UpdateTime",
    "JSID",
    "InsertTime",
)
