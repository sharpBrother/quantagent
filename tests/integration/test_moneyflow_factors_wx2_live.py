"""资金流三因子（abso_umr、moneyflowh、actlargemedcut）与旧仓 wx2 ``stock_<factor>`` 对拍。

数据来源：本地 PG（all_a 成员、行情、资金流、基准指数）只读。旧值与 wx2 原始资金流行来自
``tests/golden/market_data/moneyflow_factors/``：

- ``<YYYYMMDD>.json``：一个截面日。``codes`` 是截面日 all_a 成员（升序），每个因子一个与 ``codes`` 等长的数组
  （wx2 原样十进制字符串，无行或 NULL 为 null）。provenance 记录 SQL、范围与抓取日期。
- ``wx2_source_rows.json``：wx2 ``ASHAREMONEYFLOW`` 中与本地不同的行，只存 9 个因子用到的字段（NULL 保留为 null），
  只包含 golden 截面日的 abso_umr 窗口（69 个开市日）内出现的 (日期, 代码)。

截面日选取：只用“可复现区间”内的日期。抽样方法、按月一致率与区间划分写在
``docs/adr/2026-11-24-moneyflow-factors-batch-2a.md``。摘要如下：

- 抽样：2021-10 起每月取第一个 15 日及以后的开市日；abso_umr 另取 2018-05 起每季度一个。每个截面日用
  ``一致 / (一致 + 其他)`` 计算一致率，分母排除已裁定与源数据差异。达标要求一致率 >= 99% 且分母覆盖 wx2 非空行的一半以上。
- 不可复现区间（不追查），按抽样月：abso_umr 为 2023-04 至 2023-10、2024-01 至 2024-04（窗口跨越下面的重写日）；
  moneyflowh 为 2021-12、2022-06 至 2022-08、2022-10 至 2022-11、2023-04、2023-06、2023-08、2024-01、2025-07、2025-09；
  actlargemedcut 为 2021-12、2022-07 至 2022-08、2022-11、2025-07、2025-09。2021-10-15 的 moneyflowh 与 actlargemedcut
  在 wx2 中无行。2022-06 至 2022-08 的 moneyflowh 与 actlargemedcut 的“其他”占比很高，与资金流源数据无关。
- wx2 OPDATE 批量重写（观察，不追查）：2023-03-20、2023-06-02、2023-08-01、2024-01-08 的 wx2 ``ASHAREMONEYFLOW``
  当日行几乎全部为当日 OPDATE，与本地镜像大面积不同；2023-12-13 有 5084 行 OPDATE 为当日，其中 2242 行与本地不同。
  2018 至 2022 年的历史行大量带 OPDATE 2026-03-04/05（2022-06-01 的 wx2 行中 3745 行），与本地不同的行数很少。
- 未判定哪一边对：上述 wx2 重写与本地镜像谁正确，未判定。本仓以本地镜像为输入（源镜像跟随 Wind，见 ADR），
  golden 只证明 wx2 与本地的差异来自输入，不证明 wx2 是错的。
- 残留未解释差异：2021-11-15 与 2022-12-15 的若干股票在三因子中仍归为“其他”（个别为行情侧的精度差异，例如
  wx2 的复权价只保留 2 位小数，``000717.SZ`` 2022-09-15 的 actlargemedcut）。这两天不进 golden，不加例外。

比对口径：
- 旧表存的是 raw；本仓长表存 ``SIGN * raw``（消费方向）。比对前把长表值乘回 SIGN。
- 比对精度按旧表存储精度：abso_umr 为 numeric(20,8)，其余两个为 numeric(10,6)，ROUND_HALF_UP。

每个 (因子, 股票, 截面日) 只有四类结果，按以下优先级判定：

- 一致：双方都有值且相等，或双方都无值。
- 已裁定（严格口径）：旧有值、新无值，且本仓窗口内有缺失输入或分母为 0。这是 AGENTS.md §7.5 与 tr_umr v2 的同一
  原则：窗口内缺输入不产值。旧代码跳过缺失（pandas ``nansum`` / ``sum`` / ``dropna``）才会得到旧值。每一条都要
  同时满足两个证据：本地窗口确有缺失（``_strict_gap``），且用旧 pandas 语义模拟出的值与旧值相等（``_legacy_raw``）。
  两者缺一即为“其他”。
- 源数据差异：窗口内有 wx2 与本地不同的资金流行（含一侧有行、另一侧无行）。证据是：用 wx2 行替换本地对应行后，
  经本仓同一计算函数（严格口径）重算得到旧值，或在替换后的输入上用旧 pandas 语义模拟得到旧值。
  这两条路径任一成立即可。替换后本仓重算为 NULL 而旧值为 0 的，由第二条路径证明（旧 ``sum()`` 对全 NaN 得 0）。
  主要来源有三：
  1. 2023-12-13 的 SH 资金流快照（wx2 的 OPDATE 为 2023-12-13，本地镜像为 2023-12-14 10:15），2000 多只股票的 9 个字段不同。
  2. wx2 整段无行、本地有行，如 302132.SZ、689009.SH 上市初期的资金流。这类行在 ``wx2_source_rows.json`` 中存为 null。
  3. 少数股票在个别日的字段不同。
  golden 窗口内 wx2 没有单元格级 NULL，只有整行缺失。
  裁定：以本地镜像为准（源镜像跟随 Wind，见 ``docs/adr/2026-11-17-src-mirror-follows-source.md``）。
  因此本仓的输出与 wx2 的旧值不一致，但 golden 用 wx2 原始行证明差异确实来自输入。这是调度方建议，未经负责人裁定。
- 其他：不属于以上任何一类。测试失败，不加例外。
"""

