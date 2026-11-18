-- 按 2026-11-18 确认的分表原则，src_macro 的宏观源表改为按源端数据产品建表。
-- 开头三条 DROP 删除的旧表都为空、从未写入，删除不丢数据。
-- 旧表是按指标拆出的单指标表，不符合新原则；设计依据见
-- docs/migration/macro-source-ingest-plan.md「分表原则」。
-- 允许的 DROP 只有开头这三条，由 migrate.py 与 test_src_migrations.py 白名单放行；其余语句只能是 CREATE。
DROP TABLE src_macro."macro_jin10_usa_ism_pmi";
DROP TABLE src_macro."macro_gpr_daily";
DROP TABLE src_macro."macro_fred_observation";
CREATE TABLE src_macro."jin10_economic_calendar" (
    "indicator_id" integer NOT NULL,
    "publish_date" date NOT NULL,
    "data_id" bigint NOT NULL,
    "period_end" date,
    "time_period" text,
    "published_at" timestamptz,
    "actual_value" numeric(18, 8),
    "forecast_value" numeric(18, 8),
    "previous_value" numeric(18, 8),
    "revised_value" numeric(18, 8),
    "source" text NOT NULL,
    _batch_id bigint NOT NULL REFERENCES src_macro._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("indicator_id", "publish_date", "data_id")
);
CREATE INDEX "jin10_economic_calendar__batch_id_idx" ON src_macro."jin10_economic_calendar" (_batch_id);
CREATE TABLE src_macro."gpr_daily" (
    "series_id" varchar(32) NOT NULL,
    "observation_date" date NOT NULL,
    "file_vintage" date NOT NULL,
    "value" numeric(18, 8),
    "file_sha256" char(64) NOT NULL,
    "source" text NOT NULL,
    _batch_id bigint NOT NULL REFERENCES src_macro._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("series_id", "observation_date", "file_vintage")
);
CREATE INDEX "gpr_daily__batch_id_idx" ON src_macro."gpr_daily" (_batch_id);
CREATE TABLE src_macro."fred_observation_vintage" (
    "series_id" varchar(32) NOT NULL,
    "observation_date" date NOT NULL,
    "realtime_start" date NOT NULL,
    "realtime_end" date NOT NULL,
    "value" numeric(18, 8),
    "source" text NOT NULL,
    _batch_id bigint NOT NULL REFERENCES src_macro._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("series_id", "observation_date", "realtime_start")
);
CREATE INDEX "fred_observation_vintage__batch_id_idx" ON src_macro."fred_observation_vintage" (_batch_id);
