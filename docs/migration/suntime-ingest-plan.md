---
title: 朝阳永续（Suntime）源镜像接入交接
status: active
created: 2026-11-24
updated: 2026-11-24
applies_to:
  - src/quantagent/ingest/sources/suntime/
  - db/migrations/src/
  - src/quantagent/contracts/visibility/
  - docs/domain/pit-rules.md
supersedes: null
superseded_by: null
---

# 朝阳永续（Suntime）源镜像接入交接

本文给接手同步的 agent。先读 `AGENTS.md`、`docs/architecture/layers/ingest.md`、
`docs/domain/pit-rules.md`、[聚源交接文档](jydb-ingest-plan.md)，再按本文做。
聚源 P0/P1 已经接入（提交 `201eac3`），朝阳永续照它的结构做，不另造一套。
数字来自 wx2（旧仓镜像）2026-11-24 的只读查询。

## 目标

- 把下表 P0、P1 的朝阳永续表接成 `src_suntime` 源镜像：首次全量回填，加上每日增量。
  有可见性规则的表配好契约，并与 wx2 对拍通过。
- P2 在 P0、P1 验收后再做，规则相同。

不做：

- 研究侧读取（指数层一致预期的聚合、`ConsensusRepository` 之类的端口），由研究线另做。
- 本文"不同步"一节列出的表。
- `con_forecast_stk_ttm`，见"不同步"。

## 旧仓怎么同步

- **脚本：** `pycharm_workspace/data/zyyx_to_sql.py`，每天 22:00、02:00、04:30 各跑一次，
  超时 90 分钟（`task_scheduler/jobs.json`）。
- **源库：** 配置节 `[zyyx]`，SQL Server，数据库 `suntime_db`，只读账号。
  主机在公司内网，和 Wind、聚源都不是同一台。旧仓注释说源库读取普遍较慢，所以先同步小表，再同步大表。
- **镜像方式：** 整表全量镜像，所有列、所有行。目标主键是源端 `id`（`FIN_APPO_RELE_DATE` 是大写 `ID`）。
- **游标：** 历史初始化和增量都用 `(tmstamp, id)` 复合游标分页：
  `tmstamp > last OR (tmstamp = last AND id > last_id)`。每页 1000 行，按 id 先删后插。
  源端改过的行会被覆盖，源端物理删除的行不会同步。和聚源的 `(JSID, ID)` 是同一个模式。
- **中文字段编码：** 旧仓对 `stock_name`、`title`、`organ_name` 等中文列做
  `x.encode('latin1').decode('gbk')` 再解码。2026-11-24 源库核对：用 pymssql `charset="utf8"`
  直接读出就是正确中文，不需要旧仓那套再解码。解码失败要报错停下，不要像旧仓那样置 None。

## 需求表与优先级

| 优先级 | 表 | 用途（旧仓消费者） | wx2 行数 / 大小 | 覆盖 | 建表 | 可见性 |
|---|---|---|---|---|---|---|
| P0 | `con_forecast_stk` | 个股一致预期（年度）；研究线估值陷阱检验要用，旧仓 `agent_style_rotation`、`alpha_factory`、`core/raw_loader` | 69,642,855 / 28.9 GB | 2006-01 – 2026-11 | 0006 已建，PK `id` | `source_field con_date`，A |
| P0 | `con_forecast_roll_stk` | 个股滚动 12 个月一致预期；同上 | 17,410,992 / 4.0 GB | 2006-01 – 2026-11 | 0006 已建，PK `id` | 同上 |
| P0 | `con_forecast_idx` | 指数一致预期（年度）；研究线宽基指数直接用 | 511,532 / 165 MB | 2006-01 – 2026-11 | **未建**，需新迁移 | `source_field con_date`，A |
| P0 | `con_forecast_roll_idx` | 指数滚动 12 个月一致预期；研究线主用 | 127,883 / 48 MB | 2006-01 – 2026-11 | **未建**，需新迁移 | 同上 |
| P1 | `rpt_earnings_adjust` | 卖方盈利预测调整（上调、下调）；旧仓 `core/raw_loader`、`enhanced_optimizer` | 3,397,832 / 1.0 GB | 2006-01 – 2026-11 | 0006 已建，PK `id` | 只建镜像，**不写契约** |
| P2 | `FIN_APPO_RELE_DATE` | 定期报告预约披露日；旧仓 `strategy/growth_stock*.py` | 336,985 / 50 MB | — | 0006 已建，PK `ID` | `source_field DECLARE_DATE strict`（pit-rules 已钉） |
| P2 | `der_prob_excess_stock` | 可能超预期提示；旧仓 `alpha_factory` | 108,663 / 24 MB | — | 0006 已建，PK `id` | 只建镜像，**不写契约**，见下 |
| P2 | `der_diver_stk` | 个股一致预期分歧度；旧仓 `core/raw_loader`、`enhanced_optimizer` | 61,544,212 / 11.0 GB | 2009-01 – 2026-11 | 0006 已建，PK `id` | `source_field con_date`，同 P0 |

