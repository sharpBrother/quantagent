-- 资金流读取（MoneyFlowRepository）按 WHERE "S_INFO_WINDCODE" = ANY(%s) AND "TRADE_DT" BETWEEN %s AND %s 取一批代码的
-- 连续区间，每次约 5,000 只股票、约 120 个自然日。表 1,330 万行，除 OBJECT_ID 主键与 _batch_id 索引外没有读取索引。
-- 用 (S_INFO_WINDCODE, TRADE_DT) 复合索引而不是单列 TRADE_DT：代码列表先定位到少数几只股票，
-- 再在每只股票内按日期范围做索引扫描，与 0026 对指数序列的取法相同。
CREATE INDEX "ASHAREMONEYFLOW_WINDCODE_TRADE_DT_idx" ON src_wind."ASHAREMONEYFLOW" ("S_INFO_WINDCODE", "TRADE_DT");
