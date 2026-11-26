---
title: A 股 1 分钟行情接入方案
status: active
created: 2026-11-21
updated: 2026-11-21
applies_to:
  - src/quantagent/ingest/
  - src/quantagent/adapters/lake/
  - src/quantagent/domain/ports/
  - src/quantagent/contracts/visibility/
  - src/quantagent/platform/config/
  - db/migrations/src/
  - orchestration/
---

# A 股 1 分钟行情接入方案

选型与理由见 [ADR](../adr/2026-11-21-minute-bars-in-parquet.md)。本文写怎么做。
**实施中**；标"待探查"的项在第 1 步核实后回填本文。

2026-11-26 负责人决定日更暂改由 MySQL 同步，覆盖以下旧东财来源计划；
详见 [增量来源裁定](../adr/2026-11-26-minute-bars-mysql-incremental.md)。

2026-11-21 负责人决定不再以 Wind 日行情对账作为迁入条件；保留源值，
成交量统一为手、成交额统一为元。MySQL 只用于历史回填；新增日行情取东财，
详见 [来源裁定](../adr/2026-11-21-minute-bars-source-split.md)。只读探查发现源端有 561 张日表（2024-07-29 至
2026-11-20），其中 2024-07-29 为空；2026-11-20 样本包含 09:30，
单股有 241 行。源端样本字段为 `decimal(20,4)`。

负责人指定修正 2025-10-28 一条负成交量/成交额记录，保留 MySQL 不变并在
运行日志记录原值与摘要；这一分区存在单条源值例外，见
[修正裁定](../adr/2026-11-21-minute-bar-negative-correction.md)。
2025-11-26 一条负成交额亦按负责人要求修正，见
[修正裁定](../adr/2026-11-21-minute-bar-november-negative-correction.md)。
2025-12-08 一条负成交额亦按负责人要求修正，见
[修正裁定](../adr/2026-11-22-minute-bar-december-negative-correction.md)。
2025-12-11 一条负成交额亦按负责人要求修正，见
[修正裁定](../adr/2026-11-22-minute-bar-december-11-correction.md)。
2025-12-29 一条负成交额亦按负责人要求修正，见
[修正裁定](../adr/2026-11-22-minute-bar-december-29-correction.md)。
后续 MySQL 历史数据中，股票负成交额置 0 后的当日分钟合计与日行情差异严格小于
0.5% 才修正入库，否则排除该股票全天；缺日行情也排除，其他异常仍停止。
详见 [处理裁定](../adr/2026-11-22-minute-bar-negative-amount-daily-check.md)。
东财日更的当天股票名单改由 Wind 上市描述表生成，包含沪深京新股；该当前态
名单仅用于采集，不作为 PIT 研究股票池，见 [裁定](../adr/2026-11-25-minute-bar-wind-stock-list.md)。
2025-10-17 的 45 条已由负责人单独裁定，核对记录摘要后置 0，见
[当日裁定](../adr/2026-11-22-minute-bar-october-17-correction.md)。
2026-01-13 的 75 条亦由负责人单独裁定，核对记录摘要后置 0，见
[当日裁定](../adr/2026-11-22-minute-bar-january-13-correction.md)。

## 1. 源端

| 项 | 值 |
|---|---|
| 库 | MySQL `minprice`，经 UURemote 隧道 `127.0.0.1:13306` |
| 表 | 每个交易日一张，`mYYYYMMDD` |
| 列 | `ts_code, trade_time, open, high, low, close, vol, amount` |
| `trade_time` | bar 终点（负责人 2026-11-21 确认） |
| 出齐时间 | 每个交易日 15:30 左右（负责人 2026-11-21 确认） |
| 规模 | 约 5,000 只 × 240 根/日 × 727 日 ≈ 8.7 亿行 |
| 配置 | `QUANTAGENT_MINPRICE_MYSQL_{HOST,PORT,DATABASE,USER,PASSWORD}`，只由 `platform/config` 解析 |
| 驱动 | `pymysql`，进 `sources` 依赖组 |

连接只读：会话开头执行 `SET SESSION TRANSACTION READ ONLY`，只发 `SELECT`。
表名必须匹配 `^m\d{8}$` 且出现在 `information_schema.tables` 的列表里才拼进 SQL，
否则拒绝。

**一次拉一整天**：`SELECT ... FROM minprice.mYYYYMMDD`，用 `SSCursor` 流式读取，
按 20 万行一批转 Arrow。旧仓每股每日一条查询的读法不沿用。

### 待探查（实施第 1 步，只读）

1. 表数量、最早与最晚日期、每表行数和股票数。
2. 列类型（decimal 还是 double，`vol` 是整数还是浮点）。
3. `trade_time` 是 bar 终点（已确认）。待查：每股每天是 240 根（9:31–11:30、13:01–15:00）
   还是 241 根（含 9:30）；尾盘集合竞价怎么处理。
