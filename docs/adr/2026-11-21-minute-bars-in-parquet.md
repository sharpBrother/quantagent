---
title: A 股 1 分钟行情以 Parquet 作源镜像，不进 PostgreSQL
status: active
created: 2026-11-21
updated: 2026-11-21
applies_to:
  - src/quantagent/ingest/
  - src/quantagent/adapters/lake/
  - src/quantagent/domain/ports/
  - src/quantagent/contracts/visibility/
  - db/migrations/src/
supersedes: null
superseded_by: null
---

# A 股 1 分钟行情以 Parquet 作源镜像，不进 PostgreSQL

## 背景

旧仓分钟因子（`factors/factor_min.py`）从一个 MySQL 库 `minprice` 取数。本机经
UURemote 隧道访问，地址 `127.0.0.1:13306`。源端结构（来自旧仓代码，待探查核实）：

- 每个交易日一张表，表名 `mYYYYMMDD`；
- 列 `ts_code, trade_time, open, high, low, close, vol, amount`，代码形如 `000001.SZ`。

规模：约 5,000 只股票 × 每日 240 根 × 3 年约 727 个交易日，约 **8.7 亿行**，
每日约 120 万行。源端可以随时重拉。

旧仓的读法是"每只股票 × 每个交易日"一条 SQL，全市场一天就是 5,000 次查询，
没有 PIT 契约，也没有落地副本。

[存储选型](2026-09-16-storage-selection.md) 规定"源镜像进 PG `src_*`"，
理由是源数据需要唯一键、事务和增量去重。那条理由针对的是体量适中、会逐行
修订的源表。分钟行情的特点不同：

| 特点 | 含义 |
|---|---|
| 体量是现有最大源表的数十倍 | 行存加主键索引约 100GB；列存加 zstd 估算 10–15GB |
| 按交易日追加，源端本身按日分表 | 天然的写入、替换和校验单位是"一天" |
| 读取是区间扫描与全截面聚合 | 典型任务是把分钟数据聚合成日频因子，几乎不点查 |
| 不需要与其他源表做关系 JOIN | 用不上 PG 的约束与索引 |

## 决策

1. **数据集** `src.minprice.ashare_minute_bar`，以 Parquet 作源镜像，不建 PG 表。
   路径 `var/lake/src/minprice/ashare_minute_bar/trade_date=YYYY-MM-DD/`。
   这是"源镜像进 PG"的唯一例外，不得据此把其他源表搬出 PG。
2. **分区清单（manifest）进 PG 研究数据面** `src_minprice`。它是"这批源数据
   来自哪里、内容 digest 是多少"的元数据，按
   [PG 双面](2026-09-16-pg-two-planes.md) 推论 1 属于 `src`，不属于 `ops`。
3. **manifest 是唯一可见性来源**。读取只读 manifest 登记的文件，不 glob 目录。
   未登记的文件对读取不可见。
4. **查询引擎** DuckDB，读取实现只在 `adapters/lake/`，业务层只依赖新 port。
5. **源端驱动** `pymysql`，加入 `sources` 依赖组，只读连接。
6. **修订跟随源端**，与 Wind、Tushare 一致
   （[Wind](2026-11-17-src-mirror-follows-source.md)、
   [Tushare](2026-11-18-tushare-mirror-follows-source.md)）。粒度是整天：
   重拉后内容 digest 变化则整天替换，计入 `replaced`。
7. **不做 `std` 物化副本**。代码统一、单位换算在读取时由 adapter 完成。
   分钟数据派生的日频因子按常规落 `feature` 层。

## 理由

**Parquet**：8.7 亿行做全截面聚合，列存加列裁剪约比行存少读一个数量级。
源端可重拉，所以 Parquet 缺少的事务保证可以用"整天重写 + manifest 原子切换"
补上，不需要关系库。

**按交易日分区**：与源端分表、日更和修订的粒度一致，一天正好一个文件。
727 个文件、每个约 15–20MB，不存在小文件问题。按月分区会让每天的增量写入
变成重写整月。

**manifest 放 PG**：分区登记需要唯一约束和原子提交。把它放在 Parquet 旁边的
JSON 里做不到原子切换，并发写时会坏。行数只有每天一行，不构成 PG 负担。

**manifest 是唯一可见性来源**：文件写入和登记分两步完成，中间崩溃会留下半成品。
只认登记过的文件，崩溃的结果就是"多一个无人引用的文件"，不会让读者看到坏数据。

**不物化 `std`**：分钟数据的标准化只有代码映射和单位换算，读取时做的成本
可以忽略。物化一份等于再存 10–15GB，换来的只是少一步投影。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| PG `src_*` 普通表 | 约 100GB；全截面扫描慢；研究仍需派生一份列存，等于存两份 |
| PG 按月声明式分区 | 解决了维护问题，没解决扫描与体积问题 |
| TimescaleDB 压缩表 | 多维护一个扩展；扫描仍慢于 DuckDB 读 Parquet；压缩块修订麻烦 |
| ClickHouse | 多一个常驻服务；不到 10 亿行，单机 DuckDB 足够 |
| 继续直读 MySQL | 依赖隧道在线；每股每日一条查询；无 PIT 契约；无法复现 |
| 持久化 `.duckdb` | 形成第二个事实源，[存储选型](2026-09-16-storage-selection.md)已否 |
| 按月分区 | 日更要重写整月文件，修订替换的粒度也变粗 |
| 按股票分区 | 日更要碰 5,000 个目录，产生大量小文件 |
| manifest 用 JSON 或 Parquet 旁文件 | 没有唯一约束，不能原子切换 |

## 代价

1. **"源镜像进 PG"有了例外**，读取源数据要同时认识两种存储。由 adapter 吸收。
2. **Parquet 没有约束**。唯一键、时段、取值范围全靠写入时校验，校验漏掉的错误会直接落盘。
3. **读取依赖 PG**。即使数据在 Parquet，没有 manifest 也读不了。这是刻意的，
   用来换取原子切换和 fail-closed。
4. **单股票长历史查询**依赖 row group 统计跳读，实测不达标时需要加第二套按股票的布局。
5. **源端修订不留历史**，与其他源镜像相同，同一 `as_of` 重算会看到改后的值。

## 推论

1. 盘中（分钟粒度）`as_of` 暂不实现。日频读取用 `same_day_close`；需要盘中回测时
   另写 ADR 扩展规则引擎与 port，不在本决策里预建。
2. 物理参数（row group 大小、压缩级别）先按
   [实施方案](../migration/minute-bar-ingest-plan.md) 的默认值写，一个月样本实测后定版。
3. `var/lake/src/` 只承载本数据集。`var/` 整体可删，因为源端可重拉；
   如果源端停止服务，要重新评估是否需要备份。
