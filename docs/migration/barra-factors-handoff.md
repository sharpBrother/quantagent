---
title: barra_cne6 ERNQLT/SENTIMENT 迁移交接——公共横截面框架 + 完整逆向
created: 2026-11-26
updated: 2026-11-26
---
# barra_cne6 ERNQLT / SENTIMENT 迁移交接

> Current-20 最后 2 个因子。与之前 18 个根本不同：不是单因子重算，是**完整 Barra CNE6 风险模型**
> 的暴露输出。经负责人裁定，走"公共横截面框架"路线（见下）。本文件固化全部逆向成果。

## 0. 负责人裁定（2026-11-26，已生效）

1. **路线**：把 RAW 基类数据加载 + `descriptor_process`（去极值/标准化/中性化）+ `l3integrate`
   做成**公共横截面因子模块**（`features/cross_section/` 或类似），所有截面因子可复用，不区分是否 barra。
   ERNQLT/SENTIMENT 是该模块的头两个真实用户（驱动设计、即刻验证）。
   **注意**：公共模块是"可选能力"，已迁 18 因子存原始值是正确设计，不强制所有因子走截面处理。
2. **股票池**：用本项目统一 **all_a 减 ST**（非旧仓"上市超14月"）。旧规则本质是历史数据充分性
   要求；新口径下**不预过滤**，数据不足的股票该 descriptor 自然为空（符合"缺失即缺失"铁律）。
3. **值形态**：存**标准化后暴露值**（与 wx2 对齐）。wx2 `barra_cne6` 的 ERNQLT 标准差精确=1.0001
   （z-score），证明存的就是 descriptor_process 处理后的值，不是原始财务比率。

## 1. barra_cne6 本质（关键认知纠偏）

- wx2.dbo.barra_cne6 是 `pycharm_workspace/enhanced_optimizer/factors/exposure.py` 的
  `BarraFactorManager` **本地计算的暴露缓存**，非 tushare/外部预计算。tushare 数据字典标"Tushare"
  是因计算依赖 tushare 基础数据，非 barra 值本身来自 tushare。
- `BarraFactorManager`：`is_date_exists` 命中缓存则读，否则 `compute_style` 重算并写库。
- 9 个风格类：SIZE/VOLATILITY/LIQUIDITY/MOMENTUM/QUALITY/VALUE/GROWTH/SENTIMENT/DIVYLD。
  ERNQLT∈QUALITY、SENTIMENT∈SENTIMENT。
- 表结构：`adj_date/stock_code/LNCAP.../ERNQLT/.../SENTIMENT/.../insert_time`，912 万行，
  20180102~20261030，2142 交易日，5381 股票，ERNQLT/SENTIMENT 零空值，insert_time 全 07:36 盘前。
  非交易日 adj_date 仅 2 个（20260228/20260301 周末，tushare 端偶发异常）。

## 2. 消费口径（PIT 链，window=1 mean +1）

ids=359/364 组合因子中：`barra_cne6.SENTIMENT`/`ERNQLT` window=**1** direction=**+1** demind=**mean**。
`factor_loader.py`：
- 非事件 → `observation_date = prev_trade_date(adj_date)` = P
- window=1 → `recent_dates=[P]`
- barra SQL（`data_gateway._legacy_factor_sql`）：`start_adj=end_adj=next_trade_date(P)`，
  `next_trade_date` 是 `cal_date > P` **严格大于**。P=prev(T)、T 交易日 → next(P)=T。
- **净效果：trade_date=T 的因子值 = barra_cne6 在 adj_date=T 的暴露**（当日盘前 07:36 已插入可见，无前视）。
- SQL：`SELECT adj_date AS trade_date, {field} FROM barra_cne6 WHERE adj_date BETWEEN start_adj AND end_adj`。
- **event_dt = adj_date（交易日），value = 当日暴露，window=1 无聚合**。

## 3. RAW 基类（core/raw_loader.py，权威实现）逆向

### fetch_universe（旧仓，本项目改用 all_a 减 ST）
`ASHAREDESCRIPTION`：`S_INFO_LISTDATE < date-365日`（上市超1年≈14月？实际是365天）且未退市且非北交所。
**本项目不采用**，改 all_a 减 ST + 数据不足自然为空。

### fetch_industry_map
`AINDEXMEMBERSCITICS`（中信行业）：`S_CON_INDATE <= last_date AND (OUTDATE NULL OR >= last_date)`，
按 INDATE 排序 drop_duplicates keep='last'，缺失记 'Unknown'。**PIT 用 last_date=adj_date-1**。
注意：这是指数成分式 PIT（与已裁定成分口径一致 S_CON_INDATE/OUTDATE 对 as_of 切片）。

