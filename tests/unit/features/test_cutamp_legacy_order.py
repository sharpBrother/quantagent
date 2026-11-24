"""旧仓 quicksort 排序顺序的移植：与 numpy 的 quicksort 逐下标一致。

对拍对象是本机 numpy 的 ``np.argsort(kind="quicksort")``。本机是 arm64，走标量 ``aquicksort_``，
与移植的算法路径相同。若在 x86 AVX-512 上 numpy 会走 SIMD 排序，这里的对拍不再代表那条路径；
cutamp 本身不依赖 numpy，结果只由移植决定。
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from quantagent.features.library._legacy_sort import (
    legacy_quicksort_order as _legacy_quicksort_order,
)


def _numpy_quicksort(keys: list[float]) -> list[int]:
    order = np.argsort(np.array(keys, dtype=np.float64), kind="quicksort")
    return [int(i) for i in order]


@pytest.mark.unit
@pytest.mark.parametrize("length", range(1, 41))
def test_order_matches_numpy_quicksort_with_many_ties(length: int) -> None:
    # 只从很小的取值集合里抽，制造大量并列；并列顺序正是这里要复现的部分。
    rng = random.Random(20241105 + length)
    for _ in range(40):
        distinct = rng.sample(range(1, 40), rng.choice([3, 4, 5]))
        keys = [float(rng.choice(distinct)) for _ in range(length)]
        assert _legacy_quicksort_order(keys) == _numpy_quicksort(keys)


@pytest.mark.unit
@pytest.mark.parametrize("length", range(1, 41))
def test_order_matches_numpy_quicksort_on_random_floats(length: int) -> None:
    rng = random.Random(7 + length)
    for _ in range(20):
        keys = [rng.random() for _ in range(length)]
        assert _legacy_quicksort_order(keys) == _numpy_quicksort(keys)


@pytest.mark.unit
@pytest.mark.parametrize(
    "keys",
    [
        [1.0] * 25,
        [float(i) for i in range(30)],
        [float(i) for i in range(30, 0, -1)],
        [float(i % 3) for i in range(33)],
        [],
    ],
    ids=["all_equal", "sorted", "reversed", "periodic_ties", "empty"],
)
def test_order_matches_numpy_on_special_shapes(keys: list[float]) -> None:
    assert _legacy_quicksort_order(keys) == _numpy_quicksort(keys)


@pytest.mark.unit
def test_order_is_a_permutation_with_distinct_keys_sorted() -> None:
    # 不并列时顺序唯一，任何正确的排序都应给出同一结果。这里不依赖 numpy。
    rng = random.Random(99)
    keys = [rng.random() for _ in range(200)]
    order = _legacy_quicksort_order(keys)
    assert sorted(order) == list(range(200))
    assert [keys[i] for i in order] == sorted(keys)
