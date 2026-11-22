---
title: 2026-01-21 分钟行情排除 67 只股票
status: active
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/domain/minute_exclusions.py
  - src/quantagent/ingest/jobs/minprice.py
  - src/quantagent/adapters/lake/minute_bar.py
supersedes: null
superseded_by: null
---

# 2026-01-21 分钟行情排除 67 只股票

负责人决定不迁入当日出现负成交额的 67 只股票的任何分钟记录，其他代码继续入库。
排除名单在 `minute_exclusions.py` 中固定；写入前核对源异常代码集合与 103 条
负成交额数量，源端变化即停止。其余代码含两个指数的 3 条负成交额，按既有每日
不超过 10 条的规则置 0，记录原值。MySQL 源不变，运行记录保留完整源摘要、
排除名单、修正记录和输出摘要。

该日分区并非全市场完整：研究读取不指定代码、或请求名单内股票时停止并提示缺失；
明确指定其他代码时允许读取。以后补齐或修订该日时应同步更新此保护。
