-- 聚源分页按 (JSID, ID) 顺序推进。没有这个复合索引，每页查询会随表变大变慢。
-- 只建索引，不改表结构。C_IN_IndicatorMain 与其余四张 P0/P1 表一并覆盖。

CREATE INDEX "C_ED_MacroIndicatorData__jsid_id_idx" ON src_jydb."C_ED_MacroIndicatorData" ("JSID", "ID");
CREATE INDEX "C_ED_IndicatorMain__jsid_id_idx" ON src_jydb."C_ED_IndicatorMain" ("JSID", "ID");
CREATE INDEX "ED_MoneySupply__jsid_id_idx" ON src_jydb."ED_MoneySupply" ("JSID", "ID");
CREATE INDEX "C_IN_IndicatorDataV__jsid_id_idx" ON src_jydb."C_IN_IndicatorDataV" ("JSID", "ID");
CREATE INDEX "C_IN_IndicatorMain__jsid_id_idx" ON src_jydb."C_IN_IndicatorMain" ("JSID", "ID");
