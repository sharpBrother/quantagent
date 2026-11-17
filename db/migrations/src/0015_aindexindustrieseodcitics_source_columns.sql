-- AINDEXINDUSTRIESEODCITICS 仍为空。0003 建表时多带了 19 个指数简介列
-- （S_INFO_NAME、INDEX_INTRO、WEIGHT_TYPE 等），它们属于 AINDEXDESCRIPTION。
-- 源库 dbo.AINDEXINDUSTRIESEODCITICS 只有 S_DQ_* 行情字段。
-- 表仍为空才允许删掉重建；类型沿用 0003，只保留源端有的 18 列。

DROP TABLE src_wind."AINDEXINDUSTRIESEODCITICS";

CREATE TABLE src_wind."AINDEXINDUSTRIESEODCITICS" (
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
    "OPDATE" timestamp,
    "OPMODE" varchar(1),
    "gsUTime" timestamp,
    "gsCTime" timestamp,
    "mopdate" timestamp,
    _batch_id bigint NOT NULL REFERENCES src_wind._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("OBJECT_ID")
);
