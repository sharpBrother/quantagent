---
title: 旧仓文档与制品处置清单
status: active
created: 2026-09-18
updated: 2026-09-18
applies_to:
  - docs/migration/docs-and-artifacts-disposition.md
  - docs/migration/docs-and-artifacts-list.yaml
  - tests/contracts/test_docs_and_artifacts_list.py
  - frozen/
supersedes: null
superseded_by: null
---

# 旧仓文档与制品处置清单

P2 第 5 条交付物，**本文件是评审基线**。分类标准见
[docs-and-artifacts-disposition.md](docs-and-artifacts-disposition.md)。
机器可读副本：[docs-and-artifacts-list.yaml](docs-and-artifacts-list.yaml)。

**不迁入。** 冻结制品的迁移与口径改写在 P5 才执行。

## 范围与指针

- 旧仓：`pycharm_workspace` @ `7c506d51160e57385fd85217edece815268ffd55`
- 文档：本 commit `docs/` 共 3415 文件（其中 3278 份 md），与公约所称「3422」同量级，差在后续工作树未纳入本清单
- 反查：现役 py / `task_scheduler/jobs.json` 对 `outputs/`、`reports/`、`data_registry/` 的路径；新仓 `docs/` 对旧仓绝对路径的指针；`docs/decisions/README.md` 现行裁定 vs 代码
- 归并：TASK/REVIEW/台账按目录一行+文件数；冻结 bundle、仍生效裁定、有现役读取的 outputs/reports **逐项**
- 消费者不含一次性 `scripts/taskNNNN`、已丢弃 `legacy/` 代码、采集只写不读

## 汇总

| 类别 | 项数 | 覆盖文件数（约） |
|---|---:|---:|
| 1 冻结制品与可复现输入 | 8 | 48 |
| 2 仍在生效的口径裁定 | 124 | 124 |
| 3 有效知识 | 31 | 165 |
| 4 过程记录 | 26 | 3058 |
| 5 被取代或自相矛盾 | 56 | 2076 |
| 合计 | 245 | 5471 |

覆盖文件数只是归并项的 `file_count` 之和，目录重叠（例如 `docs/DESIGN/` 与 DESIGN-0008 单列、`reports/remaining/` 与四条 market_data）会重复计数，**不是**旧仓文件总数。

bond_timing exhibit freeze 是已知必迁范例，见逐项表第一行。

## 逐项清单