from __future__ import annotations

import functools
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pytest

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import load_price_visibility
from quantagent.adapters.postgres.index_returns import load_index_visibility
from quantagent.adapters.postgres.money_flow import load_money_flow_visibility
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.cli.moneyflow_materialize import read_moneyflow_inputs
from quantagent.domain.calendar import open_dates
from quantagent.domain.money_flow.types import MoneyFlow
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID
from quantagent.features.library._legacy_sort import legacy_descending_order
from quantagent.features.library.money_flow import abso_umr, actlargemedcut, moneyflowh
from quantagent.features.library.money_flow.abso_umr import LOOKBACK, abso_umr_from_maps
from quantagent.features.library.price.tr_umr import RET_WINDOW
from quantagent.features.panel.money_flow import build_money_flow_factor_values
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import psycopg

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.feature_value import FeatureValue
    from quantagent.domain.index_returns.types import IndexReturn
    from quantagent.domain.prices.types import DailyPrice

FIXTURE_DIR = Path(__file__).parents[1] / "golden" / "market_data" / "moneyflow_factors"
SOURCE_ROWS_PATH = FIXTURE_DIR / "wx2_source_rows.json"
AS_OF = date(2026, 11, 24)
COMPUTED_AT = datetime(2026, 11, 25)
FACTORS = ("abso_umr", "moneyflowh", "actlargemedcut")
# 旧表存 raw；长表存 SIGN * raw。比对时乘回 SIGN，与 cutamp 的测试一致。
SIGN = {
    "abso_umr": Decimal("1"),
    "moneyflowh": moneyflowh.SIGN,
    "actlargemedcut": actlargemedcut.SIGN,
}
SCALE = {
    "abso_umr": Decimal("0.00000001"),
    "moneyflowh": Decimal("0.000001"),
    "actlargemedcut": Decimal("0.000001"),
}
FEATURE_ID = {
    "abso_umr": abso_umr.FEATURE_ID,
    "moneyflowh": moneyflowh.FEATURE_ID,
    "actlargemedcut": actlargemedcut.FEATURE_ID,
}
# 截面日来自“可复现区间”，见 ADR：抽样中三因子的一致率都达标，且 golden 窗口内没有残留的未解释差异。
# 2023-03-15：窗口在 2023-03-20 的 wx2 批量重写之前。
# 2023-12-15：abso_umr 窗口跨 2023-12-13 的 SH 资金流快照，2000 多只股票由 wx2 源行解释。
# 2024-05-15：常规窗口。
# 2025-10-15：窗口内 1238 只股票发生除权，是除权较多的时段。
GOLDEN_DAYS: tuple[date, ...] = (
    date(2023, 3, 15),
    date(2023, 12, 15),
    date(2024, 5, 15),
    date(2025, 10, 15),
)
# wx2 ASHAREMONEYFLOW 的 9 个字段，顺序与 wx2_source_rows.json 的 fields 一致。
SOURCE_FIELDS = (
    "value_diff_small_trader",
    "value_diff_med_trader",
    "value_diff_large_trader",
    "value_diff_institute",
    "buy_value_small_order_act",
    "buy_value_med_order_act",
    "buy_value_large_order_act",
    "sell_value_med_order_act",
    "sell_value_large_order_act",
)
_EXCHANGE = "SSE"
_CALENDAR_PAD_DAYS = 240
_OWN_WINDOW = moneyflowh.WINDOW
_FAILURE_LIST_LIMIT = 20
_ABSO_RISK_START = LOOKBACK - RET_WINDOW
CATEGORIES = ("一致", "已裁定", "源数据差异", "其他")
_NAN = math.nan


