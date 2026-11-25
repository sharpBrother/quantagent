---
title: 决策记录索引
status: active
created: 2026-09-16
updated: 2026-11-21
applies_to:
  - docs/adr/
---

# 决策记录（ADR）

## 规则

- 文件名：`YYYY-MM-DD-slug.md`，不使用编号
- **只增不改**。正文一经提交不改写
- 被新决策取代时：新文档写 `supersedes`，旧文档改 `status: superseded` 并写
  `superseded_by`，**正文保持原样**
- 与 `architecture/` 的分工：ADR 记录「当初为什么这么选」，活文档描述
  「现在是什么样」。前者不改写，后者持续改写

## 固定结构

1. **背景** — 当时面临的情况与约束
2. **决策** — 选了什么
3. **理由** — 为什么
4. **被否方案** — 考虑过但没选的，以及为什么没选
5. **代价** — 这个选择放弃了什么、以后可能后悔在哪
6. **推论** — 由这个决策直接导出的其他约束

第四和第五部分是 ADR 的核心价值。只写"选了什么、为什么好"的记录无法防止
后来的人重新提出已被否掉的方案。

## P0 初始决策

| 日期 | 决策 |
|---|---|
| 2026-09-16 | [存储选型：PostgreSQL + Parquet + DuckDB](2026-09-16-storage-selection.md) |
| 2026-09-16 | [PostgreSQL 分为研究数据面与控制状态面](2026-09-16-pg-two-planes.md) |
| 2026-09-16 | [源镜像层不做版本留存](2026-09-16-no-source-vintage-in-pg.md)（已被取代） |
| 2026-09-16 | [PIT 由声明式规则定义，不由字段约定](2026-09-16-rule-based-pit.md) |
| 2026-09-16 | [因子统一为长表存储](2026-09-16-feature-long-table.md) |
| 2026-09-16 | [因子身份拆分为三段](2026-09-16-feature-identity-triplet.md) |
| 2026-09-16 | [不可重算历史制品的冻结策略](2026-09-16-frozen-artifacts.md) |
| 2026-09-16 | [回测语义合同先行，内核按场景分设](2026-09-16-backtest-contract-first.md) |
| 2026-09-16 | [选择 Dagster 作资产化编排](2026-09-16-dagster-orchestration.md) |
| 2026-09-16 | [Python 3.12 作为唯一基线](2026-09-16-python-312-baseline.md) |
| 2026-09-16 | [文档体系去编号化](2026-09-16-docs-without-numbering.md) |
| 2026-09-17 | [因子配套派生数据集的层归属](2026-09-17-derived-dataset-boundaries.md) |
| 2026-09-17 | [因子长表 Parquet 物理布局](2026-09-17-feature-value-parquet-layout.md) |
| 2026-09-17 | [源数据不做批次 vintage 归档](2026-09-17-no-source-vintage-archive.md) |
| 2026-11-17 | [Wind 源镜像修订自动跟随](2026-11-17-wind-revision-auto-replace.md)（已被取代） |
| 2026-11-17 | [Wind 源镜像全自动跟随源端](2026-11-17-src-mirror-follows-source.md) |
| 2026-11-17 | [股票池按读取时计算，不物化](2026-11-17-universe-computed-on-read.md) |
| 2026-11-17 | [ST 状态按左闭右开区间判断](2026-11-17-st-status-half-open.md) |
| 2026-11-17 | [执行机上的 Dagster 运行存储改用本地 SQLite](2026-11-17-dagster-local-run-storage.md) |
| 2026-11-18 | [Tushare 源镜像同样全自动跟随源端](2026-11-18-tushare-mirror-follows-source.md) |
| 2026-11-23 | [聚源与朝阳永续源镜像同样跟随源端修订](2026-11-23-jydb-suntime-mirror-follows-source.md) |
| 2026-11-18 | [源端发布的版本可以落表，与采集批次 vintage 不同](2026-11-18-source-published-versions.md) |
| 2026-11-18 | [GPR 日频采集的版本比较与数值口径](2026-11-18-gpr-daily-ingest.md) |
| 2026-11-23 | [FRED 的 OECD 德债、日债收益率超精度值按 8 位小数量化](2026-11-23-fred-oecd-yield-rounding.md) |
| 2026-11-21 | [A 股 1 分钟行情以 Parquet 作源镜像，不进 PostgreSQL](2026-11-21-minute-bars-in-parquet.md)（实施中） |
| 2026-11-21 | [分钟行情历史与日更来源](2026-11-21-minute-bars-source-split.md) |
| 2026-11-21 | [2025-10-28 分钟行情单条负值修正](2026-11-21-minute-bar-negative-correction.md) |
| 2026-11-21 | [2025-11-26 分钟行情单条负成交额修正](2026-11-21-minute-bar-november-negative-correction.md) |
| 2026-11-22 | [2025-12-08 分钟行情单条负成交额修正](2026-11-22-minute-bar-december-negative-correction.md) |
| 2026-11-22 | [2025-12-11 分钟行情单条负成交额修正](2026-11-22-minute-bar-december-11-correction.md) |
| 2026-11-22 | [2025-12-29 分钟行情单条负成交额修正](2026-11-22-minute-bar-december-29-correction.md) |
| 2026-11-22 | [分钟行情少量负成交额处理](2026-11-22-minute-bar-limited-negative-amounts.md) |
| 2026-11-22 | [2025-10-17 分钟行情 45 条负成交额修正](2026-11-22-minute-bar-october-17-correction.md) |
| 2026-11-22 | [2026-01-13 分钟行情 75 条负成交额修正](2026-11-22-minute-bar-january-13-correction.md) |
| 2026-11-22 | [2026-01-21 分钟行情排除 67 只股票](2026-11-22-minute-bar-january-21-exclusions.md) |
| 2026-11-22 | [分钟行情负成交额按日行情差异处理](2026-11-22-minute-bar-negative-amount-daily-check.md) |
| 2026-11-22 | [2026-01-22 分钟行情单条负成交量和成交额修正](2026-11-22-minute-bar-january-22-correction.md) |
| 2026-11-22 | [2026-03-26 分钟行情单条负成交量和成交额修正](2026-11-22-minute-bar-march-26-correction.md) |
| 2026-11-23 | [2026-04-16 分钟行情单条负成交量和成交额修正](2026-11-23-minute-bar-april-16-correction.md) |
| 2026-11-23 | [2026-04-30 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-april-30-correction.md) |
| 2026-11-23 | [2026-06-02 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-june-02-correction.md) |
| 2026-11-23 | [2026-06-08 分钟行情单条负成交量和成交额修正](2026-11-23-minute-bar-june-08-correction.md) |
| 2026-11-23 | [2026-06-22 分钟行情单条负成交量和成交额修正](2026-11-23-minute-bar-june-22-correction.md) |
| 2026-11-23 | [2026-06-29 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-june-29-correction.md) |
| 2026-11-23 | [2026-07-06 分钟行情两条成交量和成交额修正](2026-11-23-minute-bar-july-06-correction.md) |
| 2026-11-23 | [2026-07-08 分钟行情单条负成交量和成交额修正](2026-11-23-minute-bar-july-08-correction.md) |
| 2026-11-23 | [2026-07-09 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-july-09-correction.md) |
| 2026-11-23 | [2026-07-14 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-july-14-correction.md) |
| 2026-11-23 | [2026-07-15 分钟行情两条成交量和成交额修正](2026-11-23-minute-bar-july-15-correction.md) |
| 2026-11-23 | [2026-07-17 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-july-17-correction.md) |
| 2026-11-23 | [2026-07-22 分钟行情两条成交量和成交额修正](2026-11-23-minute-bar-july-22-correction.md) |
| 2026-11-23 | [2026-07-24 分钟行情单条负成交量和成交额修正](2026-11-23-minute-bar-july-24-correction.md) |
| 2026-11-23 | [2026-07-28 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-july-28-correction.md) |
| 2026-11-23 | [2026-08-04 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-august-04-correction.md) |
| 2026-11-23 | [2026-08-17 分钟行情两条成交量和成交额修正](2026-11-23-minute-bar-august-17-correction.md) |
| 2026-11-23 | [2026-08-20 分钟行情两条成交量和成交额修正](2026-11-23-minute-bar-august-20-correction.md) |
| 2026-11-23 | [2026-08-24 分钟行情三条成交量和成交额修正](2026-11-23-minute-bar-august-24-correction.md) |
| 2026-11-23 | [2026-09-10 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-september-10-correction.md) |
| 2026-11-23 | [2026-09-15 分钟行情三条成交量和成交额修正](2026-11-23-minute-bar-september-15-correction.md) |
| 2026-11-23 | [2026-09-17 分钟行情单条负成交量和成交额修正](2026-11-23-minute-bar-september-17-correction.md) |
| 2026-11-23 | [2026-09-28 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-september-28-correction.md) |
| 2026-11-23 | [2026-09-30 分钟行情两条负成交量修正](2026-11-23-minute-bar-september-30-correction.md) |
| 2026-11-23 | [2026-10-08 分钟行情三条负成交量和成交额修正](2026-11-23-minute-bar-october-08-correction.md) |
| 2026-11-23 | [2026-10-12 分钟行情两条成交量和成交额修正](2026-11-23-minute-bar-october-12-correction.md) |
| 2026-11-23 | [2026-10-13 分钟行情两条负成交量修正](2026-11-23-minute-bar-october-13-correction.md) |
| 2026-11-23 | [2026-10-14 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-october-14-correction.md) |
| 2026-11-23 | [2026-10-19 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-october-19-correction.md) |
| 2026-11-23 | [2026-10-21 分钟行情两条成交量和成交额修正](2026-11-23-minute-bar-october-21-correction.md) |
| 2026-11-23 | [2026-10-22 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-october-22-correction.md) |
| 2026-11-23 | [2026-10-27 分钟行情三条负成交量和成交额修正](2026-11-23-minute-bar-october-27-correction.md) |
| 2026-11-23 | [2026-10-29 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-october-29-correction.md) |
| 2026-11-23 | [2026-11-03 分钟行情两条负成交量修正](2026-11-23-minute-bar-november-03-correction.md) |
| 2026-11-23 | [2026-11-11 分钟行情单条负成交量和成交额修正](2026-11-23-minute-bar-november-11-correction.md) |
| 2026-11-23 | [2026-11-18 分钟行情单条成交量和成交额修正](2026-11-23-minute-bar-november-18-correction.md) |