| 路径 | 类别 | 依据 | 拟去向 | 附加约束 |
|---|---|---|---|---|
| `outputs/bond_timing_exhibit_freeze/` | 1 冻结制品 | 已知必迁范例。bond_timing/refresh.py 与 jobs.json bond_timing_exhibit_refresh_publish 只读此 bundle；含 manifest/config/nav.csv/signals.csv 共 4 文件 | 拟 frozen/bond_timing/exhibit_freeze/（完整迁 manifest、config、data；现不迁） | nav.csv 约 1.0MB，frozen/ 单文件上限 4MB 的显式例外。digest 按 LF。research-only、dml=0。对应裁定 docs/decisions/2026-09-13-bond-timing-exhibit-freeze-bundle.md |
| `outputs/gold_timing_exhibit_freeze/` | 1 冻结制品 | 现役：gold_timing/freeze_bundle.py 与 jobs.json gold_timing_exhibit_refresh_publish 绑定 manifest.json；4 文件 | 拟 frozen/gold_timing/exhibit_freeze/（完整迁；现不迁） | nav.csv/signals.csv 均约 1MB。research-only、dml=0。对应裁定 2026-09-14-gold-timing-exhibit-freeze-bundle.md |
| `outputs/multi_asset_core5_exhibit_freeze/` | 1 冻结制品 | 现役：multi_asset/freeze_bundle.py 与 jobs.json multi_asset_core5_exhibit_refresh_publish；14 文件含 size_panel.csv | 拟 frozen/multi_asset/core5_exhibit_freeze/（完整迁；现不迁） | size_panel.csv 约 3.1MB，低于 4MB。对应 2026-09-13-multi-asset-core5-website-exhibit.md |
| `outputs/style_rotation_exhibit_freeze/` | 1 冻结制品 | 现役：style_rotation/exhibit/freeze_bundle.py 默认根目录；jobs.json style_rotation_research_exhibit_refresh_publish 启用；12 文件 | 拟 frozen/style_rotation/exhibit_freeze/（完整迁；现不迁） | 日增 overlay 不读 reports/。对应 2026-09-04-style-rotation-research-exhibit-live-overlay.md |
| `outputs/etf_factor_website_freeze/` | 1 冻结制品 | 现役：alpha_factory/etf/website_freeze.py DEFAULT_WEBSITE_FREEZE_BUNDLE_PATH；website_data.py 发布前校验 digest；6 文件 | 拟 frozen/etf/website_freeze/（完整迁；现不迁） | research-only、dml=0。对应 2026-09-12-etf-website-freeze-bundle.md。历史 NAV 不在此 bundle 重复保存，见 2026-09-17-etf-baseline-daily-continuation.md |
| `data_registry/factors/etf_factor_rolling_monitor_freeze.json` | 1 冻结制品 | 现役：alpha_factory/etf/{website_data,regime_website,current_holdings,strategy_data}.py DEFAULT_FREEZE_MANIFEST_PATH | 拟 frozen/etf/rolling_monitor_freeze/（连同 manifest digest 合同；现不迁） | 冻结因子身份，不重算。体积约 23KB |
| `data_registry/factors/etf_factor_regime_website.json` | 1 冻结制品 | 现役：alpha_factory/etf/regime_website.py 与 website 读模型 etf_factor_regime_website_v4；冻结 performanceSeries 不重算 | 拟 frozen/etf/regime_website_freeze/（现不迁） | 日增只追加冻结末日之后，见 2026-09-17-etf-baseline-daily-continuation.md。体积约 89KB |
| `data_registry/factors/etf_factor_daily_refresh/` | 1 冻结制品 | 现役：alpha_factory/etf/refresh_inputs.py 读取 manifest、monitor_members.json、spec_overrides、preflight；jobs.json alpha_factory_etf_factor_refresh | 拟 frozen/etf/daily_refresh_inputs/（现不迁） | availability_cache.json 可重建，不进 frozen/。single_factor_preflight_20260907_reverse_v2.json 约 12MB，超过 frozen/ 4MB 上限，P5 须单独评估不自动放行 |
| `docs/decisions/2026-08-17-pf-nap-v5-identity-drop-qualification-binding.md` | 2 口径裁定 | identity 摘除授权绑定，现役 PF 合同仍按此 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-18-all-a-daily-canonical-scene.md` | 5 已取代 | README 标 Superseded；all_a 场景合同已改 | 不迁移，清单记一行 | 市值观测域见 2026-08-27-all-a-canonical-membership-market-cap-domain.md |
| `docs/decisions/2026-08-18-coverage-policy-drop-family-size-gate.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-18-drop-qualification-authorized-flags.md` | 2 口径裁定 | 去掉授权旗标；与新仓取消审批链一致且旧代码已执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-18-macro-curves-strategy-engine-research-backtest.md` | 2 口径裁定 | 宏观曲线允许进研究回测；取代 DESIGN-0029 禁令 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-18-observed-domain-sample-floor.md` | 2 口径裁定 | observed domain 样本下限，不得换成 all-A | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-18-pf-nap-v5-slim-candidate.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-18-repin-governance-doc-sha.md` | 5 已取代 | 编号文档 SHA 钉扎，属治理台账 | 不迁移，清单记一行 | 新仓无编号台账 |
| `docs/decisions/2026-08-20-factor-output-legacy-cleanup.md` | 5 已取代 | 清理 outputs/factor.json 的过渡裁定；新仓 publish/ 重装，不继承旧 JSON 路径 | 不迁移，清单记一行 | 现役代码已禁止 outputs/factor.json |
| `docs/decisions/2026-08-20-style-rotation-dynamic-only-website-channel.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-21-did-growth-daily-canonical-scene.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-21-etf-factor-testing-module.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-21-style-rotation-public-asset-retention.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-21-style-rotation-top20-monthly-refresh.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-21-top20-settle-date-display.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-22-alpha-factory-refresh-git-push.md` | 4 过程记录 | 旧调度 git push 发布操作 | 不迁移，旧仓追溯 | 新仓 publish 装配器取代；Dagster 重写调度 |
| `docs/decisions/2026-08-22-daily-metric-lookback-10.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-22-factor-website-reads-git-outputs.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-22-forward-return-source-integrity.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-22-style-rotation-git-publish.md` | 4 过程记录 | 风格轮动 git 发布操作 | 不迁移，旧仓追溯 | 同上 |
| `docs/decisions/2026-08-23-etf-constituent-factor-aggregation.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-23-macro-risk-neutral-market-data-entry.md` | 2 口径裁定 | 宏观风险中性入口；h00985 不得覆盖 000985.CSI | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-23-numbered-docs-legacy-archive.md` | 5 已取代 | 编号归档规则已被新仓 docs/adr/2026-09-16-docs-without-numbering.md 取代 | 不迁移，清单记一行 | 过程目录仍按此迁入过 docs/legacy/，不把编号体系带进新仓 |
| `docs/decisions/2026-08-23-project-knowledge-archive.md` | 5 已取代 | Project Knowledge allowlist 归档，属旧流程 | 不迁移，清单记一行 | 新仓唯一入口 docs/README.md |
| `docs/decisions/2026-08-23-stock-factor-group-id-lowest-first.md` | 2 口径裁定 | group_id=1=最低组；取代 DESIGN-0008 反转 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-24-medium-long-loan-null-publish-date.md` | 2 口径裁定 | 仅 IndicatorCode=1530094044 空发布日用次月 20 日 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-24-pf-nap-frozen-v5-cross-check.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-24-pf-nap-neutral-materialization-qualification.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-24-pf-nap-observed-domain-neutralization.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-24-pf-nap-semantic-selector-revision.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-24-pf-nap-v3-v4-legacy-archive.md` | 5 已取代 | v3/v4 归档说明，不是现役口径 | 不迁移，清单记一行 | 现役 PF nap 以 ADR-0074/0075 为准 |
| `docs/decisions/2026-08-24-public-equity-risk-premium-source.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-25-etf-close-signal-t-minus-one-indicator.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-25-etf-incremental-refresh.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/ 或并入 AGENTS.md 写入铁律指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-25-southwest-historical-extension.md` | 5 已取代 | 2018-03-30 起点被 2026-08-26-southwest-historical-extension-2010.md 覆盖 | 不迁移，清单记一行 | 现役扩展起点 2010-04-30 |
| `docs/decisions/2026-08-25-southwest-research-closure.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-25-southwest-research-scope.md` | 2 口径裁定 | 仅 southwest_*；000985.CSI 月末 PIT、T+1 开盘 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-25-southwest-rv-dsv-vote.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-26-macro-regime-website-data-contract.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-26-margin-intensity-factor-caliber.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-26-southwest-historical-extension-2010.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-27-all-a-canonical-membership-market-cap-domain.md` | 2 口径裁定 | 缺 mv/free_float_mv 不属于当日 all_a | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-27-etf-factor-result-natural-identity.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-27-stock-metric-historical-backfill.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-28-style-rotation-phase1-alpha-attribution.md` | 3 有效知识 | 行业轮动超额归因合同，不改生产 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 行业监控已归档到 /style-rotation/industry |
| `docs/decisions/2026-08-28-umr-money-flow-read-path.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-29-style-rotation-phase2-industry-alpha.md` | 3 有效知识 | Industry Alpha 第二阶段冻结，不改生产 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 不迁原文 |
| `docs/decisions/2026-08-29-style-rotation-phase3-industry-alpha-components.md` | 3 有效知识 | 原子组件与 dividend 不用 fillna(0) 的陷阱记录 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | fillna(0) 禁忌可提炼进 domain |
| `docs/decisions/2026-08-29-style-rotation-phase3-start-gate.md` | 3 有效知识 | 开工门与残差禁止写成纯 alpha | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 过程门已过，留知识 |
| `docs/decisions/2026-08-29-umr-weekend-catchup-next-open.md` | 5 已取代 | README 标 Superseded | 不迁移，清单记一行 | UMR 现役读取见 2026-08-28-umr-money-flow-read-path.md |
| `docs/decisions/2026-08-30-growth-value-style-rotation-research.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-30-source-table-initialization.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/ 或并入 AGENTS.md 写入铁律指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-30-style-rotation-phase4-dividend-quality-breadth.md` | 3 有效知识 | Dividend-Quality 机制研究，不改生产 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 不迁原文 |
| `docs/decisions/2026-08-31-did-growth-scene-delisted-member-handling.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-31-growth-value-balanced-benchmark.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-31-performance-factor-event-pit.md` | 2 口径裁定 | event_* 按 confirm_date；get_events T-2 是策略层 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-08-31-scheduler-natural-date-attribution.md` | 2 口径裁定 | 旧调度按自然日 15:00 切日；切 Dagster 前仍约束 jobs.json | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-01-cbondcurvecnbd-term-sync.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-01-growth-value-overnight-shibor.md` | 5 已取代 | 已知会误导：Wind SHIBORPRICES / TRADE_DT+1 PIT 已被 macro_shibor 同日 PIT 取代 | 不迁移，清单记一行 | 以 2026-09-02-growth-value-shibor-macro-table.md 为准；代码走 wx2.dbo.macro_shibor |
| `docs/decisions/2026-09-01-jydb-bond-curve-gap-repair.md` | 4 过程记录 | 一次性 JSID 范围补齐收据 | 不迁移，旧仓追溯 | insert-only 原则已在 AGENTS.md；本页是当时执行记录 |
| `docs/decisions/2026-09-01-large-small-style-rotation-research.md` | 3 有效知识 | Phase A 开题范围；后续口径多份后继裁定已收窄 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | SHIBOR 1M proxy 等已被后继数据源裁定覆盖，开题文不当现役口径 |
| `docs/decisions/2026-09-02-cbondcurvecsi-daily-sync.md` | 5 已取代 | README 标 Superseded；日增范围以后继历史回填裁定为准 | 不迁移，清单记一行 | 以 2026-09-02-cbondcurvecsi-historical-backfill.md 为准 |
| `docs/decisions/2026-09-02-cbondcurvecsi-historical-backfill.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-02-growth-value-phase1-5-vote-structure.md` | 3 有效知识 | 投票结构诊断，明确不改变 2:2->Growth | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 有效教训可提炼，不迁原文 |
| `docs/decisions/2026-09-02-growth-value-phase1-attribution.md` | 3 有效知识 | Phase 1 归因协议与冻结 Replication Baseline V1，是研究过程知识 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 正式策略身份见 final-research-closure；不照搬任务语境 |
| `docs/decisions/2026-09-02-growth-value-shibor-macro-table.md` | 2 口径裁定 | 成长/价值使用 macro_shibor，trade_date <= signal_date | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-02-large-small-active-period-metrics.md` | 3 有效知识 | 净值窗口锚点研究口径 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 展厅冻结后作为知识提炼 |
| `docs/decisions/2026-09-02-large-small-credit-single-factor-score.md` | 3 有效知识 | 信用单因子对照，research-only | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 组合结构见 5-core + credit confirmation |
| `docs/decisions/2026-09-02-large-small-credit-spread-and-relative-volatility.md` | 3 有效知识 | 信用利差与波动数据口径的研究记录 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 仍被 5-core 结构引用的部分写入 C2 后继裁定，本文作知识 |
| `docs/decisions/2026-09-02-large-small-money-supply-source.md` | 2 口径裁定 | ED_MoneySupply 可见日=EndDate 次月 15 日，InfoPublDate 仅审计 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-02-tushare-shibor-etl.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-02-tushare-shibor-history-extension.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-02-us-treasury-yield-insert-only.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/ 或并入 AGENTS.md 写入铁律指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-03-growth-value-final-research-closure.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-03-growth-value-phase2-parameter-mechanism.md` | 3 有效知识 | 参数族扰动协议，不自动选参 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 不迁原文 |
| `docs/decisions/2026-09-03-jydb-ed-money-supply-gap-repair.md` | 4 过程记录 | 一次性 59 行缺口补齐收据 | 不迁移，旧仓追溯 | 不迁 |
| `docs/decisions/2026-09-03-large-small-20d-core-conviction-oos.md` | 3 有效知识 | OOS 门槛 not_supported_oos 的失败教训 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 典型「不要把全样本单调当时间外证据」 |
| `docs/decisions/2026-09-03-large-small-5-core-credit-confirmation.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-03-large-small-phase-c-parameter-stability.md` | 3 有效知识 | OAT 网格与不选单点最高 Sharpe 的研究纪律 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | Phase E 已冻结代表参数 |
| `docs/decisions/2026-09-04-jydb-incremental-missing-data-policy.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/ 或并入 AGENTS.md 写入铁律指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-04-large-small-phase-d-finalization.md` | 5 已取代 | 历史记录 Phase D 输出 NO_DECISION；验证基线已由 Phase E 前置裁定覆盖 | 不迁移，清单记一行 | 现役见 2026-09-04-large-small-phase-e-precondition.md |
| `docs/decisions/2026-09-04-large-small-phase-e-etf-source.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-04-large-small-phase-e-precondition.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-04-style-rotation-research-exhibit-live-overlay.md` | 2 口径裁定 | 现役风格展厅冻结输入 + live overlay；jobs 启用 | 拟改写 docs/adr/（新仓已有 2026-09-16-frozen-artifacts.md 作目录策略，本裁定正文未迁；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-04-style-rotation-research-exhibit-website.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-05-macro-website-historical-performance.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-05-tushare-shibor-daily-refresh.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-06-bond-gold-timing-intended-nav.md` | 5 已取代 | 自认半截序列不得当结论；债券现役身份已改西南四票 | 不迁移，清单记一行 | 不迁 |
| `docs/decisions/2026-09-06-bond-gold-timing-website-exhibit.md` | 5 已取代 | 路由枢纽已被 2026-09-11-bond-gold-timing-website-hub.md 取代 | 不迁移，清单记一行 | research-only 边界仍被后继裁定继承，不从本文迁 |
| `docs/decisions/2026-09-06-bond-timing-research-line.md` | 5 已取代 | 已被西南四票月频再被双周调仓取代；历史两票/000012.SH 身份 | 不迁移，清单记一行 | 现役 identity 见 2026-09-07-bond-timing-biweekly-four-vote.md |
| `docs/decisions/2026-09-06-bond-timing-southwest-four-vote.md` | 2 口径裁定 | 月末投票已废；收益腿/半仓/PMI·地产公式仍约束现役 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 只继承仍有效的公式段，月末投票不迁 |
| `docs/decisions/2026-09-06-etf-core-down-partial-window.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-06-gold-timing-research-line.md` | 5 已取代 | 已被西南七票月频取代；历史两票/伦敦金现身份 | 不迁移，清单记一行 | 现役 identity 见 2026-09-08-gold-timing-southwest-seven-vote.md |
| `docs/decisions/2026-09-07-bond-timing-biweekly-four-vote.md` | 2 口径裁定 | 现役债券 decisionCode=SOUTHWEST_FOUR_VOTE_BIWEEKLY | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-07-bond-timing-close-execution.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-07-bond-timing-daily-four-vote.md` | 2 口径裁定 | 调仓频率已废，但 T 日缺值取更早有限报价仍被现役沿用 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 类别按「缺值回退仍执行」留在第二类，调仓频率本身已废 |
| `docs/decisions/2026-09-07-bond-timing-estate-january-carry.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-07-bond-timing-robustness-protocol.md` | 3 有效知识 | 稳健性对照协议，不改现役双周身份 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 不迁原文 |
| `docs/decisions/2026-09-07-etf-incremental-drift-overwrite.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/ 或并入 AGENTS.md 写入铁律指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-07-regulatory-word-ooxml-revision-gate.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-07-southwest-keep-month-end-decision.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-08-etf-factor-daily-publish.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-08-etf-factor-website-cumulative-nav.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-08-gold-timing-southwest-seven-vote.md` | 2 口径裁定 | 现役黄金七票月末 vs 现金 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-08-tushare-eco-cal-etl.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-09-etf-factor-v2-production-identity.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-09-gold-timing-whitelist-scheduler.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-09-jin10-ism-empty-actual.md` | 2 口径裁定 | 空今值先丢掉再按日期 < T 去重 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-09-jin10-ism-pmi-crawler.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-09-jin10-ism-pmi-storage.md` | 2 口径裁定 | 独立入库表 insert-only，不进 Tushare/JYDB 表 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-09-reports-working-payload-ignore.md` | 5 已取代 | 旧仓按文件族 ignore reports；新仓已用 var/ 整体忽略，不再逐任务开例外 | 不迁移，清单记一行 | 与新仓 .gitignore 十几行策略冲突，不迁 |
| `docs/decisions/2026-09-09-wgc-bars-vintage-pit.md` | 2 口径裁定 | WGC 发布日期映射；自认非严格 vintage | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 与新仓 fail-closed PIT 不完全同级；迁入前标 grade，不得把 _ingested_at 当 PIT |
| `docs/decisions/2026-09-09-wgc-gold-demand-detail-scope.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 与新仓 fail-closed PIT 不完全同级；迁入前标 grade，不得把 _ingested_at 当 PIT |
| `docs/decisions/2026-09-10-gold-timing-frequency-robustness.md` | 3 有效知识 | 预注册频率对照，升级门槛见保持月末裁定 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 现役频率以 keep-month-end 为准 |
| `docs/decisions/2026-09-10-gold-timing-ism-reads-table.md` | 2 口径裁定 | ISM 经 MDS 读 macro_jin10_usa_ism_pmi，publish_date < T | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-10-gold-timing-six-vote-preregister.md` | 3 有效知识 | 去 VIX 六票对照，不改现役七票 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 不迁原文 |
| `docs/decisions/2026-09-10-gold-timing-structure-closure.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-10-gold-timing-structure-diagnostics.md` | 3 有效知识 | 结构诊断协议；WGC 非严格 vintage 自认 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | WGC 迁入前单独标 pit_grade，见新仓 pit-rules.md |
| `docs/decisions/2026-09-10-gold-timing-vix-pit.md` | 2 口径裁定 | 七票 VIX 用 trade_date < T，禁止当日收盘 | 拟并入 docs/domain/pit-rules.md（新仓已从旧仓下游反推部分规则；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-11-bond-gold-timing-cadence-signal-date.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-11-bond-gold-timing-frozen-exhibit-overlay.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-11-bond-gold-timing-website-hub.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-11-bond-timing-review-gates.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-11-etf-factor-regime-website.md` | 5 已取代 | README 标明已取代；历史基线，日增扩展见 2026-09-17-etf-baseline-daily-continuation.md | 不迁移，清单记一行 | 制品 etf_factor_regime_website.json 仍作冻结输入（类别 1），本文只作过时合同 |
| `docs/decisions/2026-09-11-factor-main-money-flow-gateway.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-11-gold-timing-keep-month-end.md` | 2 口径裁定 | 正式基线继续月末 4/7，不升级双周 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-11-gold-timing-overlay-safety.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-11-multi-asset-core4-portfolio.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-12-etf-website-freeze-bundle.md` | 2 口径裁定 | 现役 ETF website freeze bundle 与日增量输入分离 | 拟改写 docs/adr/（新仓已有 2026-09-16-frozen-artifacts.md 作目录策略，本裁定正文未迁；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-12-factor-research-facade.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-12-factor-research-trace-regime.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-12-multi-asset-bl-v1-spec.md` | 2 口径裁定 | 正式放弃 BL；主框架 ERC + Direct Signal Tilt | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-12-multi-asset-dynamic-risk-budget.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-12-multi-asset-sleeve-attribution.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-12-multi-asset-target-vol.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-12-research-portfolio-cost-profile.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-13-bond-timing-exhibit-freeze-bundle.md` | 2 口径裁定 | 现役债券展厅冻结合同；refresh 不读 reports CSV | 拟改写 docs/adr/（新仓已有 2026-09-16-frozen-artifacts.md 作目录策略，本裁定正文未迁；现不迁） | P5 与 bundle 一并改写 ADR；不得照搬编号语境 |
| `docs/decisions/2026-09-13-multi-asset-core5-nasdaq.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-13-multi-asset-core5-production-baseline.md` | 2 口径裁定 | Production Baseline=Core5 Monthly Tilt；Research Champion 仍 Core4 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-13-multi-asset-core5-website-exhibit.md` | 2 口径裁定 | 现役 Core5 展厅 freeze/overlay 与 /zh/portfolio 只读契约 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-13-multi-asset-rebalance-cost.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-14-core5-exhibit-equity-sleeve.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-14-etf-current-holdings-push.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-14-etf-ew-z-current-holdings.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-14-etf-indicator-incremental-backfill.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/ 或并入 AGENTS.md 写入铁律指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-14-etf-monitor-members.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-14-factor-purpose-admission.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-14-gold-timing-exhibit-freeze-bundle.md` | 2 口径裁定 | 现役黄金展厅冻结合同 | 拟改写 docs/adr/（新仓已有 2026-09-16-frozen-artifacts.md 作目录策略，本裁定正文未迁；现不迁） | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-14-research-d2-portfolio-identity.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-15-etf-xhy-one-shot-signal.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-15-reports-prefixed-backtest-payload-ignore.md` | 5 已取代 | 同上，reports 后缀长表 ignore；新仓 var/ 已覆盖 | 不迁移，清单记一行 | 不迁 |
| `docs/decisions/2026-09-17-etf-baseline-daily-continuation.md` | 2 口径裁定 | 冻结 performanceSeries 不重算；只追加冻结末日之后 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-17-macro-website-daily-performance.md` | 2 口径裁定 | docs/decisions/README.md 仍列为现行裁定，且未被后继文档标取代；旧仓现役模块按此执行 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/2026-09-17-stock-factor-group-nav-date-axis.md` | 2 口径裁定 | canonical oo_5d 横轴用 source_end_date | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 本清单不启动迁入；P5 才执行第一、二、三类 |
| `docs/decisions/README.md` | 4 过程记录 | 旧仓现行裁定索引与「已知会误导」表，属导航/台账 | 不迁移，旧仓追溯 | 新仓入口是 docs/README.md。误导表内的 TASK/DESIGN 正文在 docs/TASKS 等过程目录 |
| `docs/ADR/ADR-0074-pf-nap-valid-ratio-08-policy.md` | 2 口径裁定 | decisions/README 点名仍支撑现役代码：nap_adj_ratio observed-domain valid-ratio 8% | 拟改写 docs/domain/ 或 docs/adr/（因子口径）；现不迁 | 新仓 observed domain 铁律与此同族 |
| `docs/ADR/ADR-0075-pf-nap-finite-first-report-keyed-revision.md` | 2 口径裁定 | 仍支撑现役：先过滤有限值再 report-year keyed 去重 | 拟改写 docs/domain/ 或 docs/adr/；现不迁 | 部分取代 ADR-0073，不得手工抬升口径 |
| `docs/ADR/ADR-0072-pf-nap-observed-domain-max-id-revision-selector.md` | 2 口径裁定 | 并列最大 id fail-closed 选择器，现役 PF nap 内核仍执行 | 拟改写 docs/domain/ 或 docs/adr/；现不迁 | 与新仓 fail-closed 铁律同族 |
| `docs/ADR/ADR-0077-pf-nap-canonical-kernel-immutable-legacy-replay.md` | 2 口径裁定 | canonical kernel 不可变、legacy replay 分身份；不改 0074/0075 语义 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | golden/replay 迁移时必须保持 identity 隔离 |
| `docs/ADR/ADR-0015-legacy-db-access-freeze.md` | 2 口径裁定 | 禁止业务模块直连数据库；旧仓仍有违规，新仓分层铁律继承此方向 | 拟并入 docs/architecture/ports-and-adapters.md 指针即可，不搬原文；现不迁 | 新仓 import-linter 已覆盖方向，正文不照搬 |
| `docs/ADR/ADR-0001-secrets-out-of-repo.md` | 2 口径裁定 | 凭据出库，现役与新仓 pre-commit 仍执行 | 新仓已有实践，不必搬原文；现不迁 | 不把旧 ADR 编号体系带进来 |
| `docs/ADR/ADR-0025-strategy-return-profile-and-adjusted-price-proxy.md` | 2 口径裁定 | 策略收益轮廓与复权代理，现役 continuation 仍引用 | 拟改写 docs/domain/ 或 docs/adr/；现不迁 | 回测合同落地时对拍，不静默改口径 |
| `docs/ADR/ADR-0011-factor-json-multi-universe-contract.md` | 2 口径裁定 | website 多 universe 分片合同仍被 outputs/factors/*.json 与 loader 执行 | 拟改写 docs/contracts/ 发布 schema；现不迁 | 产物本身可重算，合同要改写 |
| `docs/ADR/ADR-0009-macro-regime-canonical-and-contract.md` | 2 口径裁定 | 宏观状态 canonical 合同仍约束 website macro_regime.json | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 与 2026-08-26-macro-regime-website-data-contract.md 一并改写 |
| `docs/ADR/ADR-0016-macro-tilt-soft-prior-and-no-hard-sign-policy.md` | 2 口径裁定 | 宏观 tilt 软先验、禁止硬符号，现役 southwest/v5 仍按此 | 拟改写 docs/adr/，保留原结论与日期并附旧仓指针；现不迁 | 不迁原文编号 |
| `docs/ADR/ADR-0073-pf-nap-report-year-keyed-revision-policy.md` | 5 已取代 | 已被 ADR-0075 部分取代：有限值过滤顺序已改 | 不迁移，清单记一行 | 历史推理链留旧仓；新仓只改写 0075 |
| `docs/ADR/research-pdf-family/` | 5 已取代 | ADR-0031/0038–0045/0047/0048/0052/0055 共 13 份，约束 .codex research-pdf 资格流水，新仓无对应模块 | 不迁移，清单记一行 | 与新仓研究发布边界（researchOnly JSON）不是同一条链路，不迁 |
| `docs/ADR/strategy-continuation-parity-family/` | 5 已取代 | ADR-0023/0026/0053/0056/0058–0069 等 Gate/授权/sentinel/parity 流水；新仓明确删除「向自己出示批准」 | 不迁移，清单记一行 | 旧仓封存前仍按其执行，但不改写进新仓 adr。文件约 20 份 |
| `docs/ADR/remaining-numbered/` | 3 有效知识 | 其余编号 ADR（0002 网关、0003 引擎映射、0010 双层因子、0014 依赖方向、0017 双通道发布、0018 JDBC、0004–0008、0012 编号、0030 证据向量、0036 治理合并等） | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 有用口径已由新仓 architecture/adr 重写；JDBC/编号/CI 脚手架与新仓冲突。约 22 份，不逐份照搬 |
| `docs/bond_timing/` | 3 有效知识 | 研究线入口与运行说明，含冻结 bundle 操作；15 份 md | 拟提炼 docs/research/bond-timing.md；README 中的现役命令改写入 runbook；现不迁 | 口径以 decisions 为准，本目录不照搬 |
| `docs/gold_timing/` | 3 有效知识 | 黄金研究线入口；6 份 md / 15 文件 | 拟提炼 docs/research/gold-timing.md；现不迁 | 七票 PIT 以 decisions 为准 |
| `docs/multi_asset/` | 3 有效知识 | 多资产研究线入口；7 份 md | 拟提炼 docs/research/multi-asset.md；现不迁 | Core5 生产指针以 decisions 为准 |
| `docs/style_rotation/` | 3 有效知识 | 风格轮动研究线入口；17 份 md | 拟提炼 docs/research/style-rotation.md；现不迁 | 展厅冻结以 decisions 为准；行业 Phase 文档见上列 C3 裁定 |
| `docs/macro_regime/` | 3 有效知识 | 宏观状态研究说明；17 份 md | 拟提炼 docs/research/macro-regime.md；现不迁 | 西南范围与月末决策以 decisions 为准 |
| `docs/alpha_factory/` | 3 有效知识 | Alpha Factory 研究线入口与 C 规格等；6 份 md | 拟提炼 docs/research/alpha-factory.md；现不迁 | 旧 Gate/continuation 不迁 |
| `docs/etf/` | 3 有效知识 | ETF 目录入口 1 份 md | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | 因子用途与冻结以 decisions 为准 |
| `docs/website/` | 3 有效知识 | 网站数据合同说明；4 份 md | 拟提炼进 docs/architecture 或 apps/web 迁移笔记；现不迁 | P5 前端迁移时对照，不照搬 |
| `docs/data_registry_guide.md` | 3 有效知识 | data_registry 目录约定，解释为何 389M 入库 | 拟改写 frozen/README 与 publish 边界说明；现不迁 | 新仓已用 frozen/publish/var 三分，不搬旧指南 |
| `docs/RUNBOOK/website-data-release-chain.md` | 3 有效知识 | 现役展厅刷新链：各 freeze bundle -> overlay -> website；新仓文档已引用其结构 | 拟改写 docs/runbook/ 发布链；现不迁 | 是有效操作知识，重写命令与路径 |
| `docs/DESIGN/` | 3 有效知识 | 现役目录残留 30 份 md / 35 文件；有引擎、PF、宏观、ETF、因子目录等设计 | 拟提炼进 docs/research/ 或 docs/domain/，重写而非照搬；现不迁 | DESIGN-0008 group_id 反转已被 stock-factor-group-id-lowest-first 取代，见第五类。其余重写进 architecture，不照搬编号 |
| `docs/infrastructure/` | 3 有效知识 | 基建说明 4 文件 | 有用部分已由新仓工程基建覆盖；现不迁 | Python 3.8/JDBC 内容与新仓 3.12 冲突，冲突段归第五类阅读时忽略 |
| `docs/legacy/` | 4 过程记录 | 已归档编号文档 1270 文件 / 1263 份 md（含 legacy/decisions 5 份） | 不迁移，旧仓追溯 | 归档裁定要求不进默认导航。本 commit 文件数 |
| `docs/TASKS/` | 4 过程记录 | TASK 正文 339 份 md，流程与验收痕迹 | 不迁移，旧仓追溯 | 去编号后不迁 |
| `docs/REVIEW/` | 4 过程记录 | REVIEW 665 文件 / 626 份 md | 不迁移，旧仓追溯 | 不迁 |
| `docs/ARCH_REVIEW/` | 4 过程记录 | AR 208 份 md | 不迁移，旧仓追溯 | 不迁 |
| `docs/ARCH_CONCERNS/` | 4 过程记录 | ARCH_CONCERN 76 文件 / 74 份 md | 不迁移，旧仓追溯 | 新仓不设 ARCH_CONCERN 升级链 |
| `docs/EVIDENCE/` | 4 过程记录 | 过程证据 57 文件 / 12 份 md | 不迁移，旧仓追溯 | 不迁 |
| `docs/PRD/` | 4 过程记录 | PRD 4 份，新仓默认不写 PRD | 不迁移，旧仓追溯 | 不迁 |
| `docs/ARCHIVE/` | 4 过程记录 | 治理 MANIFEST 等编号台账残留 1 文件 | 不迁移，旧仓追溯 | 与 DOC_NUMBER_RESERVATIONS 同类 |
| `docs/DOC_NUMBER_RESERVATIONS.json` | 4 过程记录 | 编号预留台账约 434KB，新仓明确取消 allocator | 不迁移，旧仓追溯 | 不迁 |
| `docs/RUNBOOK/` | 4 过程记录 | 除 website-data-release-chain 外的 108 份操作手册，多数绑定 TASK 编号与旧调度 | 不迁移，旧仓追溯 | 有效步骤在 P5 按研究线重写 runbook，不搬 108 份 |
| `docs/STATUS.md` | 4 过程记录 | 旧仓四个并行入口之一 | 不迁移，旧仓追溯 | 新仓唯一入口 docs/README.md |
| `docs/DOCUMENTATION_GUIDE.md` | 4 过程记录 | 旧文档类型与分支维护指南 | 不迁移，旧仓追溯 | 新仓见 docs/CONVENTIONS.md |
| `docs/README.md` | 4 过程记录 | 旧仓文档入口，与 STATUS/decisions/legacy 并行 | 不迁移，旧仓追溯 | 不迁 |
| `outputs/task_0021_parity/` | 4 过程记录 | 一次性对拍产物 6 文件，无现役发布读取 | 不迁移，旧仓追溯 | 可重算调试输出 |
| `outputs/task_0024_stock_hq_score_parity/` | 4 过程记录 | 一次性对拍 3 文件 | 不迁移，旧仓追溯 | 不迁 |
| `outputs/task_0068_factor_testing_parity/` | 4 过程记录 | 一次性对拍 15 文件 | 不迁移，旧仓追溯 | 不迁 |
| `outputs/task_0070_factor_research_profile/` | 4 过程记录 | 一次性研究 profile 18 文件 | 不迁移，旧仓追溯 | 不迁 |
| `data_registry/strategies/_result_store/` | 4 过程记录 | 策略 continuation 结果仓 132 文件，含 21MB positions.csv；属运行态而非冻结输入 | 不迁移，旧仓追溯 | 新仓不把可重算回测仓位入 git。旧调度仍读写直至封存 |
| `data_registry/strategies/_release_receipts/` | 4 过程记录 | TASK 发布收据 4 文件 | 不迁移，旧仓追溯 | 不迁 |
| `data_registry/strategies/_publication_seeds/` | 4 过程记录 | publication seeds 30 文件，Gate 流水输入 | 不迁移，旧仓追溯 | 新仓取消 Gate |
| `reports/task-family/` | 4 过程记录 | reports 下 task0335/task0396 及 strategy_continuation/TASK-* 等过程收据；gitignore 有 121 条 reports 例外 | 不迁移，旧仓追溯 | 与宏风险 295 文件中的 task0295+ 合同包同类。不逐文件 |
| `docs/data_dictionary/` | 5 已取代 | 318+ 张表 markdown 字典，无法阻止实现漂移；新仓改可执行契约 | 不迁移，清单记一行 | 325 文件 / 319 md。供应商文件夹不能当采集依据，已在 wx2 清单纠正 |
| `docs/create_sql-family/` | 5 已取代 | docs/create_*.sql 及风格表 DDL 散落文档目录，新仓 DDL 在 db/migrations/ | 不迁移，清单记一行 | 约 16 个 sql/md 入口文件，不迁入 docs/ |
| `docs/DESIGN/DESIGN-0008-factor-research-publish-pipeline.md` | 5 已取代 | 已知会误导：group_id=1=Top 且发布层反转，与现役 lowest-first 冲突 | 不迁移，清单记一行 | 以 2026-08-23-stock-factor-group-id-lowest-first.md 为准 |
| `docs/legacy/decisions/` | 5 已取代 | 已归档旧合同 5 份，含 factor-materializer-minimal-gate、large-small-core-confidence 等 | 不迁移，清单记一行 | README 误导表已指向其中若干 |
| `docs/decisions/README.md#known-misleading` | 5 已取代 | 「已知会误导人的历史文档」12 行：TASK-0688/DESIGN-0031 授权旗标、DESIGN-0029 禁曲线、h00985 vs 000985、Vercel Blob 拉包等 | 不迁移，清单记一行 | 各过时合同正文在 TASKS/DESIGN/legacy，此处记索引行避免三个月后重踩 |
| `reports/macro_risk/market_data/a_share_broad_total_return_daily.csv` | 5 已取代 | 现役：macro_regime/a_share_broad_market_data.py 默认读取；但可从行情源重算，且 website 刷新走 data_registry/macro_regime.json 而非此 CSV | 不迁移，清单记一行 | git 跟踪是旧 ignore 例外。若 P5 发现西南网站链路仍依赖再改判类别 1 |
| `reports/macro_risk/market_data/aa_aaa_relative_net_price_pressure.csv` | 5 已取代 | 现役：macro_regime/macro_curve_inputs.py 默认读取；研究回测脚本依赖；可从曲线源重算 | 不迁移，清单记一行 | 网站日更 job 不读此文件 |
| `reports/macro_risk/market_data/cgb10y_growth_value_fwd1m.csv` | 5 已取代 | 现役：macro_curve_inputs.py CGB10Y_SNAPSHOT_REL | 不迁移，清单记一行 | 同族可重算快照 |
| `reports/macro_risk/market_data/r007_funding_stress_fwd1m.csv` | 5 已取代 | 现役：macro_curve_inputs.py R007_SNAPSHOT_REL | 不迁移，清单记一行 | 同族可重算快照 |
| `reports/style_rotation/growth_value/final_research/` | 5 已取代 | freeze_bundle 构建脚本曾从此打包；日增 overlay 已改为只读 outputs/style_rotation_exhibit_freeze | 不迁移，清单记一行 | 无现役日更消费者。158 份 style_rotation reports 多数同类 |
| `reports/style_rotation/large_small/phase_e_final_validation/` | 5 已取代 | 同上，历史研究目录，展厅不再直读 | 不迁移，清单记一行 | 身份已进入 style_rotation_exhibit_freeze |
| `reports/remaining/` | 5 已取代 | 其余 git 跟踪 reports（macro_style 307、alpha_factory_governance 169、macro_risk 其余、multi_asset 108 等），合计约 1500 文件，可重算或一次性调试 | 不迁移，清单记一行 | 旧仓 reports 工作树约 1.3G。新规则：能重算的不入库 |
| `outputs/bond_timing/` | 5 已取代 | 现役 jobs 写出 overlay JSON（manifest/snapshot/nav/signals）；由冻结 bundle + 日增重放生成，可重算 | 拟由新仓 publish/ 装配，不进 frozen/；现不迁 | 与冻结目录严格分开 |
| `outputs/gold_timing/` | 5 已取代 | 现役黄金 overlay JSON，可重算 | 拟 publish/；现不迁 | jobs gold_timing_exhibit_refresh_publish 输出 |
| `outputs/multi_asset/` | 5 已取代 | 现役 Core5 overlay JSON，可重算 | 拟 publish/；现不迁 | jobs 输出 |
| `outputs/macro_regime.json` | 5 已取代 | 现役 jobs macro_regime_website_refresh_publish 与 website 读取；由 registry 装配，可重算 | 拟 publish/macro_regime.json；现不迁 | 输入侧见 data_registry/macro_regime.json |
| `data_registry/macro_regime.json` | 5 已取代 | 现役 publish_macro_regime_website_data / build_website_outputs 读取；可从宏观研究链路重算 | 拟 publish 装配输入改走 var/ 或运行时生成；现不迁 | 体积约 210KB，不是不可重算冻结前缀 |
| `outputs/etf_factor_index.json` | 5 已取代 | 现役 website/lib/data/etf-factor-sharding.ts 读取；由 website freeze + 日增装配，可重算 | 拟 publish/；现不迁 | 不要与 etf_factor_website_freeze 混淆 |
| `outputs/etf_factors/` | 5 已取代 | 现役 ETF 分片 JSON 10 文件，可重算 | 拟 publish/；现不迁 | website 读模型约束见 ADR-0011 同类合同 |
| `outputs/factor_index.json` | 5 已取代 | 现役股票因子网站分片索引，可重算；禁止回退 outputs/factor.json | 拟 publish/；现不迁 | factor.json 已退役 |
| `outputs/factors/` | 5 已取代 | 现役 all_a/did/growth 分片 3 文件，可重算 | 拟 publish/；现不迁 | website loader 读取 |
| `data_registry/factors/alpha_factory.json` | 5 已取代 | 现役 alpha_factory_daily_refresh 与 numeric delta 读取；由 DB metric 投影，可重算。约 3.3MB | 拟 var/ 或 publish 小 JSON；现不迁 | 入 git 是旧体积问题的一部分 |
| `data_registry/factors/etf_factor_daily_refresh/availability_cache.json` | 5 已取代 | 现役增量刷新读写的可用性缓存，可重建 | 不迁移，清单记一行 | 与同目录冻结身份分离，不进 frozen/ |
| `data_registry/factors/universes.json` | 5 已取代 | website_numeric_delta 引用；可从 universe 契约重算 | 不迁移，清单记一行 | 新仓 mart.universe_member |
| `data_registry/factors/style_timing.json` | 5 已取代 | 可重算注册表 | 不迁移，清单记一行 | 不迁 |
| `data_registry/factors/performance_factor_singles.did.registry.json` | 5 已取代 | numeric delta 引用的 did registry，可重算 | 不迁移，清单记一行 | 另有 growth registry 同族 |
| `data_registry/factors/performance_factor_singles.growth.registry.json` | 5 已取代 | growth registry，可重算 | 不迁移，清单记一行 | 不迁 |
| `outputs/style_rotation_growth_value_exhibit.json` | 5 已取代 | 现役展厅 JSON，由 freeze+overlay 装配，可重算 | 拟 publish/；现不迁 | 冻结输入在 style_rotation_exhibit_freeze |
| `outputs/style_rotation_large_small_exhibit.json` | 5 已取代 | 现役大小盘展厅 JSON，可重算 | 拟 publish/；现不迁 | 同族 |
| `outputs/style_rotation.json` | 5 已取代 | 可重算发布 JSON | 拟 publish/；现不迁 | 动态频道见 style-rotation-dynamic-only 裁定 |
| `outputs/style_rotation_research_dashboard.json` | 5 已取代 | 研究 dashboard JSON，可重算 | 拟 publish/ 或丢弃；现不迁 | 行业监控已归档 |
| `outputs/remaining-publish-json/` | 5 已取代 | outputs 下 agent/portfolio/strategy/research/portfolio_os/observation_monitor 及 overlay_run 收据、smoke csv 等可重算或一次性 | 不迁移，清单记一行 | website 可能读取其中若干，P5 按 loader 重装，不把 JSON 当 frozen |
| `data_registry/remaining/` | 5 已取代 | agents/research/portfolio/style_rotation 监控 JSON、strategies/_index 与各策略卡片、bond/gold/multi_asset overlay 副本等，可重算或网站静态 | 不迁移，清单记一行 | 254 跟踪文件中冻结项已单列。体积问题的主因 _result_store 见第四类 |
| `website/public/research/` | 5 已取代 | 哈希文件名的展厅静态 JSON，由发布链生成，可重算 | 拟 apps/web 构建产物，不入 frozen/；现不迁 | P5 移植 website 时重建 |
| `docs/a_share_style_rotation.md` | 5 已取代 | 根级旧设计文，已被 style_rotation 研究线与后继裁定覆盖 | 不迁移，清单记一行 | 同族 a_share_enhanced_500_risk_budget.md、a_share_alpha_factory_style_timing_design.md |