@dataclass
class _Fixture:
    codes: tuple[str, ...]
    old: dict[str, dict[str, Decimal | None]]
    provenance: dict[str, Any]


@dataclass
class _Day:
    day: date
    scope: frozenset[str]
    opens: tuple[date, ...]
    prices: dict[str, dict[date, DailyPrice]]
    flows: dict[str, dict[date, MoneyFlow]]
    index_by_day: dict[date, IndexReturn]
    produced: dict[tuple[str, str], float]
    fixture: _Fixture


@dataclass(frozen=True)
class _SourceRow:
    """wx2 中与本地不同的一行。``cells`` 按 SOURCE_FIELDS 顺序，单元格 NULL 为 None。
    ``cells`` 整体为 None 表示 wx2 没有这一行（本地有行），替换时删除本地行。"""

    day: date
    code: str
    cells: tuple[Decimal | None, ...] | None


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def _load_fixture(day: date) -> _Fixture:
    doc = json.loads((FIXTURE_DIR / f"{_ymd(day)}.json").read_text(encoding="utf-8"))
    codes: list[str] = doc["codes"]
    provenance: dict[str, Any] = doc["provenance"]
    if codes != sorted(set(codes)) or len(codes) != provenance["scope_count"]:
        raise ValueError(f"fixture {day} 的 codes 不是升序去重或与 scope_count 不符")
    old: dict[str, dict[str, Decimal | None]] = {}
    for factor in FACTORS:
        column = doc["columns"][factor]
        if len(column) != len(codes):
            raise ValueError(f"fixture {day} 的 {factor} 与 codes 长度不等")
        old[factor] = {
            code: None if value is None else Decimal(value)
            for code, value in zip(codes, column, strict=True)
        }
    return _Fixture(codes=tuple(codes), old=old, provenance=provenance)


def _load_source_rows() -> tuple[_SourceRow, ...]:
    doc = json.loads(SOURCE_ROWS_PATH.read_text(encoding="utf-8"))
    if tuple(doc["fields"]) != SOURCE_FIELDS:
        raise ValueError("wx2_source_rows.json 的字段顺序与 SOURCE_FIELDS 不一致")
    rows: list[_SourceRow] = []
    for ymd, by_code in doc["rows"].items():
        trade_day = datetime.strptime(ymd, "%Y%m%d").date()
        for code, cells in by_code.items():
            if cells is not None and len(cells) != len(SOURCE_FIELDS):
                raise ValueError(f"源行 {ymd} {code} 的字段数不对")
            rows.append(
                _SourceRow(
                    day=trade_day,
                    code=code,
                    cells=None
                    if cells is None
                    else tuple(None if v is None else Decimal(v) for v in cells),
                )
            )
    return tuple(rows)


def _quantize(value: Decimal, scale: Decimal) -> Decimal:
    return value.quantize(scale, rounding=ROUND_HALF_UP)


def _local_raw(factor: str, value: float) -> Decimal:
    # repr 保留 float 的最短可逆表示，避免把 0.1 之类的值先放大成长尾小数。
    return SIGN[factor] * Decimal(repr(value))


def _ratio(adj_close: Decimal, adj_preclose: Decimal) -> Decimal:
    # 与 actlargemedcut 的十进制口径一致（50 位），避免并列判断受 float 误差影响。
    with localcontext() as ctx:
        ctx.prec = 50
        return Decimal(100) * (adj_close / adj_preclose - 1)


def _window_abso(day: _Day) -> tuple[date, ...]:
    idx = day.opens.index(day.day)
    return day.opens[idx - (LOOKBACK - 1) : idx + 1]


