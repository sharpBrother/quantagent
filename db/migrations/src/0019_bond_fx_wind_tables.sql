-- 0003 建的六张债券曲线、债券回购与外汇表和 wx2 源表不一致，本迁移删表重建。
-- 源表以 OBJECT_ID 为主键且 NOT NULL（已核对无重复、无空值），0003 对这几张表：
--   CBONDCURVECSI、CBONDREPOANDIBLEODPRICES、CBONDPRICESREPO、CBONDREPO、FXEODPRICES
--     漏了 PRIMARY KEY，OBJECT_ID 也允许为空；
--   CBONDCURVECNBD 有主键，但多了源端不存在的 GSUPDTIME（wind_db 全库没有该列）。
-- 列顺序与 0003 相同，只做上述两处改动：OBJECT_ID 改为 NOT NULL 并加主键，CBONDCURVECNBD 去掉 GSUPDTIME。
-- 六张表本机均为 0 行。迁移前须确认 0 行；migrate 的 _refuse_nonempty_drop 在非空时也会拒绝执行。
-- 删表会连带删掉 0011 建的 _batch_id 索引，所以每张表重建后补建同名索引，命名同 0017。
-- 每条 DROP 后紧跟同名 CREATE，由 migrate.py 的 _REBUILD_PAIRS 白名单约束，不放宽其他迁移。

DROP TABLE src_wind."CBONDCURVECNBD";

CREATE TABLE src_wind."CBONDCURVECNBD" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "TRADE_DT" varchar(8),
    "B_ANAL_CURVENUMBER" bigint,
    "B_ANAL_CURVENAME" varchar(200),
    "B_ANAL_CURVETYPE" varchar(80),
    "B_ANAL_CURVETERM" numeric(20, 4),
    "B_ANAL_YIELD" numeric(20, 4),
    "B_ANAL_BASE_YIELD" numeric(20, 4),
    "B_ANAL_YIELD_TOTAL" numeric(20, 4),
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

CREATE INDEX "CBONDCURVECNBD__batch_id_idx" ON src_wind."CBONDCURVECNBD" (_batch_id);

DROP TABLE src_wind."CBONDCURVECSI";

CREATE TABLE src_wind."CBONDCURVECSI" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "TRADE_DT" varchar(8),
    "B_ANAL_CURVENUMBER" varchar(5),
    "B_ANAL_CURVENAME" varchar(200),
    "B_ANAL_CURVETYPE" varchar(20),
    "B_ANAL_CURVETERM" numeric(20, 4),
    "B_ANAL_YIELD" numeric(20, 4),
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

CREATE INDEX "CBONDCURVECSI__batch_id_idx" ON src_wind."CBONDCURVECSI" (_batch_id);

DROP TABLE src_wind."CBONDREPOANDIBLEODPRICES";

CREATE TABLE src_wind."CBONDREPOANDIBLEODPRICES" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "TRADE_DT" varchar(8),
    "S_DQ_OPEN" numeric(20, 4),
    "S_DQ_HIGH" numeric(20, 4),
    "S_DQ_LOW" numeric(20, 4),
    "S_DQ_CLOSE" numeric(20, 4),
    "B_DQ_WAVERAGERATE" numeric(20, 8),
    "S_DQ_VOLUME" numeric(20, 4),
    "S_DQ_AMOUNT" numeric(20, 4),
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

CREATE INDEX "CBONDREPOANDIBLEODPRICES__batch_id_idx" ON src_wind."CBONDREPOANDIBLEODPRICES" (_batch_id);

DROP TABLE src_wind."CBONDPRICESREPO";

CREATE TABLE src_wind."CBONDPRICESREPO" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "TRADE_DT" varchar(8),
    "S_DQ_OPEN" numeric(20, 4),
    "S_DQ_HIGH" numeric(20, 4),
    "S_DQ_LOW" numeric(20, 4),
    "S_DQ_CLOSE" numeric(20, 4),
    "S_DQ_AVGPRICE" numeric(20, 4),
    "S_DQ_VOLUME" numeric(20, 4),
    "S_DQ_AMOUNT" numeric(20, 4),
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

CREATE INDEX "CBONDPRICESREPO__batch_id_idx" ON src_wind."CBONDPRICESREPO" (_batch_id);

DROP TABLE src_wind."CBONDREPO";

CREATE TABLE src_wind."CBONDREPO" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "TRADE_DT" varchar(8),
    "B_INFO_TERM" numeric(20, 4),
    "B_TENDER_INTERESTRATE" numeric(20, 4),
    "B_TENDER_AMOUNT" numeric(20, 4),
    "B_TENDER_METHOD" numeric(9, 0),
    "B_INFO_REPO_TYPE" numeric(9, 0),
    "B_INFO_TERM_WORDS" varchar(40),
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

CREATE INDEX "CBONDREPO__batch_id_idx" ON src_wind."CBONDREPO" (_batch_id);

DROP TABLE src_wind."FXEODPRICES";

CREATE TABLE src_wind."FXEODPRICES" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "TRADE_DT" varchar(8),
    "S_INFO_WINDCODE" varchar(40),
    "S_DQ_OPEN" numeric(20, 4),
    "S_DQ_HIGH" numeric(20, 4),
    "S_DQ_LOW" numeric(20, 4),
    "S_DQ_CLOSE" numeric(20, 4),
    "WINDCODE" varchar(40),
    "S_DQ_BUY" numeric(20, 8),
    "S_DQ_SELL" numeric(20, 8),
    "OPDATE" timestamp,
    "OPMODE" varchar(1),
    "mopdate" timestamp,
    "gsCTime" timestamp,
    "gsUTime" timestamp,
    "SEC_ID" varchar(10),
    _batch_id bigint NOT NULL REFERENCES src_wind._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("OBJECT_ID")
);

CREATE INDEX "FXEODPRICES__batch_id_idx" ON src_wind."FXEODPRICES" (_batch_id);
