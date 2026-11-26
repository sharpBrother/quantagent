# 事件三因子迁移交接（event_sue / event_delta_roe / event_aog）

> 本文是 `alpha_factory` Current-20 剩余三事件因子的实现交接。算法已从旧仓
> `factors/factor_event_2.py` 逐行逆向，负责人裁定已记录。读完后即可直接实现，
> 无需重新逆向。属一次性交接文档，三因子全部迁移完成后可删除。

> **进度（2026-11-26）**：`event_sue` ✅ 完成（实现+golden 97.8%+物化+日更，见
> `docs/adr/2026-11-26-event-sue.md`）；`event_aog` ✅ 实现+golden 100% 一致；
> `event_delta_roe` 算法已逆向完毕（§4 已补全），待实现。
>
> **非交易日 declare 裁定（2026-11-26）**：财报可在任意自然日 declare（周末/节假日是披露
> 高峰，wx2 事件行 19.3%-19.5% 来自非交易日 declare）。域判定**不在 declare 日**（非交易日无
> all_a/ST 截面）：`event_aog` 在 open_date（裁定 A1）；`event_sue`/`event_delta_roe` 用 declare 后
> 首个交易日（裁定 B1）。`event_dt` 不变（aog=open_date，sue/delta_roe=declare_date）。

## 1. 前置依赖：已就绪

三张朝阳永续事件源表已由并行会话接入并回填（提交 `219a970`，roadmap 更新 `da2c52d`）：

| 表 | 行数 | 关键列 |
|---|---|---|
| `src_suntime.fin_performance_forecast`（业绩预告） | 133,545 | `np_floor/np_rate_floor/declare_date/entrytime/report_year/report_period` |
| `src_suntime.fin_performance_express`（业绩快报） | 36,105 | `np/np_grate_yoy/declare_date/entrytime/report_year/report_period` |
| `src_suntime.fin_income_gen`（正式财报） | 1,296,625 | `np_shareholder/report_type/report_year/report_quarter/declare_date` |

**可见性契约已写好且与负责人裁定一致**：统一 `declare_date`（date_only，grade A，
`pit_recoverable: true`）。负责人 2026-11-26 裁定："这是财报数据，入库及时，统一用
`declare_date`"——与 `rpt_earnings_adjust` 用 `entrytime` 不同（后者是研报，入库滞后明显）。

数据形态已核实：
- `fin_income_gen.report_type`：1001 合并期末 / 1002 母公司期末 / 1003 合并期末_调整 /
  1004 母公司期末_调整（负责人提供字典）。`report_type in (1001,1003)` = 合并口径（含调整）。
- `report_quarter`：1001/1002/1003/1004 = 一/半/三/年报（注意与 report_type 是两个独立字段）。
- `stock_code` 是 6 位裸代码，需 `add_suffix` 映射（见 §5）。
- `declare_date` 是 datetime（00:00），按日期比较。

## 2. 事件候选构建机制（三因子共享）

旧仓 `process_event`（`factor_event_2.py:213-258`）：

1. 合并三类公告源（forecast、income、express），逐行生成候选事件。
2. 事件键 `(event_date, stock_code_suffix, period)`，其中
   `period = str(report_year) + period_dict[report_period]`，
   `period_dict = {1:'0331',2:'0630',3:'0930',4:'1231',1001:'0331',1002:'0630',1003:'0930',1004:'1231'}`。
   （income 源的 report_period 是 report_quarter 即 1001-1004；forecast/express 是 1-4。）
3. **过滤**：公告月份 ∈ {1,2,3,4,7,8,10}（剔除业绩修正）；公告日距 period ≤ 4×31 天（剔除超晚披露）。
4. **去重**：同键多源只保留**首个**（按 forecast→income→express 遍历顺序，
   `setdefault` 先到先得）。注意：遍历顺序是 notice→income→express。
5. 对每个候选事件调各因子函数；同键同因子只保留首个有效非空非 inf 结果。

## 3. event_sue 算法（factor_event_2.py:383-432）

标准化未预期盈利。步骤：

