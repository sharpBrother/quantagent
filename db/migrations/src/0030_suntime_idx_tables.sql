-- 朝阳永续指数一致预期两张 P0 表。列名、类型、大小写与源端 suntime_db 一致（2026-11-24 核对）。
-- 系统列只有 _batch_id / _ingested_at / _row_hash。本文件只含 CREATE，禁止 DROP / ALTER / DML。

CREATE TABLE src_suntime."con_forecast_idx" (
    "id" bigint NOT NULL,
    "index_code" varchar(20),
    "index_name" varchar(100),
    "con_date" date,
    "con_year" integer,
    "con_or" double precision,
    "con_np" double precision,
    "con_eps" double precision,
    "con_na" double precision,
    "con_pb" double precision,
    "con_ps" double precision,
    "con_pe" double precision,
    "con_peg" double precision,
    "con_roe" double precision,
    "con_or_yoy" double precision,
    "con_np_yoy" double precision,
    "con_npcgrate_2y" double precision,
    "con_pei" double precision,
    "entrytime" timestamp,
    "updatetime" timestamp,
    "tmstamp" bigint,
    _batch_id bigint NOT NULL REFERENCES src_suntime._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("id")
);

CREATE TABLE src_suntime."con_forecast_roll_idx" (
    "id" bigint NOT NULL,
    "index_code" varchar(20),
    "index_name" varchar(100),
    "con_date" date,
    "con_or_roll" double precision,
    "con_np_roll" double precision,
    "con_eps_roll" double precision,
    "con_na_roll" double precision,
    "con_pb_roll" double precision,
    "con_ps_roll" double precision,
    "con_pe_roll" double precision,
    "con_peg_roll" double precision,
    "con_roe_roll" double precision,
    "con_npcgrate_2y_roll" double precision,
    "con_or_yoy_roll" double precision,
    "con_np_yoy_roll" double precision,
    "entrytime" timestamp,
    "updatetime" timestamp,
    "tmstamp" bigint,
    _batch_id bigint NOT NULL REFERENCES src_suntime._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("id")
);

CREATE INDEX "con_forecast_idx__batch_id_idx" ON src_suntime."con_forecast_idx" (_batch_id);
CREATE INDEX "con_forecast_roll_idx__batch_id_idx" ON src_suntime."con_forecast_roll_idx" (_batch_id);
