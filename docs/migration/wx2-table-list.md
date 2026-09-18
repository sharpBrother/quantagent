---
title: 旧 SQL Server wx2 逐表处置清单
status: active
created: 2026-09-18
updated: 2026-09-18
applies_to:
  - docs/migration/wx2-disposition.md
  - docs/migration/wx2-table-list.yaml
  - db/src_tables.yaml
  - tests/contracts/test_wx2_table_list.py
supersedes: null
superseded_by: null
---

# 旧 SQL Server wx2 逐表处置清单

P2 第一个交付物。分类标准见 [wx2-disposition.md](wx2-disposition.md)。
机器可读副本：[wx2-table-list.yaml](wx2-table-list.yaml)。

## 范围与指针

- 旧仓：`pycharm_workspace` @ `7c506d51160e57385fd85217edece815268ffd55`
- 表数：**371**（数据字典 + `db/src_tables.yaml` 宏观表 + 运维表 + 现役代码出现但字典未收录的表）
- 行数：未连 wx2，全部 **未查**
- **不迁入、不写 PIT YAML。** 迁入前须负责人确认可见性规则
- 消费者 = 现役模块引用 ∪ 启用中的 `jobs.json` ∪ `data_registry`；采集写入不算消费者
- 排除：`legacy/` 等已丢弃目录、一次性 `scripts/taskNNNN`、DDL 建表脚本、`data/review/`、网站静态快照

## 汇总

| 类别 | 张数 |
|---|---:|
| 1 源镜像 | 93 |
| 2 可重算 | 67 |
| 3 遗产冻结 | 0 |
| 4 运维改造 | 26 |
| 5 无消费者 | 185 |
| 合计 | 371 |

第一批 `db/src_tables.yaml` 的 59 张全部落在类别 1，去向标注「已收录，本清单不启动迁入」。
类别 1 中第一批未收录的表只记录，不改 `src_tables.yaml`。
类别 3 本轮为 0：历史策略结果表（`strategy_result_*` 等）现役无读取，已归入类别 5。

## 逐表清单

