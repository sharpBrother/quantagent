---
title: 股票池按读取时计算，不物化
status: active
created: 2026-11-17
updated: 2026-11-17
applies_to:
  - src/quantagent/domain/universe/
  - src/quantagent/adapters/postgres/universe.py
  - docs/architecture/derived-datasets.md
supersedes: null
superseded_by: null
---
# 股票池按读取时计算，不物化
## 背景
[派生数据集清单](../architecture/derived-datasets.md) 原定把股票池物化到
`mart.universe_member`。旧仓 `alpha_factory_universe_member_d` 每日一份截面，
wx2 里 1,280 万行、2,145 个交易日。新设计本来就是区间表，体量是几千到几万行，
但源表（`ASHAREDESCRIPTION` 的上市/退市日、成分表的进出日）本身已是区间，
物化只是原样搬运，多一个资产、一套写入保护和一层对拍。负责人裁定：读取时计算。
## 决策
1. `UniverseRepository.members_at` 由 `adapters/postgres/universe.py` 直接读源表实现，
   规则全部在 `domain/universe/`。接口签名不变。`mart.universe_member` 契约保留，暂不物化。
2. `all_a` 的口径以旧仓现役物化结果为准：规则池 ∩ 当日市值已观测。
   - 规则池：`S_INFO_LISTDATE < dt − 365 自然日`、未退市（`DELISTDATE` 空或 `> dt`）、
     `S_INFO_EXCHMARKET != 'BSE'`（NULL 不算）、代码不以 `A` 开头。不剔 ST。
   - 市值已观测：`ASHAREEODDERIVATIVEINDICATOR` 当日 `S_VAL_MV` 与 `S_DQ_MV` 都非空。来自旧仓
     `alpha_factory/all_a_canonical_scene.py` 的 canonical 分母。只用规则池时 2018–2022 每天多出
     2 到 9 只长期停牌或临近退市的股票。
   - 成员按日给出：`valid_from = valid_to = knowledge_dt = dt`，`member_weight` 为 NULL。
   - `pit_grade = B`：`ASHAREDESCRIPTION` 是当前态主数据，上市/退市日没有当时版本。
3. 旧仓 `core/universe_provider.py` 默认剔除 90 天内 ST，与 alpha_factory 的 all_a 不同。
   本次按 alpha_factory 物化结果，不剔 ST。
## 对拍
`tests/golden/test_all_a_universe_legacy.py` 用 wx2 快照逐日对 `alpha_factory_universe_member_d`：
2,145 个交易日中 2,138 天成员集合逐只相同。7 天不同，都是旧表 2026-08 重写时的自身不一致：
- 20210930、20211231、20220331、20220630：保留了当日市值为空的 `000670.SZ`、`002260.SZ`；
- 20260529：混入 317 只北交所股票；
- 20260617、20260618：比规则多 68 / 70 只，原因未查明。
## 后果
- 研究读取股票池要连 PG。本机 `ASHAREDESCRIPTION` 与衍生指标尚未采集，集成测试会跳过。
- 源镜像只保留当前状态。Wind 修订上市/退市日后，同一 `as_of` 重算结果会变；这两列不在自动替换列里，
  修订会被采集拦下。
- 指数与行业成分池按同一方式另行实现，用 `S_CON_INDATE`/`S_CON_OUTDATE` 区间命中。