4. 单位：`vol` 为手，`amount` 为元；负责人已取消 Wind 日行情对账要求。
5. 是否包含北交所、指数、ETF；停牌股是否有行。
6. 当日表 15:30 左右出齐（已确认）。待查：历史表是否会被改写，以及出齐前表是否已存在且只有部分行。

## 2. 存储布局

```
var/lake/src/minprice/ashare_minute_bar/
  trade_date=2024-01-02/part-<content_digest 前 16 位>.parquet
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| 分区 | `trade_date`，一天一个文件 | 与源端分表一致 |
| 文件名 | 内容 digest 前缀 | 替换时新旧文件可以并存，切换由 manifest 完成 |
| 排序 | `(ts_code, trade_time)` | 单股票查询靠 row group min/max 跳读 |
| row group | 约 12 万行（约 500 只股票） | 一天约 10 个 row group |
| 压缩 | zstd level 3，`ts_code` 字典编码 | |
| 统计 | 写 statistics 与 page index | |

文件内保留 `trade_date` 列。读取按 manifest 给出的文件列表调用 `read_parquet`，
不依赖 hive 目录解析。目录名只方便人工查看。

### 字段（源原生）

| 列 | 类型 | 说明 |
|---|---|---|
| `ts_code` | string | 源原样，不在 src 层转成 `asset_id` |
| `trade_time` | timestamp（无时区，北京时间） | 源原样 |
| `open`/`high`/`low`/`close` | 源端 decimal 保持同精度 decimal128；double 存 float64 | 不复权 |
| `vol`/`amount` | 同上规则 | 成交量为手、成交额为元，保留源值 |
| `trade_date` | date | 由表名得出，用来分区和对齐日频数据 |

行级不加 `_ingested_at`、`_batch_id`，这些在 manifest 里按天记录一次。

## 3. manifest（PG `src_minprice`）

迁移文件 `db/migrations/src/00xx_minprice.sql`：

```sql
CREATE SCHEMA src_minprice;

CREATE TABLE src_minprice._batch (...);  -- 与其他源 _batch 同结构