| 表名 | 行数 | 判定类别 | 判定依据 | 去向 | 附加约束 |
|---|---|---|---|---|---|
| `barra_cne6_exposure` | 未查 | 1 源镜像 | 现役：etf_sector_rotation/etf_sector_rotation/data/etf_hq_scorer.py | barra_cne6_exposure → src_*（Barra schema 待定；第一批未收录，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `stock_etf_min_price` | 未查 | 1 源镜像 | 现役：data/ETF四象限推送.py, data/etf_real_trade_v14.py, data/宽基指数配置策略.py 等11处 | stock_etf_min_price → src_*（ETF 分钟行情 schema 待定；第一批未收录，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `Bond_BondIndexQuote` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, strategy_engine/adapters/bond_timing.py | src_jydb.Bond_BondIndexQuote（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `Bond_CBYieldCurveAll` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_jydb.Bond_CBYieldCurveAll（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `C_ED_IndicatorMain` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：macro_regime/config/indicator_registry.yaml, scripts/macro_regime_revalidation/p0_evidence_pit_qualification.py | src_jydb.C_ED_IndicatorMain（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `C_ED_MacroIndicatorData` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, scripts/macro_regime_revalidation/industrial_value_added_p2_input_freeze.py, scripts/macro_regime_revalidation/macro_family_qualification.py 等11处 | src_jydb.C_ED_MacroIndicatorData（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `C_IN_IndicatorDataV` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, scripts/macro_regime_revalidation/macro_family_qualification.py, scripts/macro_style_evaluation_contract.py 等7处 | src_jydb.C_IN_IndicatorDataV（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `CT_SystemConst` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：scripts/macro_regime_external_revenue_wiring.py | src_jydb.CT_SystemConst（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `DZ_MainOperIncome` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：scripts/macro_regime_external_revenue_wiring.py, scripts/macro_regime_walk_forward_evaluation.py, macro_regime/pools.py | src_jydb.DZ_MainOperIncome（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ED_FixedInvestment` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_jydb.ED_FixedInvestment（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `ED_MoneySupply` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：macro_regime/config/indicator_registry.yaml, macro_regime/pit.py, scripts/run_large_small_style_rotation.py 等5处 | src_jydb.ED_MoneySupply（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ED_SocialFinancing` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：scripts/macro_risk_revalidation/task0350/identity_pins.py, scripts/macro_risk_revalidation/task0350/source_catalog.py | src_jydb.ED_SocialFinancing（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `IN_ManufacturingPMI` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_jydb.IN_ManufacturingPMI（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `QT_GoldTradeMarket` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, strategy_engine/adapters/gold_timing.py | src_jydb.QT_GoldTradeMarket（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `QT_OSIndexQuote` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, scripts/run_large_small_style_rotation.py, style_rotation/large_small/contracts.py 等4处 | src_jydb.QT_OSIndexQuote（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `SecuMain` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：scripts/macro_regime_external_revenue_wiring.py | src_jydb.SecuMain（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `SecuMainAll` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, style_rotation/large_small/phase_e_final_validation.py, scripts/run_large_small_style_rotation.py | src_jydb.SecuMainAll（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `macro_eco_cal` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py | src_macro.macro_eco_cal（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `macro_fred_observation` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py | src_macro.macro_fred_observation（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `macro_gpr_daily` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py | src_macro.macro_gpr_daily（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `macro_jin10_china_cpi_yoy` | 未查 | 1 源镜像 | 现役：alpha_factory/etf/timepoint_momentum/engine.py | src_macro.macro_jin10_china_cpi_yoy（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `macro_jin10_china_ppi_yoy` | 未查 | 1 源镜像 | 现役：alpha_factory/etf/timepoint_momentum/engine.py | src_macro.macro_jin10_china_ppi_yoy（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `macro_jin10_usa_ism_pmi` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, gold_timing/contracts.py, scripts/migrate_jin10_period_end.py | src_macro.macro_jin10_usa_ism_pmi（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `macro_shibor` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：macro_regime/config/indicator_registry.yaml, scripts/run_growth_value_final_research.py, scripts/run_growth_value_style_rotation.py 等5处 | src_macro.macro_shibor（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `macro_us_treasury_yield` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：macro_regime/pit.py, scripts/macro_regime_walk_forward_evaluation.py, macro_regime/config/indicator_registry.yaml 等5处 | src_macro.macro_us_treasury_yield（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `macro_wgc_gold_demand` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py | src_macro.macro_wgc_gold_demand（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `con_forecast_citic` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_suntime.con_forecast_citic（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `con_forecast_roll_stk` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, alpha_factory/etf/gateway.py, agent_style_rotation/expectation_engine.py 等5处 | src_suntime.con_forecast_roll_stk（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `con_forecast_stk` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/consensus_fttm_wide_builder.py, agent_style_rotation/data_gateway.py, alpha_factory/etf/gateway.py 等12处 | src_suntime.con_forecast_stk（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `con_forecast_stk_ttm` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/consensus_fttm_wide_builder.py, agent_style_rotation/data_gateway.py, data/宽基指数配置策略2.py | src_suntime.con_forecast_stk_ttm（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `der_diver_stk` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/raw_loader.py, enhanced_optimizer/factors/exposure.py | src_suntime.der_diver_stk（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `der_prob_excess_stock` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：alpha_factory/data_gateway.py, alpha_factory/growth_events.py, alpha_factory/layered_universe.py | src_suntime.der_prob_excess_stock（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `rpt_earnings_adjust` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, alpha_factory/pf_nap/materialization.py, alpha_factory/pf_nap/qualification.py 等7处 | src_suntime.rpt_earnings_adjust（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `rpt_forecast_stk` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_suntime.rpt_forecast_stk（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `barra_cne6` | 未查 | 1 源镜像 | 现役：alpha_factory/data_gateway.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json, alpha_factory/refresh_performance_factor_fast_ic.py 等11处 | barra_cne6 → src_*（Barra schema 待定；第一批未收录，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `barra_cne6_factor_return` | 未查 | 1 源镜像 | 现役：enhanced_optimizer/risk_models/barra_risk_gemini.py | barra_cne6_factor_return → src_*（Barra schema 待定；第一批未收录，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `barra_cne6_specific_return` | 未查 | 1 源镜像 | 现役：enhanced_optimizer/risk_models/barra_risk_gemini.py | barra_cne6_specific_return → src_*（Barra schema 待定；第一批未收录，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `fin_income_gen` | 未查 | 1 源镜像 | 现役：factors/factor_event_2.py | src_tushare.fin_income_gen（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `fin_performance_express` | 未查 | 1 源镜像 | 现役：factors/factor_event_2.py | src_tushare.fin_performance_express（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `fin_performance_forecast` | 未查 | 1 源镜像 | 现役：factors/factor_event_2.py | src_tushare.fin_performance_forecast（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `fina_rpt_forecast` | 未查 | 1 源镜像 | 现役：factors/factor_rpt.py | src_tushare.fina_rpt_forecast（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `fina_rpt_forecast_roe` | 未查 | 1 源镜像 | 现役：data/etf_trend_strategy.py | src_tushare.fina_rpt_forecast_roe（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `fund_share` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, data/etf_real_trade_v14.py, etf_sector_rotation/etf_sector_rotation/data/minute_data.py 等5处 | src_tushare.fund_share（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `mapping_industry_etf` | 未查 | 1 源镜像 | 手维护/映射参考表，无法从 vendor 行情重算；现役：data/ETF四象限推送.py, data/etf_real_trade_v14.py, data/情绪择时推送.py 等8处 | 待定落点（src_ref / frozen / 配置），现不迁 | 非 vendor 行情，不进第一批 src_*。不定 visibility YAML，须负责人确认后再配 |
| `strategy_citics_list` | 未查 | 1 源镜像 | 手维护/映射参考表，无法从 vendor 行情重算；现役：data/宽基指数配置策略2.py | 待定落点（src_ref / frozen / 配置），现不迁 | 非 vendor 行情，不进第一批 src_*。不定 visibility YAML，须负责人确认后再配 |
| `strategy_etf_black_list` | 未查 | 1 源镜像 | 手维护/映射参考表，无法从 vendor 行情重算；现役：data/etf_real_trade_v14.py, etf_sector_rotation/etf_sector_rotation/gateways/rotation_gateway.py, etf_sector_rotation/configs/etf_rotation_v1.yaml | 待定落点（src_ref / frozen / 配置），现不迁 | 非 vendor 行情，不进第一批 src_*。不定 visibility YAML，须负责人确认后再配 |
| `strategy_etf_list` | 未查 | 1 源镜像 | 手维护/映射参考表，无法从 vendor 行情重算；现役：core/market_data_service.py, data/ETF四象限推送.py, data/etf_real_trade_v14.py 等11处 | 待定落点（src_ref / frozen / 配置），现不迁 | 非 vendor 行情，不进第一批 src_*。不定 visibility YAML，须负责人确认后再配 |
| `strategy_etf_list_2` | 未查 | 1 源镜像 | 手维护/映射参考表，无法从 vendor 行情重算；现役：alpha_factory/etf/gateway.py, alpha_factory/etf/scripts/analyze_etf_factor_tradability.py, alpha_factory/etf/timepoint_momentum/engine.py 等16处 | 待定落点（src_ref / frozen / 配置），现不迁 | 非 vendor 行情，不进第一批 src_*。不定 visibility YAML，须负责人确认后再配 |
| `trade_cal` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, alpha_factory/data_gateway.py, alpha_factory/etf/gateway.py 等91处 | src_tushare.trade_cal（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `tushare_ths_industry_mapping_citics` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：alpha_factory/all_a_canonical_scene.py, scripts/backfill_alpha_factory_pf_quarterly.py | src_tushare.tushare_ths_industry_mapping_citics（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `universe_style_rotation` | 未查 | 1 源镜像 | 手维护/映射参考表，无法从 vendor 行情重算；现役：agent_style_rotation/score_engine.py, agent_style_rotation/universe.py, core/market_data_service.py 等13处 | 待定落点（src_ref / frozen / 配置），现不迁 | 非 vendor 行情，不进第一批 src_*。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXEODPRICES` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, alpha_factory/etf/gateway.py, alpha_factory/etf/timepoint_momentum/engine.py 等43处 | src_wind.AINDEXEODPRICES（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXINDUSTRIESCITICS` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：data/etf_trend_strategy.py, data/情绪择时推送.py, scripts/macro_regime_walk_forward_evaluation.py | src_wind.AINDEXINDUSTRIESCITICS（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXINDUSTRIESEODCITICS` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, alpha_factory/etf/timepoint_momentum/engine.py, core/market_data_service.py 等9处 | src_wind.AINDEXINDUSTRIESEODCITICS（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXMEMBERS` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：alpha_factory/data_gateway.py, alpha_factory/etf/gateway.py, alpha_factory/etf/timepoint_momentum/engine.py 等34处 | src_wind.AINDEXMEMBERS（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXMEMBERSCITICS` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：alpha_factory/data_gateway.py, core/market_data_service.py, core/raw_loader.py 等9处 | src_wind.AINDEXMEMBERSCITICS（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXMEMBERSCITICS2` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, core/market_data_service.py, data/宽基指数配置策略2.py 等5处 | src_wind.AINDEXMEMBERSCITICS2（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXMEMBERSCITICS3` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, core/market_data_service.py, data/宽基指数配置策略2.py 等4处 | src_wind.AINDEXMEMBERSCITICS3（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXMEMBERSCITICSZL` | 未查 | 1 源镜像 | 现役：agent_style_rotation/data_gateway.py, alpha_factory/etf/timepoint_momentum/engine.py, core/market_data_service.py | src_wind.AINDEXMEMBERSCITICSZL（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXVALUATION` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, alpha_factory/etf/gateway.py, core/market_data_service.py 等15处 | src_wind.AINDEXVALUATION（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREBALANCESHEET` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/consensus_fttm_wide_builder.py, agent_style_rotation/data_gateway.py, enhanced_optimizer/factors/exposure.py 等5处 | src_wind.ASHAREBALANCESHEET（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHARECASHFLOW` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, agent_style_rotation/lifecycle_engine.py, enhanced_optimizer/factors/exposure.py | src_wind.ASHARECASHFLOW（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREDESCRIPTION` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/consensus_fttm_wide_builder.py, alpha_factory/all_a_canonical_scene.py, alpha_factory/data_gateway.py 等24处 | src_wind.ASHAREDESCRIPTION（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREDIVIDEND` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：data/宽基指数配置策略2.py, factors/factor_fundamental.py, scripts/audit_stock_adjusted_return_qualification.py | src_wind.ASHAREDIVIDEND（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREEODDERIVATIVEINDICATOR` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, alpha_factory/data_gateway.py, alpha_factory/etf/gateway.py 等42处 | src_wind.ASHAREEODDERIVATIVEINDICATOR（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREEODPRICES` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：alpha_factory/all_a_canonical_scene.py, alpha_factory/data_gateway.py, alpha_factory/etf/gateway.py 等56处 | src_wind.ASHAREEODPRICES（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREFINANCIALINDICATOR` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/data_gateway.py, alpha_factory/data_gateway.py, alpha_factory/refresh_performance_factor_fast_ic.py 等12处 | src_wind.ASHAREFINANCIALINDICATOR（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREINCOME` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：agent_style_rotation/consensus_fttm_wide_builder.py, agent_style_rotation/data_gateway.py, core/raw_loader.py 等8处 | src_wind.ASHAREINCOME（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREINSIDEHOLDER` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_wind.ASHAREINSIDEHOLDER（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `ASHAREMARGINTRADE` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：data/ETF四象限推送.py, factors/factor_etf_margin.py | src_wind.ASHAREMARGINTRADE（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREMARGINTRADESUM` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, data/情绪择时推送.py | src_wind.ASHAREMARGINTRADESUM（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREMJRHOLDERTRADE` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_wind.ASHAREMJRHOLDERTRADE（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `ASHAREMONEYFLOW` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, factors/daily_factor.py, factors/factor_etf.py | src_wind.ASHAREMONEYFLOW（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREPROFITEXPRESS` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_wind.ASHAREPROFITEXPRESS（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `ASHAREPROFITNOTICE` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：factors/factor_event.py | src_wind.ASHAREPROFITNOTICE（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHAREST` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：alpha_factory/data_gateway.py, core/universe_provider.py, data/宽基指数配置策略2.py 等7处 | src_wind.ASHAREST（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `ASHARETRADINGSUSPENSION` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：factors/factor_etf.py | src_wind.ASHARETRADINGSUSPENSION（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `CBONDCONVPRICE` | 未查 | 1 源镜像 | 现役：strategy/convbond_backtest.py, strategy/可转债套利.py | src_wind.CBONDCONVPRICE（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `CBONDCURVECNBD` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, data/宽基指数配置策略.py, data/宽基指数配置策略2.py 等11处 | src_wind.CBONDCURVECNBD（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `CBONDCURVECSI` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, scripts/backfill_bond_curve_csi.py, scripts/run_large_small_style_rotation.py 等5处 | src_wind.CBONDCURVECSI（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `CBONDEODPRICES` | 未查 | 1 源镜像 | 现役：strategy/convbond_backtest.py, strategy/可转债套利.py | src_wind.CBONDEODPRICES（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `CBONDPRICESREPO` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：scripts/macro_regime_revalidation/dr007_research_source_bundle.py, scripts/macro_regime_revalidation/macro_family_qualification.py, scripts/macro_regime_revalidation/pit_lineage_requalification.py 等6处 | src_wind.CBONDPRICESREPO（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `CBONDPUT` | 未查 | 1 源镜像 | 现役：strategy/convbond_backtest.py, strategy/可转债套利.py | src_wind.CBONDPUT（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `CBONDREPO` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：scripts/macro_regime_revalidation/policy_rate_event_p0.py, scripts/macro_regime_revalidation/pit_lineage_requalification.py | src_wind.CBONDREPO（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `CBONDREPOANDIBLEODPRICES` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, scripts/macro_regime_revalidation/r007_dr007_funding_stress_source_pit_qualification.py | src_wind.CBONDREPOANDIBLEODPRICES（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `CBONDTRADINGSUSPENSION` | 未查 | 1 源镜像 | 现役：strategy/convbond_backtest.py, strategy/可转债套利.py | src_wind.CBONDTRADINGSUSPENSION（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `CCBONDVALUATION` | 未查 | 1 源镜像 | 现役：strategy/convbond_backtest.py, strategy/可转债套利.py | src_wind.CCBONDVALUATION（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `CHINAMUTUALFUNDSTOCKPORTFOLIO` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：alpha_factory/data_gateway.py | src_wind.CHINAMUTUALFUNDSTOCKPORTFOLIO（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `FIN_APPO_RELE_DATE` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：strategy/growth_stock.py, strategy/growth_stock_2.py | src_wind.FIN_APPO_RELE_DATE（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `FXEODPRICES` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：core/market_data_service.py, strategy/ah_premium_hk_backtest.py | src_wind.FXEODPRICES（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `HKEXCALENDAR` | 未查 | 1 源镜像 | 现役：strategy/ah_premium_hk_backtest.py, strategy/generic_backtest_framework.py | src_wind.HKEXCALENDAR（第一批未收录，有现役读取，现不迁） | 补 DDL / src_tables.yaml 前须负责人确认。不定 visibility YAML，须负责人确认后再配 |
| `SHIBORPRICES` | 未查 | 1 源镜像 | src-plane 点名弱引用（data/test_task.py 等），第二批再评估 | src_wind.SHIBORPRICES（第二批评估，现不迁） | 不定 visibility YAML，须负责人确认后再配 |
| `SWINDEXMEMBERS` | 未查 | 1 源镜像 | 第一批 src_tables.yaml；现役：strategy/ah_premium_hk_backtest.py | src_wind.SWINDEXMEMBERS（第一批已收录，本清单不启动迁入） | 存量 pit_recoverable:false。不定 visibility YAML，须负责人确认后再配 |
| `alpha_factory_alert_d` | 未查 | 2 可重算 | 现役：scripts/resolve_alpha_factory_stale_canary_alert.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `alpha_factory_factor_value_d` | 未查 | 2 可重算 | 现役：alpha_factory/pf_nap/materialization.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `alpha_factory_factor_version` | 未查 | 2 可重算 | 现役：alpha_factory/registry.py, scripts/alpha_factory_pf_multidate_coverage_audit.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `alpha_factory_group_nav_d` | 未查 | 2 可重算 | 现役：alpha_factory/website_numeric_delta.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `alpha_factory_metric_d` | 未查 | 2 可重算 | 现役：alpha_factory/publish_factor_json.py, alpha_factory/website_numeric_delta.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `alpha_factory_universe_member_d` | 未查 | 2 可重算 | 现役：scripts/alpha_factory_pf_market_cap_authority_trace.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `con_forecast_stk_fttm_wide` | 未查 | 2 可重算 | 现役：agent_style_rotation/consensus_fttm_wide_builder.py, agent_style_rotation/data_gateway.py, agent_style_rotation/incremental_refresh_consensus_fttm_wide.py 等9处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `crowd_data` | 未查 | 2 可重算 | 现役：data/style_crowd_data.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `crowd_data_2` | 未查 | 2 可重算 | 现役：data/style_crowd_data.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `etf_hq_score` | 未查 | 2 可重算 | 现役：etf_sector_rotation/etf_sector_rotation/scripts/refresh_etf_hq_score.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `style_rotation_asset_state` | 未查 | 2 可重算 | 现役：agent_style_rotation/refresh_asset_state.py, agent_style_rotation/score_engine.py, data_registry/style_rotation/research_dashboard.json 等11处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `style_rotation_expectation_factor_d` | 未查 | 2 可重算 | 现役：agent_style_rotation/asset_state_engine.py, agent_style_rotation/refresh_dimension_factors.py, agent_style_rotation/score_engine.py 等9处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `style_rotation_fundamental_factor_d` | 未查 | 2 可重算 | 现役：agent_style_rotation/asset_state_engine.py, agent_style_rotation/lifecycle_engine.py, agent_style_rotation/refresh_dimension_factors.py 等12处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `style_rotation_lifecycle` | 未查 | 2 可重算 | 现役：agent_style_rotation/asset_state_engine.py, agent_style_rotation/refresh_dimension_factors.py, agent_style_rotation/score_engine.py 等11处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `style_rotation_price_d` | 未查 | 2 可重算 | 现役：data_registry/style_rotation/research_dashboard.json, scripts/style_rotation_full_backtest_report.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `style_rotation_price_factor_d` | 未查 | 2 可重算 | 现役：agent_style_rotation/asset_state_engine.py, agent_style_rotation/refresh_dimension_factors.py, agent_style_rotation/score_engine.py 等7处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `style_rotation_score` | 未查 | 2 可重算 | 现役：agent_style_rotation/refresh_score.py, scripts/style_rotation_evidence_validation.py, scripts/style_rotation_monitor_release.py 等5处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `style_rotation_score_d` | 未查 | 2 可重算 | 现役：data_registry/style_rotation/research_dashboard.json, scripts/style_rotation_full_backtest_report.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `alpha_factory_etf_factor_group_nav_d` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, scripts/analyze_etf_factor_effectiveness.py, alpha_factory/etf/persistence.py 等6处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `alpha_factory_etf_factor_metric_d` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, scripts/analyze_etf_factor_effectiveness.py, alpha_factory/etf/persistence.py 等6处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_abnormal_margin_intensity` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, factors/factor_etf_margin.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_avg_mom` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, scripts/backfill_index_avg_mom.py, alpha_factory/etf/combination_research.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_consistency` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_day_potential` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, data_registry/factors/etf_factor_rolling_monitor_freeze.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_institute_buy_percent` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_margin_intensity` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, factors/factor_etf_margin.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_overnight_ret` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, data_registry/factors/etf_factor_rolling_monitor_freeze.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_small_buy_ratio` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_trade_elasticity` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `index_up_beta` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_abso_umr` | 未查 | 2 可重算 | 现役：alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_actlargemedcut` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v1.json, alpha_factory/policies/pf_historical_factor_source_availability_v2.json 等4处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_core_down` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v1.json, alpha_factory/policies/pf_historical_factor_source_availability_v2.json 等6处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_core_up` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v2.json, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_corr_vrlag` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_corr_vrlaglarge` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_cutamp` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_did_ratio` | 未查 | 2 可重算 | 现役：alpha_factory/policies/pf_historical_factor_source_availability_v3.json, alpha_factory/refresh_performance_factor_fast_ic.py, alpha_factory/registered/registered_factors.json 等6处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_event_aog` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_event_delta_roe` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_event_high250` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, factors/factor_event.py, factors/factor_event_2.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_event_high_growth` | 未查 | 2 可重算 | 现役：alpha_factory/data_gateway.py, alpha_factory/etf/gateway.py, factors/factor_event.py 等5处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_event_sue` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json, factors/factor_event.py 等4处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_event_surprising` | 未查 | 2 可重算 | 现役：alpha_factory/data_gateway.py, alpha_factory/etf/gateway.py, factors/factor_event.py 等5处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_mif` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json, factors/daily_factor.py 等5处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_moneyflowh` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_nap_adj_ratio` | 未查 | 2 可重算 | 现役：alpha_factory/pf_nap/evidence.py, alpha_factory/pf_nap/materialization.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_ratio` | 未查 | 2 可重算 | 现役：alpha_factory/data_gateway.py, alpha_factory/factor_testing_legacy_compat.py, alpha_factory/publish_alpha_factory_registry.py 等7处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_ratio_realdownvar` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_ratio_realupvar` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_real_kurt` | 未查 | 2 可重算 | 现役：alpha_factory/pf_historical_market_cap_policy.py, alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_rpt_excess_num` | 未查 | 2 可重算 | 现役：factors/factor_event.py, factors/factor_event_2.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `stock_tr_umr` | 未查 | 2 可重算 | 现役：alpha_factory/policies/pf_historical_factor_source_availability_v3.json | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `etf_ratio` | 未查 | 2 可重算 | 现役：alpha_factory/etf/scripts/analyze_etf_factor_tradability.py, core/market_data_service.py, scripts/run_asset_allocation_backtest.py 等15处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `market_heat_limit_num` | 未查 | 2 可重算 | 现役：data/情绪择时推送.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `market_heat_up_down_num` | 未查 | 2 可重算 | 现役：data/情绪择时推送.py | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `performance_factor` | 未查 | 2 可重算 | 现役：alpha_factory/data_gateway.py, alpha_factory/discover_performance_factor_singles.py, alpha_factory/performance_factor_score.py 等23处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `performance_factor_etf` | 未查 | 2 可重算 | 现役：alpha_factory/etf/gateway.py, etf_sector_rotation/etf_sector_rotation/scripts/refresh_etf_hq_score.py, alpha_factory/etf/contracts.py 等4处 | 不迁 wx2 行；新仓 features/mart 重算 | stock_* 运行时建表模式丢弃，统一长表。不定 visibility YAML，须负责人确认后再配 |
| `strategy_etf_index_indicator` | 未查 | 2 可重算 | 应用派生表，现役：data/etf_real_trade_v14.py, etf_sector_rotation/etf_sector_rotation/data/market_data.py, etf_sector_rotation/etf_sector_rotation/gateways/rotation_gateway.py 等5处 | 不迁 wx2 行；按新仓对应能力重写 | 不定 visibility YAML，须负责人确认后再配 |
| `strategy_etf_index_indicator_2` | 未查 | 2 可重算 | 应用派生表，现役：data/ETF四象限推送.py | 不迁 wx2 行；按新仓对应能力重写 | 不定 visibility YAML，须负责人确认后再配 |
| `strategy_etf_margin_trade` | 未查 | 2 可重算 | 应用派生表，现役：data/宽基指数配置策略.py | 不迁 wx2 行；按新仓对应能力重写 | 不定 visibility YAML，须负责人确认后再配 |
| `strategy_industry_index_indicator` | 未查 | 2 可重算 | 应用派生表，现役：data/etf_trend_strategy.py | 不迁 wx2 行；按新仓对应能力重写 | 不定 visibility YAML，须负责人确认后再配 |
| `strategy_trade_signal` | 未查 | 2 可重算 | 应用派生表，现役：data/etf_real_trade_v14.py, etf_sector_rotation/configs/etf_rotation_v1.yaml, etf_sector_rotation/etf_sector_rotation/data/holdings.py 等4处 | 不迁 wx2 行；按新仓对应能力重写 | 不定 visibility YAML，须负责人确认后再配 |
| `universe_did` | 未查 | 2 可重算 | 旧股票池缓存；现役：alpha_factory/all_a_canonical_scene.py, alpha_factory/layered_universe.py | 不迁 wx2 行；新仓 UniverseRepository 重算 | 不定 visibility YAML，须负责人确认后再配 |
| `universe_did1` | 未查 | 2 可重算 | 旧股票池缓存；现役：alpha_factory/layered_universe.py | 不迁 wx2 行；新仓 UniverseRepository 重算 | 不定 visibility YAML，须负责人确认后再配 |
| `universe_growth` | 未查 | 2 可重算 | 旧股票池缓存；现役：alpha_factory/data_gateway.py, alpha_factory/layered_universe.py | 不迁 wx2 行；新仓 UniverseRepository 重算 | 不定 visibility YAML，须负责人确认后再配 |
| `universe_growth1` | 未查 | 2 可重算 | 旧股票池缓存；现役：alpha_factory/layered_universe.py | 不迁 wx2 行；新仓 UniverseRepository 重算 | 不定 visibility YAML，须负责人确认后再配 |
| `agent_risk_insight` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `portfolio_info` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `portfolio_metrics` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `portfolio_nav` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `portfolio_position` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `portfolio_weight` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `scheduler_job_run_log` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：task_scheduler/sqlserver_schema.sql, task_scheduler/store.py | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `strategy_metrics` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：strategy_engine/storage.py | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `strategy_nav` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：enhanced_optimizer/data/gateway.py, enhanced_optimizer/risk_budget_joint_optimizer.py, strategy_engine/storage.py | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `strategy_order` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：strategy_engine/storage.py | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `strategy_position` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：strategy_engine/storage.py | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `strategy_run` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：enhanced_optimizer/data/gateway.py, enhanced_optimizer/risk_budget_joint_optimizer.py, strategy_engine/storage.py | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `strategy_trade` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：strategy_engine/storage.py | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `task_error_detail` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：data/task_monitor.py, data/宽基指数配置策略.py, task_scheduler/runner.py | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `task_moniter` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：alpha_factory/stock_hq_score_refresh.py, data/etf_trend_strategy.py, data/task_monitor.py 等11处 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `agent_candidate` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `agent_decision` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `agent_evidence` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `agent_portfolio` | 未查 | 4 运维改造 | 控制/审计/调度/组合状态；现役：strategy_engine/adapters/enhanced_500_joint_optimizer.py, strategy_engine/adapters/enhanced_500_risk_budget.py, strategy_engine/readiness_sql_providers.py 等4处 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `agent_run` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `doc_notice_chunk` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `doc_notice_text` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `doc_report_chunk` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `strategy_monitor_account` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `strategy_monitor_account_his` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `sys_user` | 未查 | 4 运维改造 | 控制状态表，字典或代码有建表 | ops_* 重建模；先看 Dagster 覆盖范围，不照搬旧表 | 改正表名/补主键；不进研究数据面。不定 visibility YAML，须负责人确认后再配 |
| `index_basic` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `indicator_dividend_crowd` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `indicator_dividend_crowd_test` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `indicator_growth_crowd` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `indicator_pb_roe_crowd` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `indicator_small_value_crowd` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_actlargemed` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_actlargenon` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_actsml` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_actsmlnon` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_amihud_illiq` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_avt_umr` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_corr_vp` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_corr_vplarge` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_corr_vr` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_corr_vrlead` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_diverge_a1` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_diverge_a2` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_em_yjyg` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_event_udpct` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_event_unexp_to` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_exlargemed` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_factors` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_hero_take` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_high_price_avgvol` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_high_price_vol` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_hk_hold` | 未查 | 5 无消费者 | 派生/应用表，现役无引用；仅写入：data/tushare_data.py, data/wind_to_sql_2.py, data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511 |
| `stock_hk_hold_weight` | 未查 | 5 无消费者 | 派生/应用表，现役无引用；仅写入：data/tushare_data.py, data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511 |
| `stock_industry` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_intraday_maxdrawdown` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_low_price_avgvol` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_low_price_vol` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_min_avg_amt_corr_amt` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_min_avg_amt_corr_price` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_min_avg_amt_kurt` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_min_avg_amt_qua` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_min_avg_amt_skew` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_min_avg_amt_sr` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_min_avg_amt_std` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_min_price` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ocac_5m` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ocac_umr` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_payout_his` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_payout_ratio` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_rankcorrrs` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ratio_vol1` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ratio_vol2` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ratio_vol3` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ratio_vol4` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ratio_vol5` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ratio_vol6` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ratio_vol7` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ratio_vol8` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_real_downvar` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_real_skew` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_real_skewlarge` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_real_upvar` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_real_var` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_research_report` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ret_h8` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ret_open2ah1` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ret_open2ah2` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ret_open2al1` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_ret_open2al2` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_rpt_num` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_s_pctchg` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_s_pctchg_pre` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_skew_5m` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_skew_5m_umr` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_smart2` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_smart3` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_std_5m` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_std_5m_umr` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_to_umr` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_total_mv` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_trendratio` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `stock_vwap_drift_umr` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `Bond_BaseRateReference` | 未查 | 5 无消费者 | 仅采集写入：data/jydb_to_sql.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `C_ED_CustomsData` | 未查 | 5 无消费者 | 仅采集写入：data/jydb_to_sql.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `CT_Product` | 未查 | 5 无消费者 | 仅采集写入：data/jydb_to_sql.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `IN_MeansofProductionPI` | 未查 | 5 无消费者 | 仅采集写入：data/jydb_to_sql.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `QT_IndexQuote` | 未查 | 5 无消费者 | 仅采集写入：data/jydb_to_sql.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `der_excess_stock` | 未查 | 5 无消费者 | 仅采集写入：data/zyyx_to_sql.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `ashare_stock_notices` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_data.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `echart_stock_fundamental` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `echart_stock_list` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `etf_amount` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `etf_est_earning_fy2` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `etf_price` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `etf_volume` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `fina_balancesheet` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_cashflow` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_est_eps_fy2` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_est_netprofit_fy2` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_est_netprofit_gr2` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_express` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_forecast` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_income` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_indicator` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_rating_targetprice` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fina_rpt_forecast_roe_w` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fund_daily_indicator` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fund_description` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fund_em_value_est` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_data_pm.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fund_list` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_data.py, data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fund_monthly_return` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fund_nav` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fund_net_value` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `fund_simulate_citics2_ratio` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `fund_simulate_citics_ratio` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `fund_simulate_stock_portfolio_2` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `fut_holding` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_data.py, data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `gx_fund` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `h_ofnav` | 未查 | 5 无消费者 | 历史策略结果，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `h_oforder` | 未查 | 5 无消费者 | 历史策略结果，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `industry_research_report` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `joinquant_backtest` | 未查 | 5 无消费者 | 历史策略结果，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `mapping_csrc_citics` | 未查 | 5 无消费者 | 参考/映射表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `mapping_future_contract` | 未查 | 5 无消费者 | 参考/映射表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `mapping_trade_etf` | 未查 | 5 无消费者 | 参考/映射表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `market_heat_avg_pctchg` | 未查 | 5 无消费者 | 派生/应用表，现役无引用；仅写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511 |
| `market_heat_middle_indicator` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `market_heat_rzrq` | 未查 | 5 无消费者 | 派生/应用表，现役无引用；仅写入：data/tushare_data.py, data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511 |
| `market_hk_hold_pct` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `performance_factor_etf_backup` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_company_info` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_distribution` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_attributes` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_futurestype_mapping` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_info` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_manager_mapping` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_performance` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_rate_mapping` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_risk_stats` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_riskadjret_stats` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_status` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_fund_strategy` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `pvn_nav` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_etf_crowd` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_etf_holding_rank` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_etf_index_indicator_test2` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_etf_index_size` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_etf_list_rebate` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_etf_pool` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_etf_raw_rank` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_etf_timing_flag` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_future_eod_amount` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_future_list` | 未查 | 5 无消费者 | 派生/应用表，现役无引用；仅写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511 |
| `strategy_industry_pool` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_result_wflm` | 未查 | 5 无消费者 | 历史策略结果，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_result_wflm_2` | 未查 | 5 无消费者 | 历史策略结果，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_result_wflm_3` | 未查 | 5 无消费者 | 历史策略结果，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_result_xhy` | 未查 | 5 无消费者 | 历史策略结果，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_trade_flow` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_trade_signal_date` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_trade_signal_his` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `strategy_trade_signal_log` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `t_custmark_stkratio` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `t_simfund_statistic` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `t_simfund_statistic_etf` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `t_simfund_statistic_weekly` | 未查 | 5 无消费者 | 派生/应用表，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `test_table` | 未查 | 5 无消费者 | 测试残留表 | 不迁移 | 旧仓 7c506d511 |
| `tushare_ths_industry_list` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_ths_industry.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `tushare_ths_industry_market` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_ths_industry.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `tushare_ths_industry_member` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_ths_industry.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `tushare_ths_industry_member_2` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_ths_industry.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `tushare_ths_industry_member_3` | 未查 | 5 无消费者 | 仅采集写入：data/tushare_ths_industry.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `universe_500_1800_balance` | 未查 | 5 无消费者 | 旧股票池缓存，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `universe_500_1800_growth` | 未查 | 5 无消费者 | 旧股票池缓存，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `universe_500_1800_value` | 未查 | 5 无消费者 | 旧股票池缓存，现役无引用 | 不迁移 | 旧仓 7c506d511 |
| `AINDEXDESCRIPTION` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `AINDEXFINANCIALDERIVATIVE` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `ASHARESECNINDUSTRIES` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `ASHARESECNINDUSTRIESCLASS` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `ASHARESTOCKREPO` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `ASWSINDEX` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `ASWSINDEXEOD` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `CBINDEXDESCRIPTION` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `CFUTURESCONTRACTMAPPING` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `CFUTURESDESCRIPTION` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `CFUTURESMAIN` | 未查 | 5 无消费者 | 字典或代码有记载，现役模块/启用调度/data_registry 均无引用 | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `CHINACLOSEDFUNDEODPRICE` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `CHINAMUTUALFUNDNAV` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `SHSCCHANNELHOLDINGS` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_am.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |
| `SHSZRELATEDSECURITIES` | 未查 | 5 无消费者 | 仅采集写入：data/wind_to_sql_2.py, data/wind_to_sql_before_open.py | 不迁移 | 旧仓 7c506d511。不定 visibility YAML，须负责人确认后再配 |

