"""复现旧仓 pandas ``sort_values`` 的并列顺序。

旧仓因子切段时并列元素谁先谁后，取决于排序算法，不取决于交易日顺序。这里只保留两条路径：

- ``legacy_quicksort_order``：``np.argsort(kind="quicksort")`` 在 float64 上的标量路径，逐行移植。
- ``legacy_descending_order``：``DataFrame.sort_values(by, ascending=False)`` 单列时的
  ``nargsort`` 降序路径，即先翻转、再 quicksort、最后翻转回来。

移植而不直接调用 numpy：numpy 在 x86 AVX-512 上会走 SIMD 排序，并列顺序随机器变，
同一输入在不同机器上可能得到不同切段结果，违反 AGENTS.md §7.8。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# numpy 的 SMALL_QUICKSORT 是 15，即段长大于 16 才分区。取 16 会在 17 个元素的并列输入上与 numpy 不一致（已对拍）。
_SMALL_QUICKSORT = 15


def legacy_descending_order(keys: Sequence[float]) -> list[int]:
    """返回与 ``pd.Series(keys).sort_values(ascending=False).index`` 相同的下标顺序。

    pandas 2.3.3 的 ``nargsort``（``pandas/core/sorting.py`` 第 436–441 行）在降序时先把
    值与下标同时翻转，对翻转后的值做 ``argsort(kind="quicksort")``，再把结果整体翻转。
    这里照做，所以并列元素的先后与旧仓一致。
    """
    n = len(keys)
    reversed_order = legacy_quicksort_order(list(keys)[::-1])
    # 翻转后位置 j 对应原始下标 n-1-j。
    indexer = [n - 1 - j for j in reversed_order]
    return indexer[::-1]


def legacy_quicksort_order(keys: Sequence[float]) -> list[int]:
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


def _less(a: float, b: float) -> bool:
    # 与 numpy 的 float 比较一致：NaN 排在最后。
    return a < b or (math.isnan(b) and not math.isnan(a))


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
