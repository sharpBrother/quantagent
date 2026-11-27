"""把 barra_cne6_ernqlt 的截面输入收成因子长表行。不写文件，也不接受手填的可见日或 PIT 等级。

ERNQLT 与事件/窗口因子不同：它是**完整 Barra CNE6 风险模型的暴露输出**，逐交易日全横截面合成。
单股票的 descriptor（ABS/ACF）依赖近 21 期财报季度序列；跨股票的 descriptor_process
（去极值/行业中位填补/市值加权标准化）+ l3integrate 等权合成在 ``features.library.cross_section``。

**与已迁 18 个因子的根本差异**：存的不是原始财务比率，而是**标准化后暴露值**（z-score，
与 wx2 ``barra_cne6`` 对齐，其 ERNQLT 标准差精确 = 1.0001，证明存的就是 descriptor_process 处理后的值）。
因此本 panel 必须在**全横截面**上合成——单股票重算无法复现，截面标准化对全样本敏感。

截面由调用方给出：``domain_by_day`` 是每个交易日的股票域（all_a 去掉当日 ST）。只有交易日才有截面。

**可见性与血缘**：

- 财报截止复现旧仓 RAW ``ANN_DT < adj_date``（严格小于，调仓日当天公告不可见——盘前 07:36
  计算时当日财报未出）。端口已按 ``ANN_DT <= as_of`` 批量截止，本 panel 逐截面再裁剪 ``ann_dt < day``。
- ``knowledge_dt`` 箍到 ``event_dt``（= adj_date = 交易日 T）：截面在 T 当日形成可见，
  与 nap_adj_ratio 的箍制语义一致。``pit_grade`` 取财报（A）/市值（A）/行业成分（B）的最差值 = **B**。
- 血缘输入取实际进入计算的财报行（ANN_DT 可见日）+ 当日市值/行业。
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.domain.feature_value import FeatureValue
from quantagent.features.library.cross_section import l3_integrate
from quantagent.features.library.fundamental.ernqlt import (
    DEFINITION_VERSION,
    FEATURE_ID,
    PARAM_HASH,
    ernqlt_descriptors,
)
from quantagent.features.library.fundamental.ernqlt_series import assemble_ernqlt_inputs

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime
    from decimal import Decimal

    from quantagent.domain.fundamental.types import FinancialSeriesRecord


@dataclass(frozen=True, slots=True)
class ErnqltBuild:
    values: tuple[FeatureValue, ...]
    # 逐截面统计：(交易日, 域内股票数, 有暴露值股票数)。供物化 run log 与 golden 覆盖率核对。
    coverage: tuple[tuple[date, int, int], ...]


def build_ernqlt_values(
    *,
    domain_by_day: Mapping[date, frozenset[str]],
    balance_rows: Sequence[FinancialSeriesRecord],
    cashflow_rows: Sequence[FinancialSeriesRecord],
    income_rows: Sequence[FinancialSeriesRecord],
    indicator_rows: Sequence[FinancialSeriesRecord],
    industry_map_by_day: Mapping[date, Mapping[str, str]],
    dq_mv_by_day: Mapping[date, Mapping[str, Decimal | None]],
    financial_grade: str,
    market_grade: str,
    industry_grade: str,
    computed_at: datetime,
    run_id: str,
) -> ErnqltBuild:
    """逐交易日全横截面合成 ERNQLT 暴露。

    输入组织：

    - 四张财报行（``*_rows``）一次性读入全历史、按 as_of 截止后的全集。本函数逐截面按
      ``ann_dt < day`` 再裁剪，复现旧仓``ANN_DT < adj_date``。财报稀疏，逐股缓存去重后的
      {report_period: 行}，按 ann_dt 排序后用 bisect 取截止前缀。
    - ``industry_map_by_day[day]`` / ``dq_mv_by_day[day]`` 是当日行业映射与流通市值（截面权重）。
      键是 wind 代码；缺失（非交易日/无数据）时该截面退化为等权/无行业填补（cross_section 已处理）。

    财报四表 grade 相同（``financial_grade``，A）；市值 ``market_grade``、行业 ``industry_grade``（B）。
    """
    # 逐股缓存：{asset: {table: (ann排序行列表, report_period->行 缓存 by 截止index)}}。
    # 财报稀疏(每股~21期)，逐截面裁剪代价小，但全市场×2142日仍需避免重复去重——按股预去重一次。
    per_stock = _prepare_per_stock(
        balance_rows=balance_rows,
        cashflow_rows=cashflow_rows,
        income_rows=income_rows,
        indicator_rows=indicator_rows,
    )

    values: list[FeatureValue] = []
    coverage: list[tuple[date, int, int]] = []
    for day in sorted(domain_by_day):
        universe = sorted(domain_by_day[day])
        if not universe:
            continue
        industry_map = industry_map_by_day.get(day, {})
        weight = {k: v for k, v in (dq_mv_by_day.get(day, {}) or {}).items() if v is not None}
        # 截面权重转 float（cross_section 用 float 算术）。
        weight_f: dict[str, float] = {k: float(v) for k, v in weight.items()}

        # 1) 逐股算 descriptor 原始值（ABS/ACF）。
        abs_raw: dict[str, float] = {}
        acf_raw: dict[str, float] = {}
        # 记录每股实际进入计算的财报最晚 ann_dt（血缘用）。
        latest_ann_by_stock: dict[str, date] = {}
        for code in universe:
            tables = per_stock.get(code)
            if tables is None:
                continue
            inputs = assemble_ernqlt_inputs(
                balance_rows=_crop(tables.balance, day),
                cashflow_rows=_crop(tables.cashflow, day),
                income_rows=_crop(tables.income, day),
                indicator_rows=_crop(tables.indicator, day),
            )
            desc = ernqlt_descriptors(inputs)
            if desc["ABS"] is not None:
                abs_raw[code] = float(desc["ABS"])
            if desc["ACF"] is not None:
                acf_raw[code] = float(desc["ACF"])
            ann = tables.max_ann_before(day)
            if ann is not None:
                latest_ann_by_stock[code] = ann

        # 2) 跨股票 l3_integrate（去极值+行业中位填补+市值加权标准化+等权平均）。
        integrated = l3_integrate(
            {"ABS": abs_raw, "ACF": acf_raw},
            industry=industry_map,
            weight=weight_f,
        )

        # 3) 落长表行。血缘：财报最晚 ann_dt（可见日）+ 当日市值/行业，箍到 event_dt。
        n_with_value = 0
        for code in universe:
            v = integrated.get(code)
            if v is None:
                continue
            n_with_value += 1
            inputs_lineage: list[tuple[date, str]] = [(day, market_grade), (day, industry_grade)]
            ann = latest_ann_by_stock.get(code)
            if ann is not None:
                inputs_lineage.append((ann, financial_grade))
            knowledge_dt, pit_grade = derive_feature_lineage(inputs_lineage)
            knowledge_dt = max(knowledge_dt, day)
            values.append(
                FeatureValue(
                    event_dt=day,
                    asset_id=code,
                    asset_class="stock",
                    feature_id=FEATURE_ID,
                    definition_version=DEFINITION_VERSION,
                    param_hash=PARAM_HASH,
                    value=float(v),
                    knowledge_dt=knowledge_dt,
                    pit_grade=pit_grade,
                    computed_at=computed_at,
                    run_id=run_id,
                )
            )
        coverage.append((day, len(universe), n_with_value))
    return ErnqltBuild(values=tuple(values), coverage=tuple(coverage))


# ---------------------------------------------------------------------------
# 财报逐股预处理与逐截面裁剪
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _StockTable:
    """单只股票单张表的全部修订行，按 ann_dt 升序。**不做全历史去重**——见 ``_crop``。

    rows: tuple[FinancialSeriesRecord]，按 ann_dt 升序；anns 与 rows 平行，供 bisect。
    """

    rows: tuple[FinancialSeriesRecord, ...]
    anns: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class _StockSeries:
    """单只股票四张表的序列 + 血缘辅助。``all_anns`` 是四表全部 ann_dt 的升序列表。"""

    balance: _StockTable
    cashflow: _StockTable
    income: _StockTable
    indicator: _StockTable
    all_anns: tuple[date, ...]

    def max_ann_before(self, day: date) -> date | None:
        """四表全部行中 ``ann_dt < day`` 的最大值（血缘用），无则 None。"""
        idx = bisect_left(self.all_anns, day)
        return self.all_anns[idx - 1] if idx > 0 else None


def _prepare_per_stock(
    *,
    balance_rows: Sequence[FinancialSeriesRecord],
    cashflow_rows: Sequence[FinancialSeriesRecord],
    income_rows: Sequence[FinancialSeriesRecord],
    indicator_rows: Sequence[FinancialSeriesRecord],
) -> dict[str, _StockSeries]:
    """按股票分组四张表，保留全部修订行按 ann_dt 排序，建成可二分裁剪的结构。

    返回 ``{asset: _StockSeries}``。**不全历史 dedupe**（去重在逐截面裁剪后做，见 ``_crop``）。
    无某表行的股票该表为空序列——``assemble_ernqlt_inputs`` 对空表自然产出 None。
    """
    grouped: dict[str, dict[str, list[FinancialSeriesRecord]]] = {}
    for table_name, rows in (
        ("balance", balance_rows),
        ("cashflow", cashflow_rows),
        ("income", income_rows),
        ("indicator", indicator_rows),
    ):
        for row in rows:
            grouped.setdefault(row.asset_id, {}).setdefault(table_name, []).append(row)

    per_stock: dict[str, _StockSeries] = {}
    for asset, tables in grouped.items():
        built: dict[str, _StockTable] = {}
        all_anns: list[date] = []
        for table_name in ("balance", "cashflow", "income", "indicator"):
            rows = tables.get(table_name, [])
            # **不全历史 dedupe**：保留全部修订行按 ann_dt 升序。去重在逐截面裁剪后做（见 _crop）。
            sorted_rows = tuple(sorted(rows, key=lambda r: r.ann_dt))
            built[table_name] = _StockTable(
                rows=sorted_rows, anns=tuple(r.ann_dt for r in sorted_rows)
            )
            all_anns.extend(r.ann_dt for r in sorted_rows)
        per_stock[asset] = _StockSeries(
            balance=built["balance"],
            cashflow=built["cashflow"],
            income=built["income"],
            indicator=built["indicator"],
            all_anns=tuple(sorted(all_anns)),
        )
    return per_stock


def _crop(table: _StockTable, day: date) -> dict[date, FinancialSeriesRecord]:
    """取 ``ann_dt < day`` 的可见前缀，在**前缀内**按报告期 keep=last 去重。

    **可见性裁剪必须先于版本选择**（PIT 铁律）：不能先全历史 dedupe 再裁剪——否则同报告期的
    早期修订版会被全历史 dedupe 丢弃，导致"修订公告前、初版公告后"的截面日错误地丢失该报告期
    （而非正确使用当时可见的初版）。正确顺序：先按 ``ann_dt < day`` 取可见行，再在可见行内
    按报告期取 ann_dt 最大（keep=last）的版本。ann 升序遍历、后写覆盖先写，即前缀内 keep=last。
    """
    idx = bisect_left(table.anns, day)
    out: dict[date, FinancialSeriesRecord] = {}
    for row in table.rows[:idx]:
        out[row.report_period] = row
    return out