### fetch_cap
`ASHAREEODDERIVATIVEINDICATOR.S_DQ_MV`（总市值）当日值，dropna，universe 过滤到市值非空的股票。

### fetch_financials（核心，ERNQLT 依赖）
```
SELECT S_INFO_WINDCODE, ANN_DT, REPORT_PERIOD, {fields} FROM {table}
WHERE S_INFO_WINDCODE IN (...) AND ANN_DT > {start} AND ANN_DT < {adj_date}
  [AND STATEMENT_TYPE='408001000']  -- 非 AShareFinancialIndicator 表
ORDER BY REPORT_PERIOD, ANN_DT
```
- **PIT：`ANN_DT < adj_date`**（公告日严格早于调仓日）
- 过滤 REPORT_PERIOD 以 0331/0630/0930/1231 结尾（正式季报）
- `drop_duplicates(['S_INFO_WINDCODE','REPORT_PERIOD'], keep='last')`（同报告期取最后公告版=最新修订）
- `groupby('S_INFO_WINDCODE').tail(count)`（每股取最近 count 期，ERNQLT 用 count=5*4+1=21）
- `last_report_num`：报告期在全样本排序后的序号（**相对期号**，对齐不同股票不齐的财报期）

### _add_quarter_col（累计→单季拆分，关键）
对流量字段（利润/现金流/折旧）：
- `field_Q`：Q1(0331)=累计值；其余季 = 本期累计 - 上期累计（`_convert_quarter` diff）
- **折旧摊销 S_STM_IS / 资本支出特殊**：仅半年报(0630)+年报(1231)有数据；缺失季度按
  `last/last_month*this_month` 比例插值摊到季度（精细 hack）
- 存量字段（资产/负债/股本/现金余额/带息债务）不拆分，直接用原值

### 季度矩阵构造（QUALITY.__init__）
```
pivot(index='last_report_num', columns='S_INFO_WINDCODE', values='{field}_Q')
```
行=相对期号、列=股票的矩阵。流量 TTM=`.rolling(4).sum()`。
ERNQLT 用到的序列：
- `balance_assets_q`=TOT_ASSETS 存量矩阵、`balance_liab_q`=TOT_LIAB、`cash_end_q`=CASH_CASH_EQU_END_PERIOD
  （存量，不拆）、`interest_debt_q`=S_FA_INTERESTDEBT（存量，fillna0 后用）
- `income_y`=NET_PROFIT_EXCL_MIN_INT_INC TTM、`da_y`=S_STM_IS TTM（折旧摊销）
- `cfo_q`/`cfi_q`=NET_CASH_FLOWS_OPER/INV_ACT 单季矩阵（注意：用 _Q 单季，但 ACF 里 tail(4).sum 即 TTM）
- `balance`=最新一期资产负债表（tail(1)），`balance['TOT_ASSETS']` 为分母

## 4. ERNQLT 完整算法（QUALITY.ERNQLT，exposure.py:459）

2 个三级 descriptor 合成（`l3integrate` = 各 descriptor 经 descriptor_process 后**等权平均**）：

**ABS（应计-资产负债法）**：
```
ta_his = balance_assets_q.tail(5)      # 近5期总资产(存量)
cash_his = cash_end_q.tail(5)          # 近5期现金(存量)
tl_his = balance_liab_q.tail(5)        # 近5期负债(存量)
td_his = interest_debt_q.tail(5).fillna(0)  # 近5期带息债务(存量,缺补0)
noa = (ta - cash) - (tl - td)          # 净经营资产
delta_noa = noa.iloc[-1] - noa.iloc[-5]  # 近4季NOA变化(5期首尾差)
da = da_y.iloc[-1]                     # 折旧摊销TTM
acbs = -(delta_noa - da) / balance['TOT_ASSETS']  # 注意:此处delta_noa/da是全矩阵,.iloc后是Series按股票
```
**ACF（应计-现金流法）**：
```
ni = income_y.iloc[-1]                 # 净利润TTM
cfo = cfo_q.tail(4).sum()              # 经营现金流TTM(近4单季和)
cfi = cfi_q.tail(4).sum()              # 投资现金流TTM
da = da_y.iloc[-1]
accr = ni - (cfo+cfi) + da
accf = -accr / balance['TOT_ASSETS']
```
`f_dict={'ABS':acbs,'ACF':accf}` → `l3integrate` → ERNQLT。
**注**：delta_noa/da/ni/cfo 都是 stock×period 矩阵的 `.iloc[-1]`/`.tail` 操作，结果是按股票对齐的
Series；`balance['TOT_ASSETS']` 是按股票的最新总资产 Series。l3integrate 内对每个 descriptor
做 descriptor_process（截面去极值+行业中位数填补+市值加权标准化），再等权平均。

