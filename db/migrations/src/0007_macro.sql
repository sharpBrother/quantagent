-- 第一批 macro 源镜像。字段名/类型/大小写与源端一致。
-- 系统列只有 _batch_id / _ingested_at / _row_hash。
-- 本文件只含 CREATE，禁止 DROP / ALTER / DML。

CREATE TABLE src_macro."macro_jin10_usa_ism_pmi" (
    "publish_date" date NOT NULL,
    "actual_value" numeric(18, 8),
    "forecast_value" numeric(18, 8),
    "previous_value" numeric(18, 8),
    "source" text NOT NULL,
    "record_hash" char(64) NOT NULL,
    "ingested_at" timestamp NOT NULL,
    _batch_id bigint NOT NULL REFERENCES src_macro._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("record_hash")
);

CREATE TABLE src_macro."macro_wgc_gold_demand" (
    "period_end" varchar(8) NOT NULL,
    "geography" text NOT NULL,
    "category" text NOT NULL,
    "value_tonnes" numeric(18, 8) NOT NULL,
    "publish_date" varchar(8) NOT NULL,
    "source" text NOT NULL,
    "file_sha256" char(64) NOT NULL,
    "record_hash" char(64) NOT NULL,
    "ingested_at" timestamp NOT NULL,
    _batch_id bigint NOT NULL REFERENCES src_macro._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("record_hash")
);

CREATE TABLE src_macro."macro_fred_observation" (
    "series_id" varchar(32) NOT NULL,
    "observation_date" date NOT NULL,
    "value" numeric(18, 8),
    "source" text NOT NULL,
    "ingested_at" timestamp NOT NULL,
    _batch_id bigint NOT NULL REFERENCES src_macro._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("series_id", "observation_date")
);

CREATE TABLE src_macro."macro_gpr_daily" (
    "observation_date" varchar(8) NOT NULL,
    "gprd_act" numeric(18, 8) NOT NULL,
    "source" text NOT NULL,
    "file_sha256" char(64) NOT NULL,
    "record_hash" char(64) NOT NULL,
    "ingested_at" timestamp NOT NULL,
    _batch_id bigint NOT NULL REFERENCES src_macro._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("record_hash")
);