CREATE TABLE src_minprice.lake_partition (
    dataset        text        NOT NULL,   -- 'ashare_minute_bar'
    trade_date     date        NOT NULL,
    file_name      text        NOT NULL,   -- 相对数据集根目录
    row_count      bigint      NOT NULL,
    code_count     integer     NOT NULL,
    content_digest char(64)    NOT NULL,   -- 排序后内容的 sha256，与写法无关
    file_sha256    char(64)    NOT NULL,   -- 文件字节 sha256
    file_bytes     bigint      NOT NULL,
    source_table   text        NOT NULL,   -- 'mYYYYMMDD'
    _batch_id      bigint      NOT NULL REFERENCES src_minprice._batch,
    _ingested_at   timestamptz NOT NULL,
    PRIMARY KEY (dataset, trade_date)
);
```

两个 digest 的分工：

- `content_digest`：按 `(ts_code, trade_time)` 排序，用固定 schema 序列化为
  Arrow IPC 后取 sha256。只随内容变化，用来判断源端是否修订。
- `file_sha256`：校验落盘文件没有损坏或被改动。

## 4. 写入流程（`ingest`）

单日写入：

1. 拉取源表 → Arrow，计算 `content_digest`。
2. 若 manifest 已有该日且 digest 相同，记 `skipped`，结束。
3. 校验，**任一失败即停止该日，不写**：
   - `(ts_code, trade_time)` 无重复；
   - 所有 `trade_time` 的日期等于表名日期，时刻落在交易时段内；
   - 该日是交易日（经 `CalendarRepository`，不另写日历查询）；
   - 价格有限且 > 0，`low <= close <= high`、`low <= high`、`open <= high`；
     开盘价低于最低价时，差额不得超过最低价的 0.5%（含边界），保留源值。
     `vol >= 0`、`amount >= 0`。符合容差的记录在 run log 中列出代码、时间和价格。
4. 统计但不阻断：每股 bar 数偏离标准值（240 或 241，待探查）的股票数与清单，写进 run log。
   缺 bar 就是缺，不补。
5. 写到分区目录下的 `.staging-<uuid>.parquet`，DuckDB 回读，比对行数和 `content_digest`，
   一致后 rename 为 `part-<digest16>.parquet`，计算 `file_sha256`。
6. 一个 PG 事务内插入 `_batch` 和新日 manifest；回读比对后提交。
   同一日已有不同内容时停止，不自动替换。提交状态未知时停止报告，不重试。

写入保护沿用 §6：需要 `--write-db` 与 `QUANTAGENT_ALLOW_DB_WRITE=true`；
目标白名单只有 `src_minprice.lake_partition`、`src_minprice._batch` 和上述数据集根目录；
SQL 只使用 `INSERT`。

**残留文件**：分区目录里未被 manifest 引用的 `part-*` 和 `.staging-*` 由
`ingest minprice verify` 列出，不自动删除。

## 5. 调度

| 作业 | 内容 |
|---|---|
| 回填 | CLI `quantagent ingest minprice backfill --start --end`，按日期串行；manifest 已有且 digest 相同的日子跳过，可随时中断续跑 |
| 日更 | Dagster asset，Mac `local` profile，交易日 16:00 运行，17:00 补跑一次，从东财拉当日；不再重拉 MySQL 历史表 |
| 校验 | `quantagent ingest minprice verify`：逐文件核对 `file_sha256` 与行数，列出残留文件 |

16:00 在源端 15:30 出齐后留半小时余量。表存在不等于已出齐，写入前先做完整性检查：
当日最大 `trade_time` 为 15:00，且股票数不低于上一交易日的 95%。不满足则记
"预期数据未到"，不写、不算失败，等 17:00 补跑。补跑仍不满足时告警。95% 是初值，
试跑后按实际停牌与新股数量调整。

## 6. 读取（port 与 adapter）

`domain/ports/minute_bar.py`：

```python
class MinuteBarRepository(Protocol):
    def scan_window(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        codes: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pa.Table: ...
```

`adapters/lake/minute_bar.py`：

1. 从 manifest 取 `trade_date ∈ [start, min(end, PIT 截止日)]` 的文件列表。
   区间内的交易日在 manifest 缺失时报错，不静默跳过。
2. 每个文件比对 Parquet footer 的行数与 manifest 的 `row_count`，不一致即停。
   全文件 sha256 只在 `verify` 里跑，不进每次读取。
3. DuckDB `read_parquet([...])` 加 `ts_code IN (...)` 和列裁剪。
4. 输出时做代码映射与单位换算（std 语义在读取时完成，不物化）。

## 7. PIT

`src/quantagent/contracts/visibility/src.minprice.ashare_minute_bar.yaml`：

```yaml
dataset: src.minprice.ashare_minute_bar
doc_ref: docs/migration/minute-bar-ingest-plan.md
temporal_kind: point_event
event_field: trade_date
visibility:
  rule: same_day_close
  grade: A
  rationale: >
    交易所分钟成交数据。旧仓 factor_min.py 按交易日取当日分钟表计算当日因子。
    日频读取按收盘后整天可见，比盘中逐根可见更严格。不得用 _ingested_at 当可见日。
pit_recoverable: true
```

- 负责人已取消第 1 节第 4 条 Wind 对账要求；PIT 规则仍须满足项目的可见性契约。
- 分钟数据派生的日频因子，`knowledge_dt` 由血缘推导，为 `trade_date` 收盘。
- 盘中 `as_of` 不在本方案内，需要时另写 ADR。因为 `trade_time` 是 bar 终点，
  届时的规则是 `trade_time <= as_of`：终点时刻那根 bar 才算完成。

## 8. 实施顺序与验收

| 步 | 内容 | 验收 |
|---|---|---|
| 1 | 只读探查（第 1 节） | 本文"待探查"各项回填结论 |
| 2 | 配置、依赖、迁移、schema 契约与 visibility YAML | `check contracts` 通过；迁移在本地执行 |
| 3 | 源读取、写入、manifest、verify | 单元测试覆盖：重复键、错日期、坏价格、digest 不变跳过、不同内容拒绝覆盖、提交失败不重试、残留文件不可见 |
| 4 | port 与 adapter | 契约测试：缺 manifest 日报错、`as_of` 截止、footer 行数不符报错 |
| 5 | 一个月样本实测 | 记录文件大小与下表耗时，定版 row group 与压缩参数 |
| 6 | 全量回填与日更上线 | 源端非空交易日均已登记、缺失日明确列出；`verify` 全部通过；roadmap 更新 |

第 5 步的目标值（Mac mini，冷缓存）：

| 查询 | 目标 |
|---|---|
| 一天全市场全部列 | < 1 秒 |
| 一只股票 3 年 | < 3 秒 |
| 全量按股票按日聚合（如日内波动率） | < 5 分钟 |

单股票 3 年查询不达标时，再评估按股票加第二套布局，不提前做。

## 不在本方案内

- 分钟因子（旧仓 `factor_min.py` 约 40 个）的迁移，接入完成后单独排。
- ETF 分钟行情（wx2 `stock_etf_min_price`），源端不同，另行评估。
- 盘中 PIT 与盘中回测。