## 5. SENTIMENT 完整算法（SENTIMENT.SENTIMENT，exposure.py:716）

3 个 descriptor 合成。`__init__` 预加载：
- `con_adjust_data_1`=fetch_suntime_adjust(['np_adjust_mark'], count=3*21)
- `con_adjust_data_2`=fetch_suntime_adjust(['current_forecast_eps','previous_forecast_eps'], count=4*21)
- `price`=ASHAREEODPRICES.S_DQ_CLOSE 当日（count=1）

**RR（评级调整）**：近 3×21 交易日。`groupby(stock,organ,current_create_date).np_adjust_mark.max()`
→ dropna → 每股 `(上调(mark==2)数 - 下调(mark==3)数)/总数`。
**ETOPFC（EP预测变化）**：近 4×21 日。dropna(eps两列) → drop_duplicates(stock,organ,keep first) →
join price → `current_ep=eps/close`、`previous_ep=prev_eps/close` → 每股 mean →
`(curr_mean - prev_mean)/abs(prev_mean)`。
**EPSFC（EPS预测变化）**：同上但不除价格：`(curr_eps_mean - prev_eps_mean)/abs(prev_eps_mean)`。
l3integrate 合成。**数据已在 PG**：`rpt_earnings_adjust`（nap_adj_ratio 同源，含 np_adjust_mark/
current_forecast_eps/previous_forecast_eps/organ_id/current_create_date/report_year）。

## 6. fetch_suntime_adjust 口径
```
SELECT stock_code,organ_id,current_create_date,report_year,{fields} FROM rpt_earnings_adjust
WHERE current_create_date BETWEEN start AND end AND stock_code IN (6位裸码)
```
- 时间窗：end=adj_date-1（last_date），start=trade_date.iloc[-count]（倒数第count个交易日）
- stock_code 转 6 位裸码查询，结果 add_suffix 补后缀
- **PIT 是 current_create_date**（与 nap_adj_ratio 裁定的可见性一致）

## 7. descriptor_process（factor_math.py，公共核心）

顺序固定（迁移前后零差异关键）：
1. reindex 到 industry_map.index
2. 全空→返回0序列
3. `winsorize`：普通因子 3倍MAD 裁剪；**股息类(DTOP/DTOPF/DIVYLD)特殊**=排名映射正态分位clip[-3,3]
   （此 hack 不进通用 winsorize，仅 barra 股息用）
4. 行业中位数填补缺失：`fv.groupby(industry_map).transform(median)`
5. `normalize(fv, weight)`：weight=cap 市值加权 z-score（市值加权均值/标准差）；无权重退化等权

`l3integrate`：每个 descriptor 经 descriptor_process 后求和 / 个数（**等权平均**）。

## 8. 迁移架构建议（待实施）

建 `features/cross_section/`（或 domain 合适层）公共模块：
- **截面处理原语**（domain 纯函数，零存储依赖）：`winsorize_mad`、`zscore_weighted`、
  `industry_neutral_fill`、`descriptor_pipeline`(组合)、`l3_integrate`
- **财报季度序列能力**（panel/adapter 层）：`quarterly_series`(累计→单季+折旧特殊)、
  `last_report_num` 对齐、TTM rolling。适配到本项目财报端口。
- 市值/行业/日历：复用本项目 ports（derivative_indicator/universe/calendar），行业需中信端口
  （AINDEXMEMBERSCITICS 是否已 ingest 待查；若无需新增）。
然后实现 ERNQLT+SENTIMENT 验证模块。

## 8.5 实施进度（2026-11-26）

**已完成**：
- ✅ 公共截面模块 `features/library/cross_section.py` 扩展（commit `ae7a22e`）：
  `weighted_zscore`（复现 normalize，缺失填加权均值+未加权std ddof=0）、`industry_median_fill`、
  `descriptor_pipeline`、`l3_integrate`。数值对照旧仓 pandas 最大差异 ~1e-16。11 单元测试全过。
