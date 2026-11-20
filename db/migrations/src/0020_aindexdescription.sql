-- Wind 指数基本资料两张源表：AINDEXDESCRIPTION 与 AINDEXDESCRIPTIONZL，列完全相同，各约 12 万行，主键 OBJECT_ID。
-- 负责人 2026-11-19 裁定：旧仓 data/wind_to_sql_2.py:630-637 从 AINDEXDESCRIPTION 按中信一二三级成分
-- 筛出 AINDEXINDUSTRIESCITICS 这张表。新仓改为完整镜像源表，再用视图做同样的筛选。
-- 视图只做筛选、不存数据，下游仍按原名 src_wind."AINDEXINDUSTRIESCITICS" 读取。
-- AINDEXDESCRIPTIONZL 只镜像，不参与视图。
-- 0003 建的 AINDEXINDUSTRIESCITICS 是从未写入的空物理表。本迁移先删表，再在同一文件里建同名视图。
-- migrate.py 的 _DROP_TO_VIEW_PAIRS 只放行这一处：每条 DROP 后必须紧跟同名 CREATE VIEW。
-- 视图列与 0003 旧物理表的 26 个源列名称、顺序、类型一致，没有缺列。视图没有存储，不建 _batch_id 索引。
-- 两张镜像表各建 _batch_id 索引，并建 S_INFO_WINDCODE 索引，视图按它过滤。

CREATE TABLE src_wind."AINDEXDESCRIPTION" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "S_INFO_CODE" varchar(40),
    "S_INFO_NAME" varchar(90),
    "S_INFO_COMPNAME" varchar(100),
    "S_INFO_EXCHMARKET" varchar(40),
    "S_INFO_INDEX_BASEPER" varchar(8),
    "S_INFO_INDEX_BASEPT" numeric(20, 4),
    "S_INFO_LISTDATE" varchar(8),
    "S_INFO_INDEX_WEIGHTSRULE" varchar(10),
    "S_INFO_PUBLISHER" varchar(100),
    "S_INFO_INDEXCODE" numeric(9, 0),
    "S_INFO_INDEXSTYLE" varchar(40),
    "INDEX_INTRO" text,
    "WEIGHT_TYPE" numeric(9, 0),
    "EXPIRE_DATE" varchar(8),
    "INCOME_PROCESSING_METHOD" varchar(20),
    "CHANGE_HISTORY" varchar(100),
    "S_INFO_PINYIN" varchar(40),
    "WEIGHT_TYPE_NAME" varchar(100),
    "S_INFO_INDEXTYPE" varchar(40),
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

CREATE INDEX "AINDEXDESCRIPTION__batch_id_idx" ON src_wind."AINDEXDESCRIPTION" (_batch_id);

CREATE INDEX "AINDEXDESCRIPTION__S_INFO_WINDCODE_idx" ON src_wind."AINDEXDESCRIPTION" ("S_INFO_WINDCODE");

CREATE TABLE src_wind."AINDEXDESCRIPTIONZL" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "S_INFO_CODE" varchar(40),
    "S_INFO_NAME" varchar(90),
    "S_INFO_COMPNAME" varchar(100),
    "S_INFO_EXCHMARKET" varchar(40),
    "S_INFO_INDEX_BASEPER" varchar(8),
    "S_INFO_INDEX_BASEPT" numeric(20, 4),
    "S_INFO_LISTDATE" varchar(8),
    "S_INFO_INDEX_WEIGHTSRULE" varchar(10),
    "S_INFO_PUBLISHER" varchar(100),
    "S_INFO_INDEXCODE" numeric(9, 0),
    "S_INFO_INDEXSTYLE" varchar(40),
    "INDEX_INTRO" text,
    "WEIGHT_TYPE" numeric(9, 0),
    "EXPIRE_DATE" varchar(8),
    "INCOME_PROCESSING_METHOD" varchar(20),
    "CHANGE_HISTORY" varchar(100),
    "S_INFO_PINYIN" varchar(40),
    "WEIGHT_TYPE_NAME" varchar(100),
    "S_INFO_INDEXTYPE" varchar(40),
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

CREATE INDEX "AINDEXDESCRIPTIONZL__batch_id_idx" ON src_wind."AINDEXDESCRIPTIONZL" (_batch_id);

CREATE INDEX "AINDEXDESCRIPTIONZL__S_INFO_WINDCODE_idx" ON src_wind."AINDEXDESCRIPTIONZL" ("S_INFO_WINDCODE");

DROP TABLE src_wind."AINDEXINDUSTRIESCITICS";

CREATE VIEW src_wind."AINDEXINDUSTRIESCITICS" AS
SELECT
    d."OBJECT_ID",
    d."S_INFO_WINDCODE",
    d."S_INFO_CODE",
    d."S_INFO_NAME",
    d."S_INFO_COMPNAME",
    d."S_INFO_EXCHMARKET",
    d."S_INFO_INDEX_BASEPER",
    d."S_INFO_INDEX_BASEPT",
    d."S_INFO_LISTDATE",
    d."S_INFO_INDEX_WEIGHTSRULE",
    d."S_INFO_PUBLISHER",
    d."S_INFO_INDEXCODE",
    d."S_INFO_INDEXSTYLE",
    d."INDEX_INTRO",
    d."WEIGHT_TYPE",
    d."EXPIRE_DATE",
    d."INCOME_PROCESSING_METHOD",
    d."CHANGE_HISTORY",
    d."S_INFO_PINYIN",
    d."WEIGHT_TYPE_NAME",
    d."S_INFO_INDEXTYPE",
    d."OPDATE",
    d."OPMODE",
    d."gsCTime",
    d."gsUTime",
    d."mopdate"
FROM src_wind."AINDEXDESCRIPTION" d
WHERE d."S_INFO_WINDCODE" IN (
    SELECT "S_INFO_WINDCODE" FROM src_wind."AINDEXMEMBERSCITICS"
    UNION
    SELECT "S_INFO_WINDCODE" FROM src_wind."AINDEXMEMBERSCITICS2"
    UNION
    SELECT "S_INFO_WINDCODE" FROM src_wind."AINDEXMEMBERSCITICS3"
);