def _own_rows(day: _Day, code: str) -> tuple[DailyPrice, ...]:
    """个股自有的最近 20 行行情（旧仓 ``tail(20)``），截面日为最后一行。不足 20 行返回空元组。"""
    rows = sorted(
        (row for row in day.prices.get(code, {}).values() if row.trade_dt <= day.day),
        key=lambda item: item.trade_dt,
    )
    if len(rows) < _OWN_WINDOW:
        return ()
    return tuple(rows[-_OWN_WINDOW:])


def _flow_from_cells(trade_day: date, code: str, cells: Sequence[Decimal | None]) -> MoneyFlow:
    v = dict(zip(SOURCE_FIELDS, cells, strict=True))
    return MoneyFlow(
        trade_dt=trade_day,
        wind_code=code,
        buy_value_small_order_act=v["buy_value_small_order_act"],
        buy_value_med_order_act=v["buy_value_med_order_act"],
        buy_value_large_order_act=v["buy_value_large_order_act"],
        sell_value_med_order_act=v["sell_value_med_order_act"],
        sell_value_large_order_act=v["sell_value_large_order_act"],
        value_diff_small_trader=v["value_diff_small_trader"],
        value_diff_med_trader=v["value_diff_med_trader"],
        value_diff_large_trader=v["value_diff_large_trader"],
        value_diff_institute=v["value_diff_institute"],
    )


class _Context:
    """只读访问本地 PG 与 lake，按截面日缓存输入与计算结果。"""

    def __init__(self) -> None:
        settings = get_settings()
        paths = resolve_var_paths(settings, repo_root=detect_repo_root())
        self.conn: psycopg.Connection[object] = connect(settings, "src")
        self.conn.read_only = True
        self.calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
        self.universe = PostgresUniverseRepository(self.conn)
        self.source_rows = _load_source_rows()
        self._days: dict[date, _Day] = {}

    def close(self) -> None:
        self.conn.close()

    def all_a(self, day: date) -> frozenset[str]:
        members = self.universe.members_at(as_of=AS_OF, dt=day, universe_id=ALL_A_UNIVERSE_ID)
        return frozenset(member.asset_id for member in members)

    def day(self, day: date) -> _Day:
        if day not in self._days:
            self._days[day] = self._load(day)
        return self._days[day]

    def _load(self, day: date) -> _Day:
        fixture = _load_fixture(day)
        scope = frozenset(fixture.codes)
        # 比对范围必须仍是截面日的 all_a 成员，否则旧表与新范围不可比。
        if self.all_a(day) != scope:
            raise AssertionError(f"{day} 的 fixture 范围与当前 all_a 成员不一致")
        days = self.calendar.list_days(
            as_of=AS_OF,
            exchange=_EXCHANGE,
            start=day - timedelta(days=_CALENDAR_PAD_DAYS),
            end=day,
        )
        opens = tuple(open_dates(days))
        prices, flows, index_returns = read_moneyflow_inputs(
            self.conn,
            as_of=AS_OF,
            opens=opens,
            start=day,
            end=day,
            codes=fixture.codes,
        )
        rows: tuple[FeatureValue, ...] = build_money_flow_factor_values(
            prices,
            flows,
            index_returns,
            opens,
            price_contract=_contract("price"),
            money_flow_contract=_contract("money_flow"),
            index_contract=_contract("index"),
            start=day,
            end=day,
            computed_at=COMPUTED_AT,
            run_id=f"golden-moneyflow-{_ymd(day)}",
        )
        produced: dict[tuple[str, str], float] = {}
        for row in rows:
            assert row.event_dt == day
            key = (row.feature_id, row.asset_id)
            assert key not in produced, key
            produced[key] = row.value
        price_map: dict[str, dict[date, DailyPrice]] = {}
        for price_row in prices:
            price_map.setdefault(price_row.wind_code, {})[price_row.trade_dt] = price_row
        flow_map: dict[str, dict[date, MoneyFlow]] = {}
        for flow_row in flows:
            flow_map.setdefault(flow_row.wind_code, {})[flow_row.trade_dt] = flow_row
        return _Day(
            day=day,
            scope=scope,
            opens=opens,
            prices=price_map,
            flows=flow_map,
            index_by_day={item.trade_dt: item for item in index_returns},
            produced=produced,
            fixture=fixture,
        )


@functools.cache
def _contract(kind: str) -> VisibilityContract:
    # 契约从 YAML 加载，缓存后每个股票不再重复解析。
    loaders = {
        "price": load_price_visibility,
        "money_flow": load_money_flow_visibility,
        "index": load_index_visibility,
    }
    return loaders[kind]()


