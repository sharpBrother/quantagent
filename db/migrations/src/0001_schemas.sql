-- 研究数据面 schema。按源隔离，便于按面授权。
-- 本文件只含 CREATE，禁止 DROP / ALTER / DML。

CREATE SCHEMA src_wind;

CREATE SCHEMA src_tushare;

CREATE SCHEMA src_jydb;

CREATE SCHEMA src_suntime;

CREATE SCHEMA src_macro;
