-- 聚源行业指标目录 C_IN_IndicatorMain。列与源端 INFORMATION_SCHEMA 一致（2026-11-23 核对）。
-- 目录表不配 visibility；时间序列在 C_IN_IndicatorDataV。

CREATE TABLE src_jydb."C_IN_IndicatorMain" (
    "ID" bigint NOT NULL,
    "IndicatorCode" integer,
    "IndicatorName" varchar(300),
    "InfoSourceCode" integer,
    "InfoSource" varchar(50),
    "PowerNumber" integer,
    "IndiState" smallint,
    "BeginDate" timestamp,
    "EndDate" timestamp,
    "UnitCode" integer,
    "UnitCodeReport" integer,
    "DisclosureFrequency" integer,
    "IndiRemark" varchar(1000),
    "UpdateTime" timestamp,
    "JSID" bigint,
    "InsertTime" timestamp,
    _batch_id bigint NOT NULL REFERENCES src_jydb._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("ID")
);

CREATE INDEX "C_IN_IndicatorMain__batch_id_idx" ON src_jydb."C_IN_IndicatorMain" (_batch_id);