@pytest.fixture(scope="module")
def ctx() -> Iterator[_Context]:
    context = _Context()
    yield context
    context.close()


# ------------------------------------------------------------ 严格口径的缺失原因


def _abso_strict_gap(day: _Day, code: str) -> str | None:
    """abso_umr 的 69 日风险序列与最后 60 日超额收益所需输入。返回第一处缺失原因，没有则 None。
    成交额为 0 视为无定义（分母为 0）。"""
    prices = day.prices.get(code, {})
    flows = day.flows.get(code, {})
    for position, trade_day in enumerate(_window_abso(day)):
        price = prices.get(trade_day)
        flow = flows.get(trade_day)
        if price is None or flow is None or flow.buy_value_small_order_act is None:
            return "风险序列缺行或缺小单主动买入"
        if price.amount is None or price.amount == 0:
            return "成交额缺失或为 0"
        if position >= _ABSO_RISK_START:
            index_row = day.index_by_day.get(trade_day)
            if price.pct_change is None or index_row is None or index_row.pct_change is None:
                return "超额收益缺涨跌幅或指数收益"
    return None


def _moneyflowh_row_gap(flow: MoneyFlow) -> str | None:
    if any(
        value is None
        for value in (
            flow.value_diff_institute,
            flow.value_diff_large_trader,
            flow.value_diff_med_trader,
            flow.value_diff_small_trader,
        )
    ):
        return "窗口内缺量差字段"
    return None


def _actl_row_gap(row: DailyPrice, flow: MoneyFlow) -> str | None:
    acts = (
        flow.buy_value_large_order_act,
        flow.sell_value_large_order_act,
        flow.buy_value_med_order_act,
        flow.sell_value_med_order_act,
    )
    if any(value is None for value in acts):
        return "窗口内缺主动金额字段"
    if row.adj_close is None or row.adj_preclose in (None, Decimal(0)):
        return "窗口内比率无定义"
    if sum(_nonnull(acts), Decimal(0)) == 0:
        return "窗口内 act 分母为 0"
    return None


def _nonnull(values: Sequence[Decimal | None]) -> list[Decimal]:
    return [value for value in values if value is not None]


def _own_strict_gap(day: _Day, code: str, factor: str) -> str | None:
    rows = _own_rows(day, code)
    if not rows:
        return "窗口行数不足 20"
    flows = day.flows.get(code, {})
    for row in rows:
        flow = flows.get(row.trade_dt)
        if flow is None:
            return "窗口内缺资金流行"
        gap = _moneyflowh_row_gap(flow) if factor == "moneyflowh" else _actl_row_gap(row, flow)
        if gap is not None:
            return gap
    if factor == "moneyflowh":
        return _moneyflowh_total_gap(rows, flows)
    return None


def _moneyflowh_total_gap(rows: Sequence[DailyPrice], flows: dict[date, MoneyFlow]) -> str | None:
    total = Decimal(0)
    for row in rows:
        flow = flows[row.trade_dt]
        total += sum(
            (abs(v) for v in _nonnull(_diff_cells(flow))),
            Decimal(0),
        )
    return "窗口内四类量差绝对值之和为 0" if total == 0 else None


def _diff_cells(flow: MoneyFlow) -> tuple[Decimal | None, ...]:
    return (
        flow.value_diff_institute,
        flow.value_diff_large_trader,
        flow.value_diff_med_trader,
        flow.value_diff_small_trader,
    )


def _strict_gap(day: _Day, factor: str, code: str) -> str | None:
    if factor == "abso_umr":
        return _abso_strict_gap(day, code)
    return _own_strict_gap(day, code, factor)


# ------------------------------------------------- 旧 pandas 语义模拟（仅测试内，用来证明旧值的来历）


def _legacy_moneyflowh(day: _Day, code: str, flows: dict[date, MoneyFlow]) -> Decimal | None:
    """旧仓 ``MONEYFLOWH``：每列 ``abs().sum()`` 跳过缺失行与缺失字段。``flows`` 可以是替换后的输入。"""
    rows = _own_rows(day, code)
    if not rows:
        return None
    sums = [Decimal(0), Decimal(0), Decimal(0), Decimal(0)]  # 机构、大户、中户、散户
    for row in rows:
        flow = flows.get(row.trade_dt)
        if flow is None:
            continue
        for index, value in enumerate(_diff_cells(flow)):
            if value is not None:
                sums[index] += abs(value)
    denominator = sum(sums, Decimal(0))
    if denominator == 0:
        return None
    return (sums[0] + sums[3]) / denominator


