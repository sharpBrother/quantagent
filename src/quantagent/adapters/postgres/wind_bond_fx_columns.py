"""债券曲线、债券回购与外汇的 Wind 源表采集列。

列与 0019_bond_fx_wind_tables.sql 的 CREATE 一致，顺序相同，去掉 _batch_id、_ingested_at、
_row_hash 三个技术列。0019 之前 0003 的建表与源端不符（缺主键，或多出 GSUPDTIME），
所以这六张表是删表重建的，列清单以 0019 为准。采集前与 wind_db 的列清单对一次，不一致就停。
CBONDCURVECNBD 与 CBONDCURVECSI 只采子集，子集范围见 quantagent.ingest.sources.wind.tables 的
source_filter，这里的列清单是整表列，不因过滤而变。
"""

from __future__ import annotations

# 顺序：曲线在前，其后回购与外汇。与 0019 的 CREATE 顺序一致。
BOND_FX_WIND_SYNC: tuple[str, ...] = (
    "CBONDCURVECNBD",
    "CBONDREPOANDIBLEODPRICES",
    "CBONDCURVECSI",
    "FXEODPRICES",
    "CBONDPRICESREPO",
    "CBONDREPO",
)

CBONDCURVECNBD_COLUMNS: tuple[str, ...] = (
    "OBJECT_ID",
    "TRADE_DT",
    "B_ANAL_CURVENUMBER",
    "B_ANAL_CURVENAME",
    "B_ANAL_CURVETYPE",
    "B_ANAL_CURVETERM",
    "B_ANAL_YIELD",
    "B_ANAL_BASE_YIELD",
    "B_ANAL_YIELD_TOTAL",
    "OPDATE",
    "OPMODE",
    "gsUTime",
    "gsCTime",
    "mopdate",
)

CBONDCURVECSI_COLUMNS: tuple[str, ...] = (
    "OBJECT_ID",
    "TRADE_DT",
    "B_ANAL_CURVENUMBER",
    "B_ANAL_CURVENAME",
    "B_ANAL_CURVETYPE",
    "B_ANAL_CURVETERM",
    "B_ANAL_YIELD",
    "OPDATE",
    "OPMODE",
    "gsUTime",
    "mopdate",
    "gsCTime",
)

CBONDREPOANDIBLEODPRICES_COLUMNS: tuple[str, ...] = (
    "OBJECT_ID",
    "S_INFO_WINDCODE",
    "TRADE_DT",
    "S_DQ_OPEN",
    "S_DQ_HIGH",
    "S_DQ_LOW",
    "S_DQ_CLOSE",
    "B_DQ_WAVERAGERATE",
    "S_DQ_VOLUME",
    "S_DQ_AMOUNT",
    "OPDATE",
    "OPMODE",
    "gsCTime",
    "gsUTime",
    "mopdate",
)

CBONDPRICESREPO_COLUMNS: tuple[str, ...] = (
    "OBJECT_ID",
    "S_INFO_WINDCODE",
    "TRADE_DT",
    "S_DQ_OPEN",
    "S_DQ_HIGH",
    "S_DQ_LOW",
    "S_DQ_CLOSE",
    "S_DQ_AVGPRICE",
    "S_DQ_VOLUME",
    "S_DQ_AMOUNT",
    "OPDATE",
    "OPMODE",
    "gsCTime",
    "gsUTime",
    "mopdate",
)

CBONDREPO_COLUMNS: tuple[str, ...] = (
    "OBJECT_ID",
    "TRADE_DT",
    "B_INFO_TERM",
    "B_TENDER_INTERESTRATE",
    "B_TENDER_AMOUNT",
    "B_TENDER_METHOD",
    "B_INFO_REPO_TYPE",
    "B_INFO_TERM_WORDS",
    "OPDATE",
    "OPMODE",
    "gsCTime",
    "gsUTime",
    "mopdate",
)

FXEODPRICES_COLUMNS: tuple[str, ...] = (
    "OBJECT_ID",
    "TRADE_DT",
    "S_INFO_WINDCODE",
    "S_DQ_OPEN",
    "S_DQ_HIGH",
    "S_DQ_LOW",
    "S_DQ_CLOSE",
    "WINDCODE",
    "S_DQ_BUY",
    "S_DQ_SELL",
    "OPDATE",
    "OPMODE",
    "mopdate",
    "gsCTime",
    "gsUTime",
    "SEC_ID",
)
