"""分红、利润表与财务指标的窄读取行，只含 did_ratio 需要的字段。

``ann_dt`` 是源端 ``ANN_DT``，即可见日；读取端口已按 as_of 截止，``ann_dt`` 不会晚于 as_of。
``report_period`` 是 ``REPORT_PERIOD`` 解析出的报告期末日。同一 (代码, 报告期) 的修订去重
不在端口做，由使用方按口径决定，见 ``features.library.fundamental.did_ratio``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from collections.abc import Mapping
if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DividendRecord:
    asset_id: str
    ann_dt: date
    report_period: date
    # 单位与源端 TOT_CASH_DVD 一致（元）。空值保留为 None，由使用方决定如何处理。
    tot_cash_dvd: Decimal | None


@dataclass(frozen=True, slots=True)
class NetProfitRecord:
    asset_id: str
    ann_dt: date
    report_period: date
    # 扣除非经常性损益后归属于母公司股东的净利润，源端 NET_PROFIT_AFTER_DED_NR_LP。
    net_profit_after_ded: Decimal | None


@dataclass(frozen=True, slots=True)
class IndicatorRecord:
    """财务指标行。只用于判断窗口内是否有季末报告期的行，不带指标值。"""

    asset_id: str
    ann_dt: date
    report_period: date


@dataclass(frozen=True, slots=True)
class EarningsAdjustRecord:
    """朝阳永续盈利预测调整行，只含 nap_adj_ratio 需要的字段。

    与财报三表不同，本行有两个时间：``create_dt`` 是研报日期 ``current_create_date``（事件时间，
    业务窗口按它过滤），``entry_dt`` 是入库时间 ``entrytime`` 的日期部分（可见日，PIT 截止按它）。
    读取端口已按 as_of 截止 ``entry_dt``，``entry_dt`` 不会晚于 as_of。``asset_id`` 是补全交易所
    后缀的 Wind 格式（源端 ``stock_code`` 无后缀，由端口按号段补 .BJ/.SH/.SZ）。
    """

    asset_id: str
    create_dt: date
    entry_dt: date
    report_year: int | None
    np_adjust_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class EarningsEventRecord:
    """业绩公告事件候选行（业绩预告/快报/正式财报三源之一），只含事件因子需要的字段。

    ``declare_dt`` 是公告日（源端 ``declare_date``，财报可见性裁定用它截止，grade A）。
    ``profit`` 是当期归母净利润，已统一换算为万元（正式财报源 ``np_shareholder`` 为元，端口÷10000；
    预告 ``np_floor``/快报 ``np`` 源端即为万元，实证比值恒 ≈1e4，见 event-factors-handoff.md）。
    ``report_year`` 与 ``report_quarter`` 统一为 1001/1002/1003/1004（一/半/三/年报）；预告与快报源端
    ``report_period`` 是 1-4，端口已乘 1000 加 1000 映射对齐（``period_dict``/``quarter_dict`` 双向映射）。
    ``source`` 标记事件来源（forecast/express/income），用于多源去重的先到先得与 profit 取值分支复现。
    """

    asset_id: str
    declare_dt: date
    report_year: int
    report_quarter: int
    profit: Decimal | None
    source: str  # "forecast" | "express" | "income"
    # 入库时刻（带时分秒），仅 event_aog 判开盘日用——决定事件结果在哪个交易日的开盘价反映，
    # 是市场微观结构建模，**不是** PIT 可见性字段（可见性截止仍是 declare_dt）。负责人 2026-11-26
    # 裁定：沿用旧仓逻辑，entrytime < declare_dt 或同日 %H%M <= '0925'（集合竞价结束前入库）→
    # 公告当日首个交易日开盘反映，否则次日首个交易日。三源 entrytime 全量非空（已实证）。
    entrytime: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProfitSeriesRecord:
    """``fin_income_gen`` 历史归母净利润行，用于 event_sue 的过去 N 年利润序列重构。

    只取 ``report_type in (1001,1003)``（合并期末/合并期末_调整，负责人 2026-11-26 提供字典）。
    ``np_shareholder`` 单位为元（源端原始单位），**不**在端口换算——库函数复现旧代码 ÷10000 的时机，
    保证 golden 对拍逐位一致。``report_quarter`` 是 1001-1004。``declare_dt`` 是可见截止列。
    """

    asset_id: str
    report_year: int
    report_quarter: int
    report_type: int
    declare_dt: date
    np_shareholder: Decimal | None


@dataclass(frozen=True, slots=True)
class RoeRecord:
    """``ASHAREFINANCIALINDICATOR`` 的加权 ROE 行（``S_QFA_ROE``），event_delta_roe 用。

    ``report_period`` 是报告期末日（``REPORT_PERIOD``，如 2024-03-31）。``ann_dt`` 是公告日，
    可见性截止列——逐事件按 ``ann_dt <= declare_date`` 裁剪（在使用方，端口按 as_of 批量截止）。
    同一 ``report_period`` 可能多行（业绩预告/快报/正式财报多次公告），使用方按 ann_dt 排序取最后一行
    （复现旧代码 ``order by ANN_DT`` 后 ``iloc[-1]``）。``s_qfa_roe`` 单位 %，缺失保留 None。
    """

    asset_id: str
    report_period: date
    ann_dt: date
    s_qfa_roe: Decimal | None


@dataclass(frozen=True, slots=True)
class ShareholderEquityRecord:
    """``ASHAREBALANCESHEET`` 的归母股东权益行（``TOT_SHRHLDR_EQY_EXCL_MIN_INT``），event_delta_roe 重算 ROE 用。

    只取 ``STATEMENT_TYPE = 408001000``（合并报表）。``report_period`` 是报告期末日。单位元，
    **不在端口换算**——库函数复现旧代码 ÷10000 的时机。``ann_dt`` 同时取出供参考，但旧代码
    ``get_shrhldr_eqt`` **不按 ann_dt 截止**（直接按 report_period 取，潜在前视，复现旧行为，
    golden 登记——见 event-factors-handoff.md §4）。
    """

    asset_id: str
    report_period: date
    ann_dt: date
    shrhldr_eqt: Decimal | None
@dataclass(frozen=True, slots=True)
class FinancialSeriesRecord:
    """Wind 财务三表/财务指标的通用多字段行，barra 风格因子（ERNQLT 等）的季度序列用。

    与上面的窄行不同：本行用 ``values`` 字典承载不定字段（一张表一次读多列），键是源端列名
    （如 ``TOT_ASSETS``/``NET_PROFIT_EXCL_MIN_INT_INC``），值缺失为 None、单位与源端一致（元），
    **不在端口换算**。``report_period`` 是报告期末日（``REPORT_PERIOD``），``ann_dt`` 是公告日。

    可见性：端口按 ``ANN_DT <= as_of`` 批量截止（契约 grade A）。但 barra 复现旧仓 RAW
    ``ANN_DT < adj_date``（严格小于，调仓日当天公告不可见——盘前 07:36 计算时当日财报未出），
    逐截面在使用方再裁剪，不在端口做。同一（代码, 报告期）的修订去重（keep=last 取最新公告版）
    与 tail(count) 取最近 N 期也都在使用方做——端口只负责按 as_of 截止后返回全部行，保持单一职责。
    """
    asset_id: str
    report_period: date
    ann_dt: date
    values: Mapping[str, Decimal | None]