def _legacy_actlargemedcut(day: _Day, code: str, flows: dict[date, MoneyFlow]) -> Decimal | None:
    """旧仓 ``ACTLARGEMEDCUT``：``dropna()`` 删掉缺输入的行，再按 ratio 降序切前 15%，act 的均值跳过 NaN。"""
    rows = _own_rows(day, code)
    if not rows:
        return None
    ratios: list[float] = []
    acts: list[Decimal | None] = []
    for row in rows:
        flow = flows.get(row.trade_dt)
        if flow is None or row.adj_close is None or row.adj_preclose is None:
            continue
        if row.adj_preclose == 0:
            continue
        big_buy = flow.buy_value_large_order_act
        big_sell = flow.sell_value_large_order_act
        med_buy = flow.buy_value_med_order_act
        med_sell = flow.sell_value_med_order_act
        if big_buy is None or big_sell is None or med_buy is None or med_sell is None:
            continue
        total = big_buy + big_sell + med_buy + med_sell
        acts.append(None if total == 0 else (big_buy - big_sell + med_buy - med_sell) / total)
        ratios.append(float(_ratio(row.adj_close, row.adj_preclose)))
    if not ratios:
        return None
    order = legacy_descending_order(ratios)
    cut = int(actlargemedcut.CUT_RATIO * len(ratios))
    values: list[Decimal] = []
    for index in order[:cut]:
        act = acts[index]
        if act is not None:
            values.append(act)
    if cut == 0 or not values:
        return None
    return sum(values, Decimal(0)) / len(values)


def _legacy_abso_umr(day: _Day, code: str, flows: dict[date, MoneyFlow]) -> float:
    """旧仓 ``guosen_umr``：风险系数用 pandas ``rolling(10, min_periods=10)``，最终加权和 ``sum()`` 跳过 NaN。
    全部为 NaN 时 ``sum()`` 得 0，这正是 wx2 中有些旧值为 0 的来源。``flows`` 可以是替换后的输入。"""
    prices = day.prices.get(code, {})
    absop: list[float] = []
    excess: list[float] = []
    for trade_day in _window_abso(day):
        price = prices.get(trade_day)
        flow = flows.get(trade_day)
        index_row = day.index_by_day.get(trade_day)
        buy = None if flow is None else flow.buy_value_small_order_act
        amount = None if price is None else price.amount
        if buy is None or amount is None or amount == 0:
            absop.append(_NAN)
        else:
            absop.append(-(float(buy) / float(amount)))
        stock_pct = None if price is None else price.pct_change
        bench = None if index_row is None else index_row.pct_change
        excess.append(
            _NAN if stock_pct is None or bench is None else float(stock_pct) - float(bench)
        )
    series = pd.Series(absop, dtype="float64")
    coef = (series.rolling(10, min_periods=10).mean() - series).tail(RET_WINDOW)
    exp_wt = np.asarray([0.5 ** (1 / 30)] * RET_WINDOW) ** np.arange(RET_WINDOW)
    weights = exp_wt[::-1] / np.sum(exp_wt)
    excess_s = pd.Series(excess, dtype="float64").tail(RET_WINDOW)
    return float((coef * excess_s * weights).sum(skipna=True))


def _legacy_raw(
    day: _Day, factor: str, code: str, flows: dict[date, MoneyFlow] | None = None
) -> Decimal | None:
    """旧表存的是 raw（未乘 SIGN），与 wx2 的口径一致。``flows`` 缺省为本地输入。"""
    use = day.flows.get(code, {}) if flows is None else flows
    if factor == "abso_umr":
        value = _legacy_abso_umr(day, code, use)
        return Decimal(repr(value)) if math.isfinite(value) else None
    if factor == "moneyflowh":
        return _legacy_moneyflowh(day, code, use)
    return _legacy_actlargemedcut(day, code, use)


# ----------------------------------------------------------- 源数据替换重算


def _replaced_flows(
    day: _Day, code: str, rows_by_date: dict[date, _SourceRow]
) -> dict[date, MoneyFlow]:
    flows = dict(day.flows.get(code, {}))
    for trade_day, source in rows_by_date.items():
        if source.cells is None:
            # wx2 没有这一行，替换后本地也没有这一行。
            flows.pop(trade_day, None)
        else:
            flows[trade_day] = _flow_from_cells(trade_day, code, source.cells)
    return flows


