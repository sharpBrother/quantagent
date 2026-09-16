-- 第一批 tushare 源镜像。字段名/类型/大小写与源端一致。
-- 系统列只有 _batch_id / _ingested_at / _row_hash。
-- 本文件只含 CREATE，禁止 DROP / ALTER / DML。

CREATE TABLE src_tushare."trade_cal" (
    "exchange" varchar(10) NOT NULL,
    "cal_date" varchar(8) NOT NULL,
    "is_open" integer,
    "pretrade_date" varchar(8),
    _batch_id bigint NOT NULL REFERENCES src_tushare._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("exchange", "cal_date")
);

CREATE TABLE src_tushare."fund_share" (
    "ts_code" varchar(10),
    "trade_date" varchar(8),
    "fd_share" double precision,
    "fund_type" varchar(5),
    "market" varchar(5),
    "insert_time" timestamp,
    _batch_id bigint NOT NULL REFERENCES src_tushare._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL
);

CREATE TABLE src_tushare."tushare_ths_industry_mapping_citics" (
    "ths_industry_code" varchar(20) NOT NULL,
    "ths_industry_name" varchar(30),
    "citics_ind_code" varchar(20),
    "citics_ind_name" varchar(30),
    _batch_id bigint NOT NULL REFERENCES src_tushare._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("ths_industry_code")
);
