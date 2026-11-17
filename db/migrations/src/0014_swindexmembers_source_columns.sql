-- SWINDEXMEMBERS 仍为空。0003 建表时多带了 ENTRY_DT、REMOVE_DT 两列，
-- 源库 dbo.SWINDEXMEMBERS 用 S_CON_INDATE/S_CON_OUTDATE 记成分区间，没有这两列。
-- 表仍为空才允许删掉重建；类型沿用 0003。

DROP TABLE src_wind."SWINDEXMEMBERS";

CREATE TABLE src_wind."SWINDEXMEMBERS" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "S_CON_WINDCODE" varchar(40),
    "S_CON_INDATE" varchar(8),
    "S_CON_OUTDATE" varchar(8),
    "CUR_SIGN" numeric(1, 0),
    "OPDATE" timestamp,
    "OPMODE" varchar(1),
    "gsUTime" timestamp,
    "mopdate" timestamp,
    "gsCTime" timestamp,
    _batch_id bigint NOT NULL REFERENCES src_wind._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("OBJECT_ID")
);
