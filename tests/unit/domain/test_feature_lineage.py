"""因子血缘推导：knowledge_dt 取最晚可见日，pit_grade 沿依赖图木桶取最差。"""

from __future__ import annotations

import itertools
from datetime import date

import pytest

from quantagent.domain.errors import FeatureLookupError
from quantagent.domain.feature_lineage import derive_feature_lineage

_GRADE_ORDER = "ABCD"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("grades", "expected"),
    [
        (("A",), "A"),
        (("B",), "B"),
        (("C",), "C"),
        (("D",), "D"),
        (("A", "B"), "B"),
        (("B", "C", "A"), "C"),
        (("A", "D", "C"), "D"),
        (("A", "A", "A"), "A"),
    ],
)
def test_single_layer_takes_worst_grade(grades: tuple[str, ...], expected: str) -> None:
    inputs = [(date(2024, 1, index + 1), grade) for index, grade in enumerate(grades)]
    assert derive_feature_lineage(inputs)[1] == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "grades",
    list(itertools.product(_GRADE_ORDER, repeat=3)),
    ids=["".join(combo) for combo in itertools.product(_GRADE_ORDER, repeat=3)],
)
def test_single_layer_matches_worst_for_every_combination(grades: tuple[str, ...]) -> None:
    inputs = [(date(2024, 1, index + 1), grade) for index, grade in enumerate(grades)]
    worst = max(grades, key=_GRADE_ORDER.index)
    assert derive_feature_lineage(inputs)[1] == worst


@pytest.mark.unit
def test_single_d_input_makes_output_d_in_any_position() -> None:
    base = [(date(2024, 1, 2), "A"), (date(2024, 1, 3), "A"), (date(2024, 1, 4), "A")]
    for position in range(len(base)):
        inputs = list(base)
        inputs[position] = (inputs[position][0], "D")
        assert derive_feature_lineage(inputs)[1] == "D"


@pytest.mark.unit
def test_grade_result_ignores_input_order() -> None:
    items = [(date(2024, 1, 2), "A"), (date(2024, 1, 5), "D"), (date(2024, 1, 3), "B")]
    results = {derive_feature_lineage(list(order)) for order in itertools.permutations(items)}
    assert results == {(date(2024, 1, 5), "D")}


# 依赖图：p(A)、q(B)、r(D) 为原始输入；f1=derive(p,q)，f2=derive(q,r)，g=derive(f1,f2)。
_P = (date(2024, 1, 5), "A")
_Q = (date(2024, 1, 8), "B")
_R = (date(2024, 1, 10), "D")


@pytest.mark.unit
def test_dag_propagates_d_from_leaf_to_top() -> None:
    f1 = derive_feature_lineage([_P, _Q])
    f2 = derive_feature_lineage([_Q, _R])
    g = derive_feature_lineage([f1, f2])

    assert f1 == (date(2024, 1, 8), "B")
    assert f2 == (date(2024, 1, 10), "D")
    assert g == (date(2024, 1, 10), "D")


@pytest.mark.unit
def test_dag_without_d_keeps_b_at_top() -> None:
    # 对照图：把 r 换成 A 级，顶层应为 B。证明上一条的 D 来自输入，不是常量输出。
    r_a = (_R[0], "A")
    f1 = derive_feature_lineage([_P, _Q])
    f2 = derive_feature_lineage([_Q, r_a])
    g = derive_feature_lineage([f1, f2])

    assert f2 == (date(2024, 1, 10), "B")
    assert g == (date(2024, 1, 10), "B")


@pytest.mark.unit
def test_knowledge_dt_is_latest_visible_date_along_path() -> None:
    # 顶层可见日取两条上游中较晚者，即便较早的上游先被传入。
    early = (date(2024, 1, 2), "A")
    late = (date(2024, 1, 20), "A")
    assert derive_feature_lineage([early, late])[0] == date(2024, 1, 20)
    assert derive_feature_lineage([late, early])[0] == date(2024, 1, 20)


@pytest.mark.unit
def test_extra_lag_pushes_knowledge_dt_later_only() -> None:
    inputs = [(date(2024, 1, 10), "A"), (date(2024, 1, 8), "B")]
    assert derive_feature_lineage(inputs) == (date(2024, 1, 10), "B")
    assert derive_feature_lineage(inputs, extra_lag_days=0) == (date(2024, 1, 10), "B")
    assert derive_feature_lineage(inputs, extra_lag_days=3) == (date(2024, 1, 13), "B")


@pytest.mark.unit
def test_negative_extra_lag_is_rejected() -> None:
    with pytest.raises(FeatureLookupError, match="不允许把 knowledge_dt 提前"):
        derive_feature_lineage([(date(2024, 1, 10), "A")], extra_lag_days=-1)


@pytest.mark.unit
def test_empty_inputs_are_rejected() -> None:
    with pytest.raises(FeatureLookupError, match="没有输入"):
        derive_feature_lineage([])


@pytest.mark.unit
@pytest.mark.parametrize("grade", ["E", "a", "", " A", "AA"])
def test_unknown_grade_is_rejected(grade: str) -> None:
    with pytest.raises(FeatureLookupError, match="未知 pit_grade"):
        derive_feature_lineage([(date(2024, 1, 10), "A"), (date(2024, 1, 11), grade)])
