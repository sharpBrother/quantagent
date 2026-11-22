"""``pf_single_cutamp_1_mean_neg``。
旧仓 ``CUTAMP.cal`` 用 20 个交易日的高低价振幅，去掉收盘触及涨跌停的日子，
按复权收盘价切出高低两端各 25% 的振幅差。Current-20 消费的是这个值的相反数，
窗口为 1。缺失不落成 0。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

from quantagent.domain.feature_lineage import derive_feature_lineage
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.prices.types import DailyPrice

FEATURE_ID = "pf_single_cutamp_1_mean_neg"
# v2：并列的复权收盘价改按旧仓 quicksort 顺序切段，v1 行保留为历史，不改不删。
DEFINITION_VERSION = "v2"
WINDOW = 20
MIN_KEPT = 10
CUT_RATIO = Decimal("0.25")
SIGN = Decimal("-1")

PARAMS = {
    "window": WINDOW,
    "min_kept": MIN_KEPT,
    "cut_ratio": format(CUT_RATIO, "f"),
    "sign": format(SIGN, "f"),
    "mean_window": 1,
}
PARAM_HASH = digest_json(PARAMS)


@dataclass(frozen=True)
class CutampValue:
    event_dt: date
    asset_id: str
    raw: Decimal
    value: Decimal
    knowledge_dt: date
    pit_grade: str


def cutamp_value(
    window: Sequence[DailyPrice],
    *,
    contract: VisibilityContract,
) -> CutampValue | None:
    """窗口必须已经按交易日排好，且最后一天是截面日。不够 20 日则缺失。"""
    if len(window) < WINDOW:
        return None
    rows = tuple(window[-WINDOW:])
    raw = _raw_cutamp(rows)
    if raw is None:
        return None
    grade = contract.visibility.grade
    knowledge_dt, pit_grade = derive_feature_lineage(tuple((row.trade_dt, grade) for row in rows))
    return CutampValue(
        event_dt=rows[-1].trade_dt,
        asset_id=rows[-1].wind_code,
        raw=raw,
        value=SIGN * raw,
        knowledge_dt=knowledge_dt,
        pit_grade=pit_grade,
    )


def _raw_cutamp(rows: Sequence[DailyPrice]) -> Decimal | None:
    # kept 保持输入的交易日顺序，排序只决定切段时的先后。
    keys: list[float] = []
    amplitudes: list[Decimal] = []
    for row in rows:
        if row.close is None or row.high is None or row.low is None or row.adj_close is None:
            continue
        if row.low == 0:
            return None
        if row.close in {row.limit_up, row.limit_down}:
            continue
        amplitudes.append(Decimal(100) * (row.high / row.low - 1))
        # 旧仓比较的是 float64 的复权收盘价，这里用同样的精度作排序键。
        keys.append(float(row.adj_close))
    if len(keys) < MIN_KEPT:
        return None
    # 复权收盘价并列时，切段取哪一只取决于排序算法。旧仓 pandas sort_values 默认 quicksort，
    # 并列顺序是 quicksort 的产物，不是交易日顺序。2024-01-05 全市场对拍里，无并列的股票全部一致，
    # 差异只出现在并列上；2024-02-02 的 000001.SZ 也是这样，所以这里复现 quicksort 的顺序。
    order = _legacy_quicksort_order(keys)
    cut = int(CUT_RATIO * len(order))
    if cut == 0:
        return None
    low_mean = sum((amplitudes[i] for i in order[:cut]), Decimal(0)) / cut
    high_mean = sum((amplitudes[i] for i in order[-cut:]), Decimal(0)) / cut
    return high_mean - low_mean


# numpy 的 quicksort 对 float64 有 SIMD 实现：x86 AVX-512 上 argsort 会走 x86-simd-sort，
# 并列元素的先后随机器变。这里不用 sorted 或 np.argsort，而是逐行移植标量 aquicksort_
# （numpy/_core/src/npysort/quicksort.cpp），让同一输入在任何机器上给出同一顺序。
# numpy 的 SMALL_QUICKSORT 是 15，即段长大于 16 才分区。取 16 会在 17 个元素的并列输入上与 numpy 不一致（已对拍）。
_SMALL_QUICKSORT = 15


def _less(a: float, b: float) -> bool:
    # 与 numpy 的 float 比较一致：NaN 排在最后。
    return a < b or (math.isnan(b) and not math.isnan(a))


def _legacy_quicksort_order(keys: Sequence[float]) -> list[int]:
    """返回与 ``np.argsort(keys, kind="quicksort")`` 相同的下标顺序（标量路径）。"""
    n = len(keys)
    tosort = list(range(n))
    if n == 0:
        return tosort
    pl, pr = 0, n - 1
    stack: list[tuple[int, int, int]] = []
    # cdepth 是 introsort 的递归深度上限：2 * floor(log2(n))。超过后改用堆排序，避免最坏情形。
    cdepth = (n.bit_length() - 1) * 2
    while True:
        if cdepth < 0:
            # numpy 此处转堆排序。堆排序的并列顺序尚未移植准确，cutamp 窗口最多 20 个元素，
            # 深度上限 8、实际分区不超过 4 层，到不了这里。真到了就停下，不给一个对不上旧仓的顺序。
            raise ValueError(f"quicksort 递归深度超限（n={n}），堆排序兜底未移植")
        else:
            while pr - pl > _SMALL_QUICKSORT:
                pi = _partition(keys, tosort, pl, pr)
                cdepth -= 1
                # 较大的一段入栈，较小的一段继续处理，栈深度因此是 O(log n)。
                if pi - pl < pr - pi:
                    stack.append((pi + 1, pr, cdepth))
                    pr = pi - 1
                else:
                    stack.append((pl, pi - 1, cdepth))
                    pl = pi + 1
            _insertion_sort(keys, tosort, pl, pr)
        if not stack:
            break
        pl, pr, cdepth = stack.pop()
    return tosort


def _partition(keys: Sequence[float], tosort: list[int], pl: int, pr: int) -> int:
    """numpy 的一次分区：三数取中选枢轴，返回枢轴在最终顺序中的位置。"""
    pm = pl + ((pr - pl) >> 1)
    if _less(keys[tosort[pm]], keys[tosort[pl]]):
        _swap(tosort, pm, pl)
    if _less(keys[tosort[pr]], keys[tosort[pm]]):
        _swap(tosort, pr, pm)
    if _less(keys[tosort[pm]], keys[tosort[pl]]):
        _swap(tosort, pm, pl)
    vp = keys[tosort[pm]]
    pi = pl
    pj = pr - 1
    _swap(tosort, pm, pj)
    # 对应 C 里的 do-while：先自增（自减）再判断，所以不能直接写成 while 条件。
    while True:
        pi += 1
        while _less(keys[tosort[pi]], vp):
            pi += 1
        pj -= 1
        while _less(vp, keys[tosort[pj]]):
            pj -= 1
        if pi >= pj:
            break
        _swap(tosort, pi, pj)
    _swap(tosort, pi, pr - 1)
    return pi


def _insertion_sort(keys: Sequence[float], tosort: list[int], pl: int, pr: int) -> None:
    for pi in range(pl + 1, pr + 1):
        vi = tosort[pi]
        vp = keys[vi]
        pj = pi
        while pj > pl and _less(vp, keys[tosort[pj - 1]]):
            tosort[pj] = tosort[pj - 1]
            pj -= 1
        tosort[pj] = vi


def _swap(items: list[int], i: int, j: int) -> None:
    items[i], items[j] = items[j], items[i]
