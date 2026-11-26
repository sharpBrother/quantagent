-- 朝阳永续分页按 (tmstamp, id) 顺序推进。没有这个复合索引，每页查询会随表变大变慢。
-- 只建索引，不改表结构。P2 的表本次不同步，不建。

CREATE INDEX "con_forecast_stk__tmstamp_id_idx" ON src_suntime."con_forecast_stk" ("tmstamp", "id");
CREATE INDEX "con_forecast_roll_stk__tmstamp_id_idx" ON src_suntime."con_forecast_roll_stk" ("tmstamp", "id");
CREATE INDEX "rpt_earnings_adjust__tmstamp_id_idx" ON src_suntime."rpt_earnings_adjust" ("tmstamp", "id");
CREATE INDEX "con_forecast_idx__tmstamp_id_idx" ON src_suntime."con_forecast_idx" ("tmstamp", "id");
CREATE INDEX "con_forecast_roll_idx__tmstamp_id_idx" ON src_suntime."con_forecast_roll_idx" ("tmstamp", "id");
