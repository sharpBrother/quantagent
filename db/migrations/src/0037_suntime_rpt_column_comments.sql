-- 本文件由 `quantagent contracts emit-comments` 从契约 YAML 生成，勿手改。
-- 字段说明的唯一来源是 src/quantagent/contracts/schemas/pg/src.*.yaml 的 columns.<名>.description。
-- COMMENT ON 只取轻量锁，不阻塞写入。

COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."id" IS '朝阳永续源表主键';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."report_id" IS '研报 ID';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."stock_code" IS '股票代码，无交易所后缀（nap_adj_ratio 计算时按号段补 .BJ/.SH/.SZ）';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."stock_name" IS '股票名称';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."title" IS '研报标题';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."report_type" IS '研报类型';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."organ_id" IS '机构 ID；nap_adj_ratio 按 report_year 分组数它的数量';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."organ_name" IS '机构名称';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."author" IS '作者';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."report_year" IS '预测年度；nap_adj_ratio 取调整数最多的年度';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."current_create_date" IS '当前研报日期（事件时间），业务窗口过滤字段';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."previous_create_date" IS '前次研报日期';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."current_forecast_np" IS '当前预测净利润';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."previous_forecast_np" IS '前次预测净利润';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."np_adjust_rate" IS '净利润调整幅度；nap_adj_ratio 取最多年度该值的中位数';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."np_adjust_mark" IS '净利润调整标记';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."current_forecast_eps" IS '当前预测 EPS';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."previous_forecast_eps" IS '前次预测 EPS';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."eps_adjust_rate" IS 'EPS 调整幅度';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."eps_adjust_mark" IS 'EPS 调整标记';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."is_capital_different" IS '股本是否变动';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."entrytime" IS '供应商首次入库时间戳，PIT 可见截止字段，按日期比较';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."updatetime" IS '供应商最近修订时间戳';
COMMENT ON COLUMN src_suntime."rpt_earnings_adjust"."tmstamp" IS '供应商时间戳序号';
