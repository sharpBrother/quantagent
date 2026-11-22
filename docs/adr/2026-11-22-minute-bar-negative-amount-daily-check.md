---
title: 分钟行情负成交额按日行情差异处理
status: active
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/ingest/jobs/minprice_corrections.py
  - src/quantagent/ingest/jobs/minprice.py
  - src/quantagent/ingest/writers/minprice_parquet.py
  - src/quantagent/adapters/lake/minute_bar.py
supersedes: 2026-11-22-minute-bar-limited-negative-amounts.md
superseded_by: null
---

# 分钟行情负成交额按日行情差异处理

负责人裁定：MySQL 回填中，对出现负成交额的每个代码，先在计算中将负值置 0，
然后将当日所有分钟成交额求和，与同日 Wind 股票日行情比较；Wind 原字段为千元，
先转换为元。绝对差异除以日成交额严格小于 0.5% 才将该代码的负值置 0 后入库；
达到或超过 0.5%、缺少日行情或日成交额不大于 0 时排除该代码的全天记录。
其他价格、成交量异常仍按原有校验阻断。未出现负成交额的代码不属于本规则的
比较范围。没有可比较的股票日行情的指数同样排除，不猜测数据。

运行记录保留完整源摘要、各异常代码的分钟与日成交额、处理决定、排除清单和
逐条置零前后值。排除清单写入 Parquet 元数据：不指定代码或请求被排除代码时，
读取器必须报缺失。单日分区仍按原有写后回读、摘要和不覆盖规则入库。

先前已经写入的独立裁定分区保留原样；2026-01-21 的原排除名单继续生效。
负责人决定新标准只用于尚未入库的数据，不追溯改写已入库日期。