- ✅ 可行性核查：全部源表字段齐备（BALANCESHEET/INCOME/CASHFLOW/FINANCIALINDICATOR/
  EODDERIVATIVEINDICATOR），中信行业成分 `AINDEXMEMBERSCITICS` 在 PG（30一级/114二级/312三级行业，
  S_INFO_WINDCODE=行业指数CI005xxx.WI、S_CON_WINDCODE=成分股、INDATE/OUTDATE）。
- ✅ 负责人裁定：`aindexmemberscitics` 行业成分沿用成分规则（S_CON_INDATE/OUTDATE 对 as_of 切片，
  grade A）——**契约待补**（当前 visibility/ 无此 yaml）。

**下一步（按序）**：
1. 补 `contracts/visibility/src.wind.aindexmemberscitics.yaml`（成分规则）+ schemas 若缺。
2. 财报时间序列 adapter：复现 RAW `fetch_financials`——按表/字段/ANN_DT<adj_date 截止、
   STATEMENT_TYPE='408001000'（FINANCIALINDICATOR 除外）、REPORT_PERIOD 以0331/0630/0930/1231结尾过滤、
   drop_duplicates(windcode,report_period,keep=last)、每股tail(count=21)、last_report_num 相对期号。
   ERNQLT 需 BALANCESHEET(INCL_MIN_INT/OTHER_EQUITY_TOOLS/NON_CUR_LIAB/TOT_LIAB/TOT_ASSETS/TOT_SHR)、
   FINANCIALINDICATOR(S_FA_INTERESTDEBT/S_STM_IS/S_FA_CAPITALIZEDTODA)、INCOME(TOT_OPER_REV/TOT_OPER_COST/
   NET_PROFIT_EXCL_MIN_INT_INC)、CASHFLOW(NET_INCR_CASH_CASH_EQU/CASH_CASH_EQU_END_PERIOD/
   NET_CASH_FLOWS_OPER_ACT/NET_CASH_FLOWS_INV_ACT)。
3. `_add_quarter_col` 季度拆分（panel/domain 纯 python，项目不用pandas）：Q1=累计、非Q1=本期-上期、
   is_last连续性校验(不连续field_Q=NaN)、折旧S_STM_IS/CAPITALIZED半年报年报插值
   (last/last_month*this_month)。last_report_num透视+rolling(4).sum()做TTM。
4. ERNQLT library(ABS/ACF纯函数)+panel(数据装配+descriptor合成)。
5. 行业映射 adapter(fetch_industry_map: INDATE<=last_date AND (OUTDATE NULL OR >=last_date),
   keep=last,缺失'Unknown')+市值cap adapter(S_DQ_MV)。
6. SENTIMENT library(RR/ETOPFC/EPSFC)+panel。
7. 全横截面golden(不能单股对拍，需全all_a重算比wx2整行，容差设计是难点——快照时差+股票池差异)。
8. 物化+日更。

**风格约束**：本项目 panel/library 现有文件均不用 pandas（坚持 dict/纯python），pandas虽是依赖。
财报季度序列是逐股票时序操作（rolling逐股），跨股票仅在descriptor_process(已dict实现)，
故纯python可行。rolling(4).sum()=近4期求和，**满4期才产值**（前3期NaN），**窗口内任一
   NaN则结果为NaN**（pandas rolling 默认 min_periods=window，NaN传播）——即 TTM 严格4季完整才计算，
   任一季缺失(折旧插值失败/is_last不连续)使 TTM 为NaN、descriptor为空，与“数据不足则descriptor为空”
   裁定一致。纯python实现rolling_ttm时需严格复现此NaN传播语义。

## 9. 待查/风险

- **AINDEXMEMBERSCITICS（中信行业成分）是否已 ingest 进 PG**——SENTIMENT/ERNQLT 的行业中性化依赖。
  若无，需新增采集（属源镜像，遵循 src-mirror-follows-source ADR）。
- `_add_quarter_col` 折旧摊销插值 hack 极其精细，golden 对齐难点。
- ERNQLT 5期 NOA 需 21 期财报（count=5*4+1），as_of 截止 + ANN_DT<adj_date 双重过滤后的数据充分性。
- 财报 `STATEMENT_TYPE='408001000'`（合并报表）。`keep='last'` 取最新修订版（与 sue 的 1003 快照
  问题类似——golden 需用计算时点快照，会有同类快照时差）。
- golden 对拍：wx2 barra_cne6 逐 adj_date 值 vs 新仓重算。容差需评估（截面标准化对全样本敏感，
  单股票重算无法复现——必须全横截面重算才能对拍，这是与事件因子 golden 的根本差异）。