## 研究口径决策

| 日期 | 决策 |
|---|---|
| 2026-09-19 | [因子多周期检验与三层准入](2026-09-19-factor-horizons-and-admission.md)（已裁定，待实现） |
| 2026-11-22 | [cutamp 复现旧仓 quicksort 并列顺序，定义版本 v2](2026-11-22-cutamp-legacy-quicksort-order.md) |
| 2026-11-23 | [货币供应 ED_MoneySupply 可见日：InfoPublDate 优先，空则期末次月 15 日](2026-11-23-ed-moneysupply-visibility.md)（已被取代） |
| 2026-11-23 | [聚源可见性：发布当天可见；货币供应取发布日与次月 15 日中较早者](2026-11-23-jydb-visibility.md) |
| 2026-11-23 | [美国与境外市场日频数据次日可见](2026-11-23-overseas-daily-next-day.md) |
| 2026-11-24 | [朝阳永续接入范围与一致预期可见性](2026-11-24-suntime-visibility.md) |
| 2026-11-22 | [中信一级行业成分改用 AINDEXMEMBERSCITICSZL](2026-11-22-citics-l1-members-zl.md) |
| 2026-11-22 | [股票前瞻收益按 open-to-open 落 mart，端点停牌不落行](2026-11-22-forward-return-open2open.md) |
| 2026-11-24 | [tr_umr 升 v2，窗口内缺输入不产值](2026-11-24-tr-umr-v2-no-missing-as-zero.md) |
| 2026-11-24 | [第一批四个分钟因子：无定义记缺失、排除日无日值、只在 all_a 内产出](2026-11-24-minute-factors-first-batch.md) |
| 2026-11-24 | [资金流因子 2a：abso_umr、moneyflowh、actlargemedcut](2026-11-24-moneyflow-factors-batch-2a.md) |
| 2026-11-24 | [第二批分钟因子：pxret21 截面中性化（存残差）、排序的堆排序兜底](2026-11-24-minute-factors-batch-2b.md) |
| 2026-11-24 | [MIF 迁移：night_ratio 按 4 位舍入自算，换手走衍生指标窄端口，长表存 -corr](2026-11-24-mif.md) |
| 2026-11-25 | [稳健股息率 did_ratio_realized_1：A/B/C 裁定、股票域、可复现区间与源端漏行](2026-11-25-did-ratio.md) |
