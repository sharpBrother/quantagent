-- AINDEXMEMBERS 仍为空。0003 建表时多带了 22 个不属于源表的列：
-- TRADE_DT、INDEXNAME、EXCHANGE、TOT_SHR、WEIGHT、I_WEIGHT*、S_IN_INDEX 等，
-- 它们属于权重表。源库 dbo.AINDEXMEMBERS 只有成分关系字段。
-- 表仍为空才允许删掉重建；类型沿用 0003，只保留源端有的 11 列。

DROP TABLE src_wind."AINDEXMEMBERS";

CREATE TABLE src_wind."AINDEXMEMBERS" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "S_CON_WINDCODE" varchar(40),
    "S_CON_INDATE" varchar(8),
    "S_CON_OUTDATE" varchar(8),
    "CUR_SIGN" numeric(1, 0),
    "OPDATE" timestamp,
    "OPMODE" varchar(1),
    "mopdate" timestamp,
    "gsCTime" timestamp,
    "gsUTime" timestamp,
    _batch_id bigint NOT NULL REFERENCES src_wind._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("OBJECT_ID")
);
