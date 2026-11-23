-- 指数时间序列读取（IndexReturnRepository、IndexValuationRepository）按
-- WHERE "TRADE_DT" BETWEEN %s AND %s AND "S_INFO_WINDCODE" = ANY(%s) 取少数几个指数的长区间。
-- 两表各 2,000 万行以上，只有 OBJECT_ID 主键，一次查询全表扫描约 14 秒。
-- 用 (S_INFO_WINDCODE, TRADE_DT) 复合索引而不是 0024 的单列 TRADE_DT：这里是按代码取长序列，
-- 单列日期索引在长区间上帮不上忙。
CREATE INDEX "AINDEXEODPRICES_WINDCODE_TRADE_DT_idx" ON src_wind."AINDEXEODPRICES" ("S_INFO_WINDCODE", "TRADE_DT");
CREATE INDEX "AINDEXVALUATION_WINDCODE_TRADE_DT_idx" ON src_wind."AINDEXVALUATION" ("S_INFO_WINDCODE", "TRADE_DT");
