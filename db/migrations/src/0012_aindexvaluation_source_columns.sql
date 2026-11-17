-- AINDEXVALUATION 仍为空。0003 建表时多带了 22 个不属于源表的列：
-- INDEXNAME、INDEXNAME_ENG、S_CON_WINDCODE、EXCHANGE、FREE_SHR_RATIO、
-- SHR_CALCULATION、WEIGHTFACTOR、CLOSEVALUE、OPEN_ADJUSTED、TOT_MV、
-- MV_CALCULATION、WEIGHT、CRNCY_CODE 以及 S_DQ_* 行情列。这些列属于权重表
-- 与成员表，源库 dbo.AINDEXVALUATION 只有估值字段。
-- 表仍为空才允许删掉重建；类型沿用 0003，只保留源端有的 39 列。

DROP TABLE src_wind."AINDEXVALUATION";

CREATE TABLE src_wind."AINDEXVALUATION" (
    "OBJECT_ID" varchar(100) NOT NULL,
    "S_INFO_WINDCODE" varchar(40),
    "TRADE_DT" varchar(8),
    "CON_NUM" numeric(20, 4),
    "PE_LYR" numeric(20, 4),
    "PE_TTM" numeric(20, 4),
    "PB_LF" numeric(20, 4),
    "PCF_LYR" numeric(20, 4),
    "PCF_TTM" numeric(20, 4),
    "PS_LYR" numeric(20, 4),
    "PS_TTM" numeric(20, 4),
    "MV_TOTAL" numeric(24, 4),
    "MV_FLOAT" numeric(24, 4),
    "DIVIDEND_YIELD" numeric(20, 4),
    "PEG_HIS" numeric(20, 4),
    "TOT_SHR" numeric(24, 4),
    "TOT_SHR_FLOAT" numeric(24, 4),
    "TOT_SHR_FREE" numeric(24, 4),
    "TURNOVER" numeric(20, 4),
    "TURNOVER_FREE" numeric(20, 4),
    "EST_NET_PROFIT_Y1" numeric(20, 4),
    "EST_NET_PROFIT_Y2" numeric(20, 4),
    "EST_BUS_INC_Y1" numeric(20, 4),
    "EST_BUS_INC_Y2" numeric(20, 4),
    "EST_EPS_Y1" numeric(20, 4),
    "EST_EPS_Y2" numeric(20, 4),
    "EST_YOYPROFIT_Y1" numeric(20, 4),
    "EST_YOYPROFIT_Y2" numeric(20, 4),
    "EST_YOYGR_Y1" numeric(20, 4),
    "EST_YOYGR_Y2" numeric(20, 4),
    "EST_PE_Y1" numeric(20, 4),
    "EST_PE_Y2" numeric(20, 4),
    "EST_PEG_Y1" numeric(20, 4),
    "EST_PEG_Y2" numeric(20, 4),
    "OPDATE" timestamp,
    "OPMODE" varchar(1),
    "mopdate" timestamp,
    "gsUTime" timestamp,
    "gsCTime" timestamp,
    _batch_id bigint NOT NULL REFERENCES src_wind._batch (_batch_id),
    _ingested_at timestamptz NOT NULL,
    _row_hash char(64) NOT NULL,
    PRIMARY KEY ("OBJECT_ID")
);
