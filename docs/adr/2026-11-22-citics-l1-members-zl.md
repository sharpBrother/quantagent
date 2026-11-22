---
title: 中信一级行业成分改用 AINDEXMEMBERSCITICSZL
status: active
created: 2026-11-22
updated: 2026-11-22
applies_to:
  - src/quantagent/adapters/postgres/universe.py
  - db/migrations/src/0025_aindexmembersciticszl.sql
supersedes: null
superseded_by: null
---
# 中信一级行业成分改用 AINDEXMEMBERSCITICSZL

## 背景

旧仓两张中信一级成员表并存，口径冲突：

- `core/market_data_service.py:294-313`（风格轮动等）以 `AINDEXMEMBERSCITICSZL` 为一级 canonical（旧仓 AR-0038），
  旧表 `AINDEXMEMBERSCITICS` 只允许 audit 对账路径读取。
- `alpha_factory/data_gateway.py:853`、`enhanced_optimizer/data/gateway.py:150`、`core/raw_loader.py:108` 仍读旧表。

新仓 `citics1` 原先指向 `AINDEXMEMBERSCITICS`，ZL 表未接入。

## 决策

负责人 2026-11-22 裁定：`citics1` 改读 `AINDEXMEMBERSCITICSZL`。0025 建表，全表镜像，与 `AINDEXMEMBERSCITICS2/3` 同样的接入方式。
可见性沿用已裁定的成分口径：`S_CON_INDATE`/`S_CON_OUTDATE` 对 `as_of` 闭区间切片，grade B。

## 理由

旧仓最近一次针对一级成员表的裁定（AR-0038）选了 ZL，并把旧表降为对账用途。

## 被否方案

- **继续用旧表**：与旧仓最近的裁定相反。
- **两张表都作为 citics1 来源**：同一个 universe 两种口径。

## 代价

- 从 `alpha_factory`、`enhanced_optimizer` 移植的行业相关逻辑，一级行业成员会与旧仓结果不同。移植时的 golden 须按 ZL 取期望值，
  或把差异记为已知口径变化，不能静默对齐旧表。
- 旧表继续采集：`AINDEXINDUSTRIESCITICS` 视图（0020）依赖它筛选中信行业指数代码。

## 推论

- `tests/golden/universe/citics1_zl_wx2.json` 存 wx2 ZL 表 2018-01 至 2026-10 共 106 个月末的成员 digest；
  wx2 上没有一只股票同日命中多个一级行业，旧仓 `keep="last"` 去重不会改变结果。
- 本地表回填前 `tests/integration/test_citics1_zl_live.py` 跳过。
