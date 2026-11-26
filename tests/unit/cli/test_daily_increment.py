"""日更增量的计划与执行：水位线为空报错、就绪截止、前瞻收益成熟区间、区间为空不写。

水位线、开市日历、就绪快照都用替身，不连 PG，也不读 lake。物化函数用替身捕获参数。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from quantagent.adapters.lake.feature_value import LakeFeatureRepository
from quantagent.adapters.lake.forward_return import LakeForwardReturnRepository
from quantagent.cli import daily_increment as d
from quantagent.cli.app import app
from quantagent.domain.errors import IncrementError
from quantagent.domain.incremental import ReadinessData

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _opens(count: int, start: date = date(2026, 1, 1)) -> tuple[date, ...]:
    return tuple(start + timedelta(days=offset) for offset in range(count))


def _paths(tmp_path: Any) -> Any:
    """只含 ``lake`` 与 ``runs`` 的替身，计划函数与 run log 只用到这两个。"""
    return cast("Any", SimpleNamespace(lake=tmp_path / "lake", runs=tmp_path / "runs"))


_DAILY_SOURCES = (
    "ashareeodprices",
    "ashareeodderivativeindicator",
    "asharemoneyflow",
    "aindexeodprices",
)


def _fake_readiness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    counts: dict[str, dict[date, int]] | None = None,
    minute_days: frozenset[date] = frozenset(),
) -> None:
    """未指定的源默认每日完整（100 行），只覆盖测试关心的那一个源。"""

    def _readiness(_settings: object, *, as_of: date, opens: tuple[date, ...], **_: object) -> Any:
        filled: dict[str, dict[date, int]] = {
            name: dict.fromkeys(opens, 100) for name in _DAILY_SOURCES
        }
        filled.update(counts or {})
        return ReadinessData(opens=opens, counts=filled, minute_days=minute_days)

    monkeypatch.setattr(d, "_readiness", _readiness)


def _feature_id() -> str:
    return d.FEATURE_INCREMENTS[0].feature_id


@pytest.mark.unit
def test_empty_lake_watermark_is_an_error_not_a_full_recompute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(LakeFeatureRepository, "latest_event_dt", lambda *_a, **_k: None)
    with pytest.raises(IncrementError, match="历史回填"):
        d.plan_feature_increment(
            cast("Any", None), _paths(tmp_path), feature_id=_feature_id(), as_of=date(2026, 1, 9)
        )


@pytest.mark.unit
def test_feature_plan_stops_at_first_unready_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    opens = _opens(15)
    last = opens[6]
    monkeypatch.setattr(LakeFeatureRepository, "latest_event_dt", lambda *_a, **_k: last)
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)
    # 第 11 个开市日的价格缺行；它之后即使完整也不计入。
    prices = dict.fromkeys(opens, 100)
    prices[opens[10]] = 0
    prices[opens[12]] = 100
    _fake_readiness(monkeypatch, counts={"ashareeodprices": prices})

    plan = d.plan_feature_increment(
        cast("Any", None), _paths(tmp_path), feature_id=_feature_id(), as_of=opens[14]
    )

    assert plan.last_event == last
    assert plan.start == opens[7]
    assert plan.cutoff == opens[9]
    assert plan.materialize_as_of == opens[9]
    assert plan.blocked_on == opens[10]
    assert plan.writes is True
    assert plan.reason == f"输入 {opens[10].isoformat()} 未就绪，本次截止在 {opens[9].isoformat()}"


@pytest.mark.unit
def test_no_new_open_day_is_skipped_without_touching_pg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    opens = _opens(10)
    monkeypatch.setattr(LakeFeatureRepository, "latest_event_dt", lambda *_a, **_k: opens[-1])
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)

    def _must_not_connect(*_a: object, **_k: object) -> Any:
        raise AssertionError("没有候选日时不应连接 PG")

    monkeypatch.setattr(d, "connect", _must_not_connect)

    plan = d.plan_feature_increment(
        cast("Any", None), _paths(tmp_path), feature_id=_feature_id(), as_of=opens[-1]
    )

    assert plan.writes is False
    assert plan.start is None
    assert plan.reason.startswith("无新数据")


@pytest.mark.unit
def test_feature_blocked_on_first_day_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    opens = _opens(15)
    monkeypatch.setattr(LakeFeatureRepository, "latest_event_dt", lambda *_a, **_k: opens[6])
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)
    _fake_readiness(monkeypatch, counts={"ashareeodprices": {}})

    plan = d.plan_feature_increment(
        cast("Any", None), _paths(tmp_path), feature_id=_feature_id(), as_of=opens[14]
    )

    assert plan.writes is False
    assert plan.blocked_on == opens[7]
    assert plan.reason == f"输入 {opens[7].isoformat()} 未就绪，本次不写"


@pytest.mark.unit
def test_forward_return_stops_when_start_or_end_price_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    opens = _opens(15)
    monkeypatch.setattr(LakeForwardReturnRepository, "latest_event_dt", lambda *_a, **_k: opens[6])
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)
    # 1d 的信号 T 需要 T+1 与 T+2 两天行情。opens[10] 缺行：T=opens[8] 的终点、T=opens[9] 的起点都受影响。
    prices = dict.fromkeys(opens, 100)
    prices[opens[10]] = 0
    _fake_readiness(monkeypatch, counts={"ashareeodprices": prices})

    plan = d.plan_forward_return_increment(
        cast("Any", None), _paths(tmp_path), horizon="1d", as_of=opens[14]
    )

    assert plan.start == opens[7]
    assert plan.cutoff == opens[7]
    # 物化 as_of 是截止信号日的终点，只读到这一天的行情。
    assert plan.materialize_as_of == opens[9]
    assert plan.blocked_on == opens[8]
    assert "信号日" in plan.reason


@pytest.mark.unit
def test_forward_return_signal_without_calendar_end_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # 日历只到 as_of。最后一个开市日作为信号时，终点在日历之外，不能判为成熟。
    opens = _opens(12)
    monkeypatch.setattr(LakeForwardReturnRepository, "latest_event_dt", lambda *_a, **_k: opens[6])
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)
    _fake_readiness(monkeypatch, counts={"ashareeodprices": dict.fromkeys(opens, 100)})

    plan = d.plan_forward_return_increment(
        cast("Any", None), _paths(tmp_path), horizon="1d", as_of=opens[11]
    )

    assert plan.cutoff == opens[9]
    assert plan.materialize_as_of == opens[11]
    assert plan.blocked_on == opens[10]


@pytest.mark.unit
def test_all_a_factor_is_blocked_when_derivative_indicator_is_partial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # all_a 成员由当日衍生指标代码决定：衍生指标缺行时，即使行情完整也不能算。
    opens = _opens(15)
    monkeypatch.setattr(LakeFeatureRepository, "latest_event_dt", lambda *_a, **_k: opens[6])
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)
    derivative = dict.fromkeys(opens, 5580)
    derivative[opens[10]] = 100
    _fake_readiness(monkeypatch, counts={"ashareeodderivativeindicator": derivative})

    plan = d.plan_feature_increment(
        cast("Any", None), _paths(tmp_path), feature_id=_feature_id(), as_of=opens[14]
    )

    assert "ashareeodderivativeindicator" in plan.inputs
    assert plan.cutoff == opens[9]
    assert plan.blocked_on == opens[10]


@pytest.mark.unit
def test_forward_return_signal_day_needs_derivative_for_all_a_membership(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    opens = _opens(15)
    monkeypatch.setattr(LakeForwardReturnRepository, "latest_event_dt", lambda *_a, **_k: opens[6])
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)
    # 信号日 opens[8] 的衍生指标缺行：它的行情完整，但 all_a 成员不完整，本次不能算到它。
    derivative = dict.fromkeys(opens, 5580)
    derivative[opens[8]] = 0
    _fake_readiness(monkeypatch, counts={"ashareeodderivativeindicator": derivative})

    plan = d.plan_forward_return_increment(
        cast("Any", None), _paths(tmp_path), horizon="1d", as_of=opens[14]
    )

    assert plan.blocked_on == opens[8]
    assert plan.cutoff == opens[7]


@pytest.mark.unit
def test_forward_return_passes_only_its_horizon_to_materializer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    opens = _opens(15)
    plan = d.IncrementPlan(
        name="forward_return:5d",
        as_of=opens[14],
        last_event=opens[6],
        start=opens[7],
        cutoff=opens[7],
        materialize_as_of=opens[13],
        blocked_on=None,
        reason="",
        inputs=("ashareeodprices",),
    )
    monkeypatch.setattr(d, "plan_forward_return_increment", lambda *_a, **_k: plan)
    captured: dict[str, object] = {}

    def _fake(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(row_count=4, digest="dig")

    monkeypatch.setattr(d, "materialize_forward_return_cli", _fake)

    result = d.run_forward_return_increment(
        cast("Any", None), _paths(tmp_path), horizon="5d", as_of=opens[14]
    )

    assert captured["horizons"] == ("5d",)
    assert captured["start"] == opens[7]
    assert captured["end"] == opens[7]
    assert captured["as_of"] == opens[13]
    assert captured["wind_codes"] is None
    assert result.row_count == 4


@pytest.mark.unit
def test_skipped_run_does_not_materialize_or_write_run_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    opens = _opens(10)
    monkeypatch.setattr(LakeFeatureRepository, "latest_event_dt", lambda *_a, **_k: opens[-1])
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("不应物化")

    monkeypatch.setattr(d, "_materialize_feature", _boom)

    result = d.run_feature_increment(
        cast("Any", None), _paths(tmp_path), feature_id=_feature_id(), as_of=opens[-1]
    )

    assert result.row_count is None
    assert result.metadata()["status"] == "skipped"
    assert not (tmp_path / "runs").exists()


@pytest.mark.unit
def test_written_run_persists_run_log_with_rows_and_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    opens = _opens(15)
    monkeypatch.setattr(LakeFeatureRepository, "latest_event_dt", lambda *_a, **_k: opens[6])
    monkeypatch.setattr(d, "_open_days", lambda *_a, **_k: opens)
    _fake_readiness(monkeypatch, counts={"ashareeodprices": dict.fromkeys(opens, 100)})
    monkeypatch.setattr(d, "_materialize_feature", lambda *_a, **_k: (42, "digest-x"))

    result = d.run_feature_increment(
        cast("Any", None), _paths(tmp_path), feature_id=_feature_id(), as_of=opens[14]
    )

    assert result.row_count == 42
    meta = result.metadata()
    assert meta["status"] == "written"
    assert meta["start"] == opens[7].isoformat()
    assert meta["cutoff"] == opens[14].isoformat()
    assert meta["row_count"] == 42
    logs = list((tmp_path / "runs").glob("*.json"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert '"action": "lake.daily_increment"' in text
    assert '"output_digest": "digest-x"' in text
    assert '"row_count": 42' in text


@pytest.mark.unit
def test_registry_has_eighteen_distinct_factor_identities() -> None:
    ids = [item.feature_id for item in d.FEATURE_INCREMENTS]
    identities = {
        (item.feature_id, item.definition_version, item.param_hash) for item in d.FEATURE_INCREMENTS
    }
    assert len(ids) == len(set(ids)) == 18
    assert len(identities) == 18
    kinds = {item.feature_id: item.materializer for item in d.FEATURE_INCREMENTS}
    assert kinds["pf_single_abso_umr_1_mean_pos"] == "moneyflow"
    assert kinds["pf_single_core_up_20_mean_pos_neut_pxret21"] == "minute_2b"
    assert kinds["pf_single_tr_umr_1_mean_pos"] == "tr_umr"
    # did_ratio 的就绪输入只有衍生指标：all_a 成员与市值都由它决定；财报不参与行数就绪。
    did = next(item for item in d.FEATURE_INCREMENTS if item.materializer == "did_ratio")
    assert did.inputs == ("ashareeodderivativeindicator",)
    # nap_adj_ratio 同理：all_a 成员由当日衍生指标决定，朝阳永续调整行不参与行数就绪。
    nap = next(item for item in d.FEATURE_INCREMENTS if item.materializer == "nap_adj_ratio")
    assert nap.feature_id == "pf_single_nap_adj_ratio_1_mean_pos"
    assert nap.inputs == ("ashareeodderivativeindicator",)
    # event_sue 同理：all_a 域由当日衍生指标决定，财报三源事件驱动不参与行数就绪。
    sue = next(item for item in d.FEATURE_INCREMENTS if item.materializer == "event_sue")
    assert sue.feature_id == "pf_single_event_sue_1_mean_pos"
    assert sue.inputs == ("ashareeodderivativeindicator",)
    # event_aog 需行情（个股+中证500夜盘涨幅）与 all_a 域就绪；财报三源事件驱动不参与。
    aog = next(item for item in d.FEATURE_INCREMENTS if item.materializer == "event_aog")
    assert aog.feature_id == "pf_single_event_aog_1_mean_pos"
    assert aog.inputs == ("ashareeodprices", "aindexeodprices", "ashareeodderivativeindicator")
    # event_delta_roe 不依赖行情，就绪输入仅 all_a 域（衍生指标）；ROE/eqt/财报事件驱动不参与。
    droe = next(item for item in d.FEATURE_INCREMENTS if item.materializer == "event_delta_roe")
    assert droe.feature_id == "pf_single_event_delta_roe_1_mean_pos"
    assert droe.inputs == ("ashareeodderivativeindicator",)


@pytest.mark.unit
def test_cutamp_and_tr_umr_codes_are_optional_on_the_cli() -> None:
    runner = CliRunner()
    for command in ("cutamp", "tr-umr"):
        result = runner.invoke(app, ["lake", "materialize", command, "--help"])
        text = _ANSI.sub("", result.output)
        assert result.exit_code == 0
        assert "--codes" in text
        assert "all_a" in text
        assert "--as-of" in text
