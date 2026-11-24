"""旧仓 ``sort_values(ascending=False)`` 的并列顺序：与 pandas 2.3.3 逐下标一致。

对拍对象是本机 pandas 的 ``Series.sort_values(ascending=False).index``。pandas 降序先翻转数组、
再做 quicksort、最后翻转回来（``pandas/core/sorting.py`` 第 436–441 行），移植必须跟着这条路径走。
"""

from __future__ import annotations

import random

import pandas as pd
import pytest

from quantagent.features.library._legacy_sort import legacy_descending_order


def _pandas_descending(keys: list[float]) -> list[int]:
    return [int(i) for i in pd.Series(keys, dtype="float64").sort_values(ascending=False).index]


@pytest.mark.unit
@pytest.mark.parametrize("length", range(1, 41))
def test_descending_matches_pandas_with_many_ties(length: int) -> None:
    rng = random.Random(20261125 + length)
    for _ in range(40):
        distinct = rng.sample(range(1, 40), rng.choice([2, 3, 4, 5]))
        keys = [float(rng.choice(distinct)) for _ in range(length)]
        assert legacy_descending_order(keys) == _pandas_descending(keys)


@pytest.mark.unit
@pytest.mark.parametrize("length", range(1, 41))
def test_descending_matches_pandas_on_random_floats(length: int) -> None:
    rng = random.Random(11 + length)
    for _ in range(20):
        keys = [rng.random() for _ in range(length)]
        assert legacy_descending_order(keys) == _pandas_descending(keys)


@pytest.mark.unit
def test_descending_matches_pandas_on_long_tie_heavy_arrays() -> None:
    # 长于 16 的数组会进入分区路径，这里覆盖 quicksort 的分区与插入排序两段。
    rng = random.Random(4242)
    for length in (17, 33, 64, 129, 257):
        for _ in range(30):
            keys = [float(rng.randint(0, 6)) for _ in range(length)]
            assert legacy_descending_order(keys) == _pandas_descending(keys)


@pytest.mark.unit
def test_descending_of_empty_input_is_empty() -> None:
    assert legacy_descending_order([]) == []
