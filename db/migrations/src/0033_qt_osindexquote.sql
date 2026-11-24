-- QT_OSIndexQuote 提前接入（2026-11-24 负责人同意，见 jydb-ingest-plan.md）。
-- 0005 建的表没有主键；表为空，按 0019 先例删表重建并补 PK 与分页/读取索引。
-- 只允许删表后紧跟同名 CREATE，已在 migrate.py 的 _REBUILD_PAIRS 登记。

DROP TABLE src_jydb."QT_OSIndexQuote";
CREATE TABLE src_jydb."QT_OSIndexQuote" (
    "ID" bigint NOT NULL,
    "IndexCode" integer NOT NULL,
    "TradingDay" timestamp NOT NULL,
    "RevealIndices" varchar(200),
    "RevealInstiCode" integer,
    "TransCurrency" integer,
    "PrevClosePrice" numeric(19, 4),
    "OpenPrice" numeric(19, 4),
    "HighPrice" numeric(19, 4),
    "LowPrice" numeric(19, 4),
    "ClosePrice" numeric(19, 4),
    "TurnoverVolume" numeric(19, 6),
    "TurnoverValue" numeric(19, 6),
    "ChangeOF" numeric(19, 4),
    "ChangePCT" numeric(19, 6),
    "UpdateTime" timestamp NOT NULL,
    "JSID" bigint NOT NULL,
    "InsertTime" timestamp,
    _batch_id bigint NOT NULL REFERENCES src_jydb._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("ID")
);

CREATE INDEX "QT_OSIndexQuote__batch_id_idx" ON src_jydb."QT_OSIndexQuote" (_batch_id);
CREATE INDEX "QT_OSIndexQuote__jsid_id_idx" ON src_jydb."QT_OSIndexQuote" ("JSID", "ID");
CREATE INDEX "QT_OSIndexQuote__IndexCode_TradingDay_idx" ON src_jydb."QT_OSIndexQuote" ("IndexCode", "TradingDay");

COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."ID" IS '聚源源表主键';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."IndexCode" IS '境外/香港指数内部代码';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."TradingDay" IS '交易日；T 日数据 T+1 可见';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."RevealIndices" IS '指数揭示名称';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."RevealInstiCode" IS '指数发布机构代码';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."TransCurrency" IS '交易币种代码';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."PrevClosePrice" IS '前收盘价';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."OpenPrice" IS '开盘价';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."HighPrice" IS '最高价';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."LowPrice" IS '最低价';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."ClosePrice" IS '收盘价';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."TurnoverVolume" IS '成交量';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."TurnoverValue" IS '成交额';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."ChangeOF" IS '涨跌额';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."ChangePCT" IS '涨跌幅';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."UpdateTime" IS '源端更新时间；系统列，不参与业务修订判断';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."JSID" IS '源端同步序列；分页游标组成部分';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."InsertTime" IS '源端插入时间；系统列，不参与业务修订判断';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."_batch_id" IS '采集批次';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."_ingested_at" IS '本系统采集时间，不是 PIT 依据';
COMMENT ON COLUMN src_jydb."QT_OSIndexQuote"."_row_hash" IS '主键与业务列的内容指纹';
