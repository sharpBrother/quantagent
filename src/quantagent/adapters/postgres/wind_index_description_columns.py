"""Wind 指数基本资料两张源表的采集列：AINDEXDESCRIPTION 与 AINDEXDESCRIPTIONZL。

列与 0020_aindexdescription.sql 的 CREATE 一致，顺序相同，去掉 _batch_id、_ingested_at、
_row_hash 三个技术列。两张表列完全相同，各约 12 万行，主键 OBJECT_ID。
AINDEXDESCRIPTIONZL 只镜像，不参与 AINDEXINDUSTRIESCITICS 视图。
采集前与 wind_db 的列清单对一次，不一致就停。
"""

from __future__ import annotations

# 顺序：先镜像 AINDEXDESCRIPTION（视图的源），再 ZL。与 0020 的 CREATE 顺序一致。
INDEX_DESCRIPTION_WIND_SYNC: tuple[str, ...] = (
    "AINDEXDESCRIPTION",
    "AINDEXDESCRIPTIONZL",
)

_INDEX_DESCRIPTION_COLUMNS: tuple[str, ...] = (
    "OBJECT_ID",
    "S_INFO_WINDCODE",
    "S_INFO_CODE",
    "S_INFO_NAME",
    "S_INFO_COMPNAME",
    "S_INFO_EXCHMARKET",
    "S_INFO_INDEX_BASEPER",
    "S_INFO_INDEX_BASEPT",
    "S_INFO_LISTDATE",
    "S_INFO_INDEX_WEIGHTSRULE",
    "S_INFO_PUBLISHER",
    "S_INFO_INDEXCODE",
    "S_INFO_INDEXSTYLE",
    "INDEX_INTRO",
    "WEIGHT_TYPE",
    "EXPIRE_DATE",
    "INCOME_PROCESSING_METHOD",
    "CHANGE_HISTORY",
    "S_INFO_PINYIN",
    "WEIGHT_TYPE_NAME",
    "S_INFO_INDEXTYPE",
    "OPDATE",
    "OPMODE",
    "gsCTime",
    "gsUTime",
    "mopdate",
)

AINDEXDESCRIPTION_COLUMNS: tuple[str, ...] = _INDEX_DESCRIPTION_COLUMNS
AINDEXDESCRIPTIONZL_COLUMNS: tuple[str, ...] = _INDEX_DESCRIPTION_COLUMNS
