-- Wind 中信一级行业成分 AINDEXMEMBERSCITICSZL，全表镜像。
-- 负责人 2026-11-22 裁定：中信一级行业成员改用本表（旧仓 core/market_data_service.py:294-313，AR-0038 的 canonical L1）。
-- 旧表 AINDEXMEMBERSCITICS（0003）继续采集，只做对账，0020 的视图 AINDEXINDUSTRIESCITICS 仍依赖它。
-- 列与 0003 的 AINDEXMEMBERSCITICS2 一致：同样的成分区间字段，同样保留 gsUTime、gsCTime、mopdate 三个源端系统列。
-- CUR_SIGN 在 PG 用 integer，与 AINDEXMEMBERSCITICS2 一致；源端 numeric(1,0)，取值相等。
-- 主键 OBJECT_ID，只建 _batch_id 索引。成分查询按 S_INFO_WINDCODE 过滤，表规模与 CITICS2 相近。
CREATE TABLE src_wind."AINDEXMEMBERSCITICSZL" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "S_CON_WINDCODE" varchar(40),
    "S_CON_INDATE" varchar(8),
    "S_CON_OUTDATE" varchar(8),
    "CUR_SIGN" integer,
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
CREATE INDEX "AINDEXMEMBERSCITICSZL__batch_id_idx" ON src_wind."AINDEXMEMBERSCITICSZL" (_batch_id);
