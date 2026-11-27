---
title: 金十 ISM 制造业 PMI 自动增量：详情接口扫描发现与修订跟随源端
status: active
created: 2026-11-27
updated: 2026-11-27
applies_to:
  - src/quantagent/ingest/
  - orchestration/
  - src/quantagent/contracts/visibility/src.macro.jin10_economic_calendar.yaml
supersedes: null
superseded_by: null
---

# 金十 ISM 自动增量：发现机制与修订口径

## 背景

`src_macro.jin10_economic_calendar` 的历史数据已迁入（685 行），但新一期 ISM 制造业 PMI
无法自动入库：采集详情接口 `web/data/jiedu?id=<dataId>` 必须先知道每期的 `dataId`，
而此前认为"没有可用的事件发现接口"。负责人要求尽量沿用旧项目爬虫方式、避免每月手工
维护，实现前先解决"如何发现新一期事件 ID"。

## 否决的路径（2026-11-27 只读核验）

- **金十官方 MCP**（`mcpsvr.jin10.com`）：本机 TLS EOF。且无法确认能返回事件 ID。
- **静态月历** `cdn-rili.jin10.com/web_data/{year}/month/{m}/economics.json`：该域名公网 DNS
  返回 NXDOMAIN，金十已下线；`cdn.jin10.com` 同路径 OSS 404。不是本机代理问题，是源端废弃。
- **历史列表 `reports/list_v2`**：确认停在 2025-09-02。
- **财经日历列表接口**：`/internal/event` 一律 502（内部接口）；SPA 事件由加密 WebSocket
  下发，交接明确要求不逆向；且页面需登录才渲染事件列表。
- **模拟浏览器点击**：用 Chrome DevTools Protocol 实测，日历需登录才渲染事件、数据走加密
  WebSocket。比接口扫描更重（要维护登录态、逆向协议），不解决问题，否决。

## 决定

新事件发现只用公开、免登录、免逆向的详情接口，两个此前未利用的事实构成完整链条：

1. **上一期详情自带 `next_public_time`**（下一期发布的北京时间），决定何时开始找新事件。
2. **下一期落在上一期 `data_id` 之后的连排段内**。实证（2026-12-01 期 `dataId=1179329`）：
   在上一期 `1178751` 之后 578；窗口 `[1178752, 1179329]` 共 579 个 ID 命中 562 个事件，
   其中 `datanameId=129` 恰为首尾两期 ISM。ISM 与物价支付（131）、新订单（130）、
   就业（133）连排。

算法：每天先复查最近 4 期捕获修订；若 `now >= next_public_time`，从上一期 `data_id + 1`
正向扫描 `datanameId == 129` 的记录，命中即校验身份入库。扫描上限 `MAX_SCAN_IDS = 3000`。

**修订**：详情接口对同一 `dataId` 直接覆盖 `actual`，不给版本身份，属"源端不给版本"
（对照 [2026-11-18-source-published-versions](2026-11-18-source-published-versions.md)）。
负责人 2026-11-27 裁定**全自动跟随源端**：同一事务内按主键删旧插新，复用 `write_src_follow`，
与 Tushare/Wind 镜像一致，计数入 run log。契约 D 级、`pit_recoverable: false` 不变。

## 残余风险与边界（fail-closed，不静默）

- **ID 不随发布单调**：2026-10-01 期 `1145155` 比前期小约 3.9 万（排期批次回落）。正向
  扫描覆盖不了回落期。此时扫超上限报错，人工用 `jin10-ism-details --detail-id` 补 ID。
  宁可漏报也不静默漏数——这是设计取舍，不是缺陷。
- **`next_public_time` 缺失**：按未到期处理，不无依据全扫。
- 扫描成本集中在发布日后 1–2 天（每天几百请求，约 100 秒）；其余日子只复查 4 期（个位数请求）。

## 接入

`orchestration` 资产 `src_macro_jin10_economic_calendar` 并入 `macro_daily` 08:00 调度（仅 Mac），
asset 体内导入。CLI `quantagent ingest macro jin10-ism-scan`，默认干跑。首次真实发布验证
窗口为 2026-12-01 23:00（北京）下一期。

## 指纹稳定性修复与一次性订正（2026-11-27）

真实写库验证时发现：存量行 `_row_hash` 与当前算法不一致，复查永不命中 fast-path
（`skipped`），全部走 `metadata_skipped` 逐列兑底。根因是 `digest_json` 对带时区 datetime
按 `isoformat()` 序列化（保留时区表示，timestamptz 读回为上海时区而写入为 UTC，同一时刻
digest 不同），以及详情接口的 decimal 按任意标度序列化（`55.5` vs 库读回 `55.50000000`）。
SHIBOR/GPR 无 timestamptz 业务列、decimal 已在写入端规范，不受影响——问题只出在金十
（唯一含 `published_at` timestamptz 的 follow 表）。

修复：`digest_json` 对带时区 datetime 统一转 UTC 再序列化；金十 `_row_of` 在写入端把
decimal 量化到 numeric(18,8) 存储精度。随后按负责人批准做**一次性 UPDATE 订正**
（仅限 `src_macro.jin10_economic_calendar` 的 `_row_hash` 元数据列、686 行、业务列不动、
事务内写后回读、失败即滚）刷新存量指纹。订正后复查收敛：3 行 `skipped`；并即刻验证到
真实修订跟随——`1179329`（12-01 期）的 forecast 被金十从 55.2 改为 55.0，扫描自动捕获
并按主键删旧插新（`replaced=1`）。订正幂等：重跑报 `need_update=0`。

UPDATE 是 §6.3 禁动词，本次为例外：一次性、有界、仅元数据列、负责人显式批准。
订正作业 `ingest/jobs/jin10_ism_rehash.py`，CLI `jin10-ism-rehash`，默认干跑。