1. **当期净利 profit**：按事件来源分支——预告用 `np_floor`；快报用 `np`；正式财报用
   `np_shareholder/10000`。（三源列互斥，靠 `'col' in event_s.index` 判断来源。）
   **单位**：fin_income_gen 的 np_shareholder 单位是元，÷10000 转万；forecast/express 的
   np_floor/np 单位需核实（疑似已是万，旧代码未换算——**这是 golden 必须验证的点**）。
2. **历史利润序列**：`fin_income_gen` 查 `report_type in (1001,1003)`、`report_year >= 当期-4`、
   `report_year*10000+report_quarter < 当期`、`declare_date <= declare_date`，
   按 `report_year,report_quarter,report_type` 排序。**不足 13 行直接放弃**（return None）。
3. ÷10000 后，**追加当期行**（report_year/ report_quarter/profit）。
4. `period = report_year*10000+report_quarter`，按 period 去重 keep='last'（1003 调整覆盖 1001）。
5. **单季净利** `np_shareholder_q = np_shareholder.diff()`（累计转单季），但 Q1
   （report_quarter==1001）直接用累计值（`loc[qr==1001]=np_shareholder`）。
6. **同比变化** `q_diff_4 = np_shareholder_q.diff(periods=4)`。
7. `period_ly = (report_year-1)*10000+report_quarter`（去年同期）。若 period_ly 在序列中：
   - `profit_q_ly` = period_ly 处的单季净利
   - `q_diff_4_his` = 截至 period_ly 的 q_diff_4 取 tail(8)，**均值**为预期修正
   - `exp_profit_q = profit_q_ly + q_diff_4_his.mean()`
   - `std_profit_q = q_diff_4.iloc[:-1].tail(8).std()`（注意 `.iloc[:-1]` 去掉当期行）
   - `sue = (当期单季净利 - exp_profit_q) / std_profit_q`
8. sue 非 NaN 才产出。`confirm_date = declare_date`，`event_date = declare_date`。

## 4. event_delta_roe（factor_event_2.py:434-490）与 event_aog（factor_event_2.py:492-540）

**delta_roe**：当期 ROE − 去年同期 ROE，`confirm_date = declare_date`（非 open_date，不依赖行情）。
`event_dt = declare_date`。已逆向完毕并验证（600000.SH 2024Q1：Wind ROE 2.373834 − 2.242767
= 0.131 与 wx2 一致）。步骤：

1. `period_ly` = 去年同期（period 年份 −1，mmdd 不变）。
2. 查 `ASHAREFINANCIALINDICATOR.S_QFA_ROE`：`REPORT_PERIOD in (period, period_ly)`、
   `ANN_DT <= declare_date`，按 ANN_DT 排序。**`roe_last` = period_ly 行的最后一个 S_QFA_ROE；
   period_ly 不在结果中则整个事件不产值**（外层 `if period_ly in ... values` 是硬条件）。
3. 当期 `roe`：
   - 若 period 在结果中且 S_QFA_ROE 非空 → 用 Wind 值。
   - 否则用 profit 重算 `roe = 100*profit_q/eqt`：
     - `profit` 按来源分支（np_floor/np/np_shareholder÷10000，同 sue）。
     - `eqt = get_shrhldr_eqt(stock, get_last_period(period))`（**上一期**股东权益，÷10000）。
     - `profit_q`：Q1（mmdd=0331）直接用 profit；否则 `profit − get_profit(stock, last_period, declare_date)`。
4. `delta_roe = roe − roe_last`，两者皆非空才产出。

辅助函数（`factor_event_2.py:639-700`）：

- `get_last_period(period)`：上一报告期。mmdd 0331→前年1231；0630→0331；0930→0630；1231→0930。
- `get_profit(stock, period, cutoff)`：`fin_income_gen` 查 `report_type in (1001,1003)`、
  `declare_date <= cutoff`，`order by report_type desc` 取首行 ÷10000（1003 调整版优先）。
