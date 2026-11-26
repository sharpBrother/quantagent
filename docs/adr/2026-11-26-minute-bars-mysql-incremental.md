---
title: 暂用 MySQL 同步分钟行情增量
status: active
created: 2026-11-26
updated: 2026-11-26
applies_to:
  - src/quantagent/ingest/jobs/minprice_incremental.py
  - orchestration/assets/minprice.py
  - orchestration/schedules/minprice.py
supersedes: 2026-11-21-minute-bars-source-split.md
superseded_by: null
---

# 暂用 MySQL 同步分钟行情增量

负责人决定暂缓东财增量，历史追平后增量也暂从 MySQL `minprice` 同步。沿用
现有分日 Parquet、PostgreSQL manifest、成交量为手和成交额为元的口径；既有
分区不自动覆盖，也不跟随源端修改。每日 16:00 首次、17:00 补跑，从最近已
登记交易日开始补齐缺失交易日；源表未就绪或尚未到 15:00、代码数低于上一交易日
95% 时不登记。写入双闸、源数据校验、回读和日志继续生效。

东财资产保留，但日更调度当前选用 MySQL 资产。MySQL 日表在 15:00 后可能仍在
写入，采集应在收盘数据出齐后进行；对 2026-11-26 起每日不超过 3 条的同类收盘异常，若证券为沪深京股票、时间为
15:00 且成交量恰为 -1 手，按负责人此前多次确认的方式将该记录成交量与成交额
置 0，记录原值；负成交额仍须通过逐股日行情差异小于 0.5% 的比较。超过 3 条、
时间或成交量不符等其他异常仍停止。
