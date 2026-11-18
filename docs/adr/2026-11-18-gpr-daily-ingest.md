---
title: GPR 日频采集的版本比较与数值口径
status: active
created: 2026-11-18
updated: 2026-11-18
applies_to:
  - src/quantagent/ingest/sources/macro/gpr.py
  - src/quantagent/ingest/jobs/macro_gpr.py
  - src/quantagent/adapters/postgres/src_progress.py
supersedes: null
superseded_by: null
---
# GPR 日频采集的版本比较与数值口径

## 背景

Iacoviello GPR 日频公开文件（`data_gpr_daily_recent.dta`）是全量历史，没有版本号与发布日期。
目标表 `src_macro.gpr_daily` 的键是 `(series_id, observation_date, file_vintage)`，
其中 `file_vintage` 取文件内最大的 `DAY`，是由数据推出的近似，契约等级为 C。

## 决策

1. 无更新判断：用本次文件的 sha256 对比库里最近写入的 `file_sha256`。取值方式是 `src_macro.gpr_daily` 上按 `_batch_id` 倒序的第一行。
2. 数值口径：先把 float32 加宽到 float64，再按 8 位小数 `ROUND_HALF_EVEN` 量化。
3. 只存变化的版本：本次文件的每一行，若库里没有该 `(series_id, observation_date)`，或库里 `file_vintage` 最大的那一行的值与本次值不等（`Decimal` 按数值比较），则以本次 `file_vintage` 作键写入；值相等则不写。同一 `file_vintage` 下已有的同键行交给写入器按跟随源端规则判断：`file_sha256` 是业务列，内容变了就整键替换并计入 `replaced`。文件里没有的旧日期不做任何事。判断用的库内快照与写入在同一连接上读取。PIT 读法因此是“每个 `(series_id, observation_date)` 取 `file_vintage` 严格早于 `as_of` 的最新一行”。
4. 运行记录：用 `MacroGprRunLog`（`RunLog` 子类）加文件身份与写入计数。

## 理由

- 批次表不能回答“文件有没有变”。写入器在没有任何值变化时也会登记 `_batch`，而那条批次的 `payload_digest` 是行的指纹，不是文件的 sha256。直接取表里的 `file_sha256` 才能对上文件。
- 加宽到 float64 是为了与旧仓 wx2 对拍。wx2 历史值是 float32 加宽后量化的结果，例如 `275.19760132`。2024 年 366 个日期按此口径全部一致（`tests/golden/test_gpr_daily_wx2_golden.py`）。

## 被否方案

- **用批次表的 `payload_digest` 比较。** 它是行指纹，不是文件 sha256，无法直接对比。
- **在 `RunLog` 上加 `detail` 字段记录计数。** `RunLog` 是跨源共用的模型，改它会影响其他源的日志形状。子类只影响 GPR。
- **在 `SrcWriteStore` 协议上新增“读最近文件 sha”的方法。** 协议签名属于公共接口，需要单独裁定。本实现用只读函数 `latest_written_value`，放在 adapter 层。
- **float32 最短十进制串（如 `275.1976`）。** 与 wx2 不一致。
- **旧仓的 `record_hash` 去重追加。** 旧表没有 `file_vintage` 键。新键把版本纳入主键，按值去重会丢掉版本身份。

## 代价

- 首次写入是全量，当前文件是 15,295 个日期 × 6 个序列，共 91,770 行（非缺失）。之后每个新 `file_vintage` 只写相对上一版本有变化的行，增长量取决于源端修订频率，需要运行数周后再估算。
- “库里最近一次写入的 `file_sha256`”不是事务级锁。两次运行同时进行时可能都判定为有更新。日更调度用 `max_concurrent: 1` 与“上一轮未结束则跳过”两道保护，手动并发运行不在保护之内。
- `file_vintage` 是近似版本。PIT 可见性按它判断，等级不高于 C。

## 推论

- 文件新增数值列会自动成为新序列。新增非数值列会让采集报错停止，不会静默丢弃。
- `event` 与 `date` 列不入库。
- 写入器只在目标表声明原生 `ingested_at` 列时核对行内该列。`src_macro.gpr_daily` 没有该列（0018 起的新表不建冗余列），采集时刻只写 `_ingested_at`。