排序理由：

- P0 是研究线直接要用的。宽基指数直接读两张 `_idx` 表；中证红利 `000922` 不在指数表里，
  要用个股表按成分聚合，所以个股表也放 P0。
- P1 的调整表可以算盈利预测上调、下调的比例，也是估值陷阱检验的候选变量，量不大。
- P2 只有旧仓策略在用，新仓还没有消费者。`der_diver_stk` 很大，排在最后。

**指数层一致预期在源库里有，wx2 里没有。** 本文初稿根据 wx2 写成"不存在"，2026-11-24 源库核对后更正：
`suntime_db.con_forecast_idx` 有 511,532 行，覆盖 27 个指数，约 165 MB。
- 列与 `con_forecast_stk` 同构：`id`、`index_code`、`index_name`、`con_date`、`con_year` 加 `con_np`、`con_pe`、`con_eps` 等，
  以及 `entrytime`、`updatetime`、`tmstamp`。PK `id`，`(index_code, con_date, con_year)` 唯一，游标列没有空值。
- 含中证全指（`000985`，2011-08 起）、沪深 300、中证 500、创业板指（`399006`，2010-06 起）、
  上证红利（`000015`）。**不含中证红利 `000922`。**
- 入库时间特征与个股表相同：2022 年以前有事后回补，2023 年起当天 17 到 20 点入库。
- `con_forecast_roll_idx` 与 `con_forecast_roll_stk` 同构，每个 `(index_code, con_date)` 一行，
  127,883 行、48 MB，27 个指数、覆盖与入库特征都和 `con_forecast_idx` 相同。
  滚动 12 个月口径没有 `con_year` 年度切换带来的跳变，研究线以它为主。
- 负责人 2026-11-24 确认两张 `_idx` 表都作为 P0 接入：
  - 新迁移建表，列名、类型以源端为准，PK `id`，加 `(tmstamp, id)` 游标索引；
  - 在 `db/src_tables.yaml` 第一批登记。
- 源库里其他名字带 `idx` 的表（`der_diver_idx`、`der_con_dev_idx`、`der_const_adjust_idx`、
  `der_adjust_speed_idx`、`qt_idx_constituents`、`qt_idx_daily` 等）没有消费者，不接。

不同步：

- **`con_forecast_stk_ttm`：** 负责人 2026-11-24 决定不同步。这是旧仓的派生表，不是朝阳永续的源表。
  它没有 `tmstamp`，由 `data/wind_to_sql_am.py` 的 `con_forecast_stk_ttm()` 用 `con_forecast_stk`
  加 Wind 财报算出，按 `nd` 删后重插。以后要用就在 `features` 层用源表重算。
  它仍在 `db/src_tables.yaml` 第一批里，0006 建的空表留着，不写入、不进写入白名单，
  和 `ED_SocialFinancing` 一样处理。
- **`con_forecast_stk_fttm_wide`、`con_forecast_stk_fttm_wide_new`：** 也是旧仓派生表，不在第一批，不接。
- **第二批再评估：** `con_forecast_citic`（54,305,172 行 / 12.7 GB）、`rpt_forecast_stk`
  （4,228,605 行 / 7.4 GB）、`fin_performance_forecast`、`fin_performance_express`、
  `fin_income_gen`、`der_excess_stock`。旧仓都在同步，但不在 `src_tables.yaml` 第一批，0006 没建表。