def _recompute(day: _Day, factor: str, code: str, flows: dict[date, MoneyFlow]) -> Decimal | None:
    """本仓同一计算函数（严格口径）在给定资金流上的结果，已按旧表精度量化。"""
    contracts = {
        "price": _contract("price"),
        "money_flow": _contract("money_flow"),
        "index": _contract("index"),
    }
    if factor == "abso_umr":
        value = abso_umr_from_maps(
            _window_abso(day),
            price_by_day=day.prices.get(code, {}),
            flow_by_day=flows,
            index_by_day=day.index_by_day,
            asset_id=code,
            price_contract=contracts["price"],
            money_flow_contract=contracts["money_flow"],
            index_contract=contracts["index"],
        )
        return None if value is None else _quantize(_local_raw(factor, value.value), SCALE[factor])
    window = list(_own_rows(day, code))
    if not window:
        return None
    if factor == "moneyflowh":
        result_h = moneyflowh.moneyflowh_value(
            window,
            flows,
            price_contract=contracts["price"],
            money_flow_contract=contracts["money_flow"],
        )
        return None if result_h is None else _quantize(SIGN[factor] * result_h.raw, SCALE[factor])
    result_c = actlargemedcut.actlargemedcut_value(
        window,
        flows,
        price_contract=contracts["price"],
        money_flow_contract=contracts["money_flow"],
    )
    return None if result_c is None else _quantize(SIGN[factor] * result_c.raw, SCALE[factor])


def _window_dates(day: _Day, factor: str, code: str) -> set[date]:
    if factor == "abso_umr":
        return set(_window_abso(day))
    return {row.trade_dt for row in _own_rows(day, code)}


def _old_and_new(day: _Day, factor: str, code: str) -> tuple[Decimal | None, Decimal | None]:
    old = day.fixture.old[factor].get(code)
    raw_new = day.produced.get((FEATURE_ID[factor], code))
    old_q = None if old is None else _quantize(old, SCALE[factor])
    new = None if raw_new is None else _quantize(_local_raw(factor, raw_new), SCALE[factor])
    return old_q, new


def _adjudicated(
    day: _Day, factor: str, code: str, old: Decimal, gap: str
) -> tuple[str, str] | None:
    """旧语义模拟（本地输入）复现旧值时才是已裁定。否则返回 None，交给源数据路径判断。"""
    legacy = _legacy_raw(day, factor, code)
    if legacy is not None and _quantize(legacy, SCALE[factor]) == old:
        return "已裁定", gap
    return None


def _source_explained(
    day: _Day,
    factor: str,
    code: str,
    old: Decimal | None,
    rows_by_date: dict[date, _SourceRow],
) -> tuple[str, str]:
    """用 wx2 原始行替换本地对应行，证明差异来自输入。两条路径任一复现旧值即可：
    1. 本仓同一计算函数（严格口径）重算。
    2. 旧 pandas 语义模拟（跳过缺失）在替换后的输入上计算。
    路径 2 用于 wx2 中整段无行的股票：严格口径无值，旧 ``sum()`` 得 0。两条路径的结果都写进原因。"""
    replaced = _replaced_flows(day, code, rows_by_date)
    recomputed = _recompute(day, factor, code, replaced)
    if recomputed == old:
        return "源数据差异", f"替换 {len(rows_by_date)} 行 wx2 原始行后，本仓重算复现旧值"
    legacy = _legacy_raw(day, factor, code, replaced)
    legacy_q = None if legacy is None else _quantize(legacy, SCALE[factor])
    if legacy_q == old:
        return "源数据差异", f"替换 {len(rows_by_date)} 行 wx2 原始行后，旧语义模拟复现旧值"
    return (
        "其他",
        f"替换 wx2 原始行后两条路径都不复现旧值（本仓 {recomputed}，旧语义 {legacy_q}，旧 {old}）",
    )


