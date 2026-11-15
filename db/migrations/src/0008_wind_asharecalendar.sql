-- 保留 Wind 原生字段，开闭市推导留给标准化层。
CREATE TABLE src_wind."ASHARECALENDAR" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "TRADE_DAYS" varchar(8),
    "S_INFO_EXCHMARKET" varchar(40),
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
