-- 0003 已应用，不能改那个文件。当时这张空表多建了源端没有的 19 个简介列。
-- 表仍为空才允许删掉重建。采集列与 wind_db.dbo.AINDEXEODPRICES 一致，
-- 另外只保留 _batch_id、_ingested_at、_row_hash。

DROP TABLE src_wind."AINDEXEODPRICES";

CREATE TABLE src_wind."AINDEXEODPRICES" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "TRADE_DT" varchar(8),
    "CRNCY_CODE" varchar(10),
    "S_DQ_PRECLOSE" numeric(20, 4),
    "S_DQ_OPEN" numeric(20, 4),
    "S_DQ_HIGH" numeric(20, 4),
    "S_DQ_LOW" numeric(20, 4),
    "S_DQ_CLOSE" numeric(20, 4),
    "S_DQ_CHANGE" numeric(20, 4),
    "S_DQ_PCTCHANGE" numeric(20, 4),
    "S_DQ_VOLUME" numeric(20, 4),
    "S_DQ_AMOUNT" numeric(20, 4),
    "SEC_ID" varchar(10),
    "OPDATE" timestamp,
    "OPMODE" varchar(1),
    "gsCTime" timestamp,
    "gsUTime" timestamp,
    "mopdate" timestamp,
    _batch_id bigint NOT NULL REFERENCES src_wind._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("OBJECT_ID")
);