- `get_profit_q`：`profit − (0 if 0331 else get_profit(last_period))`。
- `get_shrhldr_eqt(stock, period)`：`ASHAREBALANCESHEET.TOT_SHRHLDR_EQY_EXCL_MIN_INT`，
  `STATEMENT_TYPE = 408001000`（合并报表）、`REPORT_PERIOD = period` ÷10000。
  **注意：无 ANN_DT 截止**——股东权益按 REPORT_PERIOD 直接取，不看公告日（潜在前视，
  复现旧行为，golden 登记）。

**依赖源表均已接入**：`ASHAREFINANCIALINDICATOR`（388,947 行，有 S_QFA_ROE/ANN_DT/REPORT_PERIOD）、
`ASHAREBALANCESHEET`（892,279 行，有 TOT_SHRHLDR_EQY_EXCL_MIN_INT/STATEMENT_TYPE/REPORT_PERIOD）、
`fin_income_gen`（已接入）。需新建两个 adapter（ROE 与股东权益）。列名大写，需 `quote_ident`。

**aog**：公告次日开盘涨幅 − 中证500次日开盘涨幅。开盘日判定用 `entrytime`：
`entrytime < declare_date` 或（同日且 `%H%M <= '0925'`）→ 公告**当日**首个交易日；
否则 → 公告**次日**首个交易日。`night_ratio`：个股 `100*(ADJOPEN/ADJPRECLOSE-1)`
（可从 ashareeodprices 重算）、指数 `100*(S_DQ_OPEN/S_DQ_PRECLOSE-1)`（aindexeodprices，
000905.SH）。`confirm_date = open_date`（注意：不是 declare_date！）。

## 5. 待负责人裁定/未决项

- **开盘日阈值**（roadmap line 206）：`event_aog` 用 `'0925'`，`event_high250` 用 `'0930'`
  不一致。负责人 2026-11-26 说"9:25 结束集合竞价，但一般考虑数据刷新运行时间"——
  **这句话的指向需确认**：是统一 `'0925'`、还是 `'0930'`、还是保持各自原值？
  high250 不在 Current-20，若只迁 aog 则用 `'0925'` 即可，但要确认。
- **forecast/express 的 profit 单位**：旧代码对 np_floor/np 未 ÷10000，对 np_shareholder
  ÷10000。需核实源数据单位是否真的不同（疑似 zyyx 预告/快报的 np 字段单位是万，利润表是元）。
  golden 对拍时必须验证。

## 6. add_suffix 映射（zyyx 裸代码 → 后缀）

`8/4/9 → .BJ`；`6/5 → .SH`；`0/3/15 → .SZ`。与 nap_adj_ratio 的号段映射（`6/5→SH, 9→BJ,
其余→SZ`）**不同**——event 版把 `4/8` 也归 BJ、`15` 归 SZ。迁移时用 event 自己的版本复现，
golden 对齐后再评估是否统一。

## 7. 迁移口径对齐（与 nap_adj_ratio/did_ratio 一致）

- 域：逐**交易日**、当日 all_a 减 ST（旧仓逐自然日全市场）。
- 观察日：`observation_date = adj_date - 1 自然日`（旧仓 decisions/2026-08-31 裁定），
  事件按 `confirm_date <= observation_date` 截止。注意 aog 的 confirm_date=open_date 特殊。
- golden：源输入重算比对，不直拍 wx2 旧值（域不同）。
- knowledge_dt 箍到 event_dt（见 nap_adj_ratio ADR 决策 4，稀疏事件因子同适用）。

## 8. 建议实现顺序

1. 先建公共"事件候选构建"层（§2），输出统一的事件流（asset_id/event_date/period/profit/
   来源类型/declare_date/entrytime）。
2. `event_sue` 最纯粹（只依赖 fin_income_gen），先迁。
3. `event_aog` 次之（输入是行情，源已具备）。
4. `event_delta_roe` 最复杂（ROE 重算 + 股东权益 + get_profit 辅助链），最后迁，
   迁前需先补读 `get_shrhldr_eqt`/`get_profit`/`get_last_period`/`get_profit_q` 全部辅助函数。