## 写入语义（已裁定）

按 [聚源与朝阳永续源镜像跟随源端](../adr/2026-11-23-jydb-suntime-mirror-follows-source.md)：

- 新键插入。业务字段没变就跳过。业务字段有变化，就在同一事务内按主键删旧插新，计入 `replaced`。
- 源端没返回的已写行不删。
- 系统列 `entrytime`、`updatetime`、`tmstamp`（`FIN_APPO_RELE_DATE` 为大写）变化不算修订。
  每张表的系统列写进写入规格，由测试固定。
- 状态类字段算业务字段，例如 `FIN_APPO_RELE_DATE.IS_VALID`。
- 复用聚源用的 `ingest/writers/src_follow.py` 和 `ingest/jobs/jydb_paged.py` 的分页加游标模式，不另造写入层。
- 写入保护照旧：双写闸、`tables.py` 白名单、SQL 动词白名单、每页一事务、写后回读、
  事务结果不确定时停止不重试。每次运行落 run log，含 inserted、replaced、skipped 计数。

**源端确实会成批改写历史行。** 例如 `con_forecast_stk` 在 2022-10-29 改写了 2022-06 的 207,362 行，
占当月一半以上。跟随写入会把这些计入 `replaced`。首次回填之后的第一次增量如果出现大批
`replaced`，属于正常现象，在 run log 里记录即可，不要当成故障停下。

## 接入步骤

1. **连接配置。** 在 `platform/config/settings.py` 加 `suntime_mssql_*`（host、port、database、user、
   password 用 `SecretStr`、tds_version、charset），写法照 `jydb_mssql_*`，同步改 `.env.example`
   和设置测试。连接参数向负责人要，对应旧仓配置节 `[zyyx]`，只放 `.env`。
2. **运行机器。** 源库在公司内网。按 `.env.example`，`office` 档位负责写 `src_suntime`，
   和 Wind、聚源一样在公司电脑上跑。同一来源的自动采集不得在两台机器上同时启用。
3. **核对列清单。** 采集前把 0006 的列与源端 `INFORMATION_SCHEMA.COLUMNS` 逐表对一遍，不一致就停。
   wx2 与 0006 已经核对过，7 张表列名完全一致，但 wx2 不等于源端。
4. **补迁移。**
   - `(tmstamp, id)` 游标索引：0006 只有主键。照 `0028_jydb_cursor_indexes.sql` 的写法，
     给要同步的表补 `(tmstamp, id)` 索引，`FIN_APPO_RELE_DATE` 用 `("TMSTAMP", "ID")`。
     源端在 `tmstamp` 上已有索引（`idx_*_tms`）。
   - 中文列注释：照 `0029` 的做法补，可以省略。
   - 迁移禁止 ALTER、DROP，只用 CREATE。
5. **采集与回填。**
   - 代码放在 `ingest/sources/suntime/`（现在只有占位）和 `ingest/jobs/`。
   - CLI 子命令 `quantagent ingest suntime <TABLE>`，默认干跑。
   - 增量前检查源端 `tmstamp`、`id` 都没有空值，旧仓也查。
   - **全量回填直接从源库读，不经 wx2**（负责人 2026-11-24）。
   - 先用一张小表试跑，定下每页行数，把吞吐量和预计耗时写进 run log 再开始大表回填。
     `con_forecast_stk` 有 7 千万行，旧仓每页 1000 行。回填期间不要占满源库，
     旧仓的三次定时同步可能还在用它。
6. **可见性契约。** 写在 `contracts/visibility/src.suntime.*.yaml`，`doc_ref` 指向本文。
   - `con_forecast_stk`、`con_forecast_roll_stk`、`con_forecast_idx`、`con_forecast_roll_idx`、`der_diver_stk`：
     `source_field`、`field=con_date`、
     非 strict、等级 A、`pit_recoverable: true`（见 [ADR](../adr/2026-11-24-suntime-visibility.md)）。
     rationale 写明三点：`con_date` 当天收盘后可见；2018 年以前的快照是供应商事后回补的；
     源端会改写历史行，数值为当前版本。`temporal_kind` 是每日快照，按
     `docs/domain/temporal-semantics.md` 选。
   - `FIN_APPO_RELE_DATE`：`source_field`、`field=DECLARE_DATE`、`strict: true`。
     `DECLARE_DATE` 是 timestamp，确认现有 `date_only` 与 strict 的组合语义正确再写；不支持就停下来问。
   - `rpt_earnings_adjust`：只建镜像，不写契约。入库常晚于研报日期（见下），研究侧要用时再定规则。
   - `der_prob_excess_stock`：旧仓规则是 `declare_date < adj OR entrytime < adj`，两个字段取早者，严格小于。
     现有引擎只支持"主字段 + 固定延迟"的取早者，不支持两个源字段取早者。新仓也没有消费者。
     本次只建镜像、不写契约。没有契约的数据集无法参与 PIT 查询，引擎会 fail-closed，这是预期行为。