def _classify(
    day: _Day,
    factor: str,
    code: str,
    source_by_key: dict[tuple[date, str], _SourceRow],
) -> tuple[str, str]:
    """返回 (类别, 原因)。"""
    old, new = _old_and_new(day, factor, code)
    if old is None and new is None:
        return "一致", "双方无值"
    if old is not None and old == new:
        return "一致", "精确"
    gap = _strict_gap(day, factor, code) if old is not None and new is None else None
    if old is not None and gap is not None:
        adjudicated = _adjudicated(day, factor, code, old, gap)
        if adjudicated is not None:
            return adjudicated
    window = _window_dates(day, factor, code)
    rows_by_date = {
        trade_day: source_by_key[(trade_day, code)]
        for trade_day in window
        if (trade_day, code) in source_by_key
    }
    if rows_by_date:
        return _source_explained(day, factor, code, old, rows_by_date)
    return _unexplained(old, new, gap)


def _unexplained(old: Decimal | None, new: Decimal | None, gap: str | None) -> tuple[str, str]:
    if gap is not None:
        return "其他", f"窗口有缺失（{gap}），旧语义模拟不复现旧值，窗口内也无 wx2 源行差异"
    if old is None:
        return "其他", "新有值、wx2 无行，窗口内无 wx2 源行差异"
    if new is None:
        return "其他", "旧有值、新无值，窗口内无缺失也无源行差异"
    return "其他", "两侧有值但不等，窗口内无 wx2 源行差异"


def _run_day(ctx: _Context, day: date) -> dict[str, Any]:
    data = ctx.day(day)
    source_by_key = {(row.day, row.code): row for row in ctx.source_rows}
    summary: dict[str, Any] = {}
    for factor in FACTORS:
        counts: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        samples: dict[str, list[str]] = {category: [] for category in CATEGORIES}
        local_values = 0
        for code in sorted(data.scope):
            if (FEATURE_ID[factor], code) in data.produced:
                local_values += 1
            category, reason = _classify(data, factor, code, source_by_key)
            counts[category] += 1
            if category != "一致":
                reasons[f"{category}:{reason.split('（')[0].split('：')[0]}"] += 1
                if len(samples[category]) < _FAILURE_LIST_LIMIT:
                    samples[category].append(f"{code} {reason}")
        wx2_in_scope = sum(1 for value in data.fixture.old[factor].values() if value is not None)
        summary[factor] = {
            "wx2_rows_in_scope": wx2_in_scope,
            "local_values": local_values,
            "counts": dict(counts),
            "reasons": dict(reasons),
            "samples": {key: value for key, value in samples.items() if value},
        }
    return summary


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_moneyflow_factors_match_wx2_with_adjudicated_differences_only(
    ctx: _Context, day: date
) -> None:
    started = time.perf_counter()
    summary = _run_day(ctx, day)
    others: dict[str, list[str]] = {}
    for factor in FACTORS:
        info = summary[factor]
        counts = info["counts"]
        print(
            f"\n[{day.isoformat()}] {factor}: scope={len(ctx.day(day).scope)} "
            f"wx2_in_scope={info['wx2_rows_in_scope']} local={info['local_values']} "
            f"一致={counts.get('一致', 0)} 已裁定={counts.get('已裁定', 0)} "
            f"源数据差异={counts.get('源数据差异', 0)} 其他={counts.get('其他', 0)}"
        )
        for key, value in sorted(info["reasons"].items()):
            print(f"    {key} = {value}")
        if counts.get("其他", 0):
            others[factor] = info["samples"].get("其他", [])
    print(f"[{day.isoformat()}] elapsed={time.perf_counter() - started:.1f}s")
    assert not others, {factor: items[:_FAILURE_LIST_LIMIT] for factor, items in others.items()}


@pytest.mark.integration
@pytest.mark.parametrize("day", GOLDEN_DAYS, ids=lambda d: d.isoformat())
def test_source_rows_in_window_differ_from_local(ctx: _Context, day: date) -> None:
    """窗口内存下来的 wx2 源行，本地对应行必须确实不同。否则它不构成源数据差异的证据。
    本地缺行（一侧有行、另一侧无行）不在这里比较字段，由分类函数按替换重算处理。"""
    data = ctx.day(day)
    window = set(_window_abso(data))
    checked = 0
    for source in ctx.source_rows:
        if source.code not in data.scope or source.day not in window:
            continue
        local_row = data.flows.get(source.code, {}).get(source.day)
        if local_row is None or source.cells is None:
            continue
        local_cells = tuple(getattr(local_row, field) for field in SOURCE_FIELDS)
        assert local_cells != source.cells, (source.day, source.code)
        checked += 1
    print(f"\n[{day.isoformat()}] 窗口内源行与本地确有差异 {checked} 条")