7. **对拍。** 每张表与 wx2 比较 `id` 集合与业务列。差异只允许来自源端新增，或者 wx2 残留了源端已删除的行。
   中文列要逐行比较，确认编码处理正确。
8. **编排。** 照 `orchestration/assets/jydb.py` 新建 asset、job、schedule，只在 `office` 档位注册。
   旧仓一天跑三次，新仓一天一次即可，时间避开旧仓的 22:00、02:00、04:30，并和 Wind、聚源错开。
9. **进度。** 完成后更新 `docs/migration/roadmap.md` 的"当前进度"，并更新
   `docs/migration/wx2-table-list.md` 与 `.yaml` 中这些表的状态。

## 已知的时间特征（供写契约与对拍参考）

- **`con_forecast_stk` 每一行是某只股票、某个预测年度在 `con_date` 这一天的一致预期快照。**
  2026-10 以来 892,804 行，`(stock_code, con_date, con_year)` 没有重复。每个 `con_date` 有
  4 个 `con_year`：2026-11-20 是 2025 到 2028 年，其中 2025 年是最近一期年报的实际值（`con_np_type` 为 0），
  其余年度为预测值（`con_np_type` 1 到 4 对应不同来源或加工方式）。
- **`con_date` 每天都有，包括周日。** 2026 年周日 42 天、周六 0 天。它不是交易日序列，
  对齐到交易日由研究侧处理。
- **近年的快照当天傍晚入库。** 2026-10 以来 99.9% 的行 `entrytime` 与 `con_date` 同一天，
  时间是 17、18、20 点，在 A 股收盘之后。这与 pit-rules 里"`as_of` 当天收盘后可见"的语义一致。
- **2018 年以前的历史是事后回补的。** 按每年 6 月 15 日抽样，`entrytime` 比 `con_date` 晚：
  2006 年约 4,200 天，2012 年约 1,900 天，2016 年约 450 天，2018 年起为 0 到几天。
  也就是说，2018 年以前的快照是朝阳永续后来重新计算的。
- **`rpt_earnings_adjust` 的入库明显晚于 `current_create_date`。**
  - 2026-09 以来的 4.1 万行里，当天入库的约 42%，晚 1 天的 36%，最长晚 60 天。
  - 按每年 6 月抽样，1 天内入库的比例在 2006 年为 11%，2015–2025 年为 50%–80%；
    2019、2020 年的平均延迟分别为 165 天和 68 天。

## 已裁定（负责人 2026-11-24）

见 [ADR](../adr/2026-11-24-suntime-visibility.md)：

1. `con_forecast_stk_ttm` 不同步，以后在 `features` 层重算。
2. `rpt_earnings_adjust` 只建镜像，先不写可见性契约。
3. 一致预期快照按旧仓口径：`con_date <= as_of`，等级 A，rationale 写明 2018 年以前是供应商回补。
   两张 `_idx` 表同此规则，rationale 写明 2022 年以前是回补（指数表的回补持续到 2022 年）。
4. 全量回填直接从源库读，不经 wx2。

## 遇到以下情况停下问负责人

- 源端列清单与 0006 不一致。
- 中文列解码失败，或者与 wx2 的值对不上。
- `FIN_APPO_RELE_DATE` 的 `DECLARE_DATE`（timestamp）加 strict，现有引擎表达不了。
- 源库里发现了指数层一致预期表。
- 本地行数与源端 `COUNT(*)` 对不上，而且无法用源端新增或删除解释。
