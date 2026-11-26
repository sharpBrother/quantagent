"""日更增量：每个因子与前瞻收益的每个 horizon，从 lake 已有的最大 event_dt 之后开始，
算到输入连续就绪的最后一天，再调用既有物化函数写入。

规则（就绪阈值、连续截止、前瞻区间）在 ``domain/incremental.py``；这里只读 lake 水位线和 PG 计数，
然后调用既有物化函数。lake 里没有该因子的行时报错，要求先做历史回填，不从头计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast, get_args

from quantagent.adapters.lake.feature_value import LakeFeatureRepository
from quantagent.adapters.lake.forward_return import LakeForwardReturnRepository
from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.readiness import PostgresSourceReadinessRepository
from quantagent.cli.cutamp_materialize import materialize_cutamp
from quantagent.cli.did_ratio_materialize import materialize_did_ratio
from quantagent.cli.event_aog_materialize import materialize_event_aog
from quantagent.cli.event_sue_materialize import materialize_event_sue
from quantagent.cli.forward_return_materialize import materialize_forward_return_cli
from quantagent.cli.mif_materialize import materialize_mif
from quantagent.cli.minute_factors_2b_materialize import materialize_minute_factors_2b
from quantagent.cli.minute_factors_materialize import materialize_minute_factors
from quantagent.cli.moneyflow_materialize import materialize_moneyflow_factors
from quantagent.cli.nap_adj_ratio_materialize import materialize_nap_adj_ratio
from quantagent.cli.tr_umr_materialize import materialize_tr_umr
from quantagent.domain.calendar import open_dates
from quantagent.domain.errors import IncrementError
from quantagent.domain.forward_return import horizon_steps
from quantagent.domain.incremental import (
    MINUTE_INPUT,
    PRIOR_OPEN_DAYS,
    READY_PERCENT,
    IncrementWindow,
    ReadinessData,
    candidates_after,
    forward_span,
    is_input_ready,
    plan_window,
)
from quantagent.domain.ports.readiness import DailySource
from quantagent.features.library.fundamental import (
    did_ratio,
    event_aog,
    event_sue,
    nap_adj_ratio,
)
from quantagent.features.library.minute.batch_2b import PARAM_HASHES as MINUTE_2B_PARAM_HASHES
from quantagent.features.library.minute.five_day import DEFINITION_VERSION as MINUTE_VERSION
from quantagent.features.library.minute.five_day import SPECS as MINUTE_SPECS
from quantagent.features.library.money_flow import abso_umr, actlargemedcut, moneyflowh
from quantagent.features.library.price import cutamp, mif, tr_umr
from quantagent.features.panel.minute_2b import DEFINITION_VERSION as MINUTE_2B_VERSION
from quantagent.platform.identity import digest_json, new_run_id
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Sequence

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "lake.daily_increment"
_EXCHANGE = "SSE"
# 起点之前至少要有 PRIOR_OPEN_DAYS 个开市日用于就绪判定。60 个自然日足以覆盖长假。
_CALENDAR_PAD_DAYS = 60

PRICE: Literal["ashareeodprices"] = "ashareeodprices"
DERIVATIVE: Literal["ashareeodderivativeindicator"] = "ashareeodderivativeindicator"
MONEY_FLOW: Literal["asharemoneyflow"] = "asharemoneyflow"
INDEX: Literal["aindexeodprices"] = "aindexeodprices"
MINUTE: Literal["minute"] = "minute"

Input = Literal[
    "ashareeodprices",
    "ashareeodderivativeindicator",
    "asharemoneyflow",
    "aindexeodprices",
    "minute",
]
Materializer = Literal[
    "cutamp",
    "mif",
    "tr_umr",
    "moneyflow",
    "minute",
    "minute_2b",
    "did_ratio",
    "nap_adj_ratio",
    "event_sue",
    "event_aog",
]

_DAILY_SOURCES: frozenset[str] = frozenset(get_args(DailySource))
# 指数源只统计基准代码。与 tr_umr / abso_umr 读取的基准一致。
_SOURCE_CODES: dict[str, tuple[str, ...]] = {"aindexeodprices": (tr_umr.BENCHMARK,)}


@dataclass(frozen=True)
class FeatureIncrement:
    feature_id: str
    definition_version: str
    param_hash: str
    materializer: Materializer
    inputs: tuple[Input, ...]


# 默认股票池 all_a 的成员 = 上市规则 ∩ 当日 ASHAREEODDERIVATIVEINDICATOR 出现的代码
# （见 adapters/postgres/universe.py 的 _OBSERVED_SQL）。所以凡是按 all_a 取股票的因子，
# 当日衍生指标表也是输入；表只完成一部分时，成员会少几只股票，且不报错。
def _feature_increments() -> tuple[FeatureIncrement, ...]:
    items = [
        FeatureIncrement(
            cutamp.FEATURE_ID,
            cutamp.DEFINITION_VERSION,
            cutamp.PARAM_HASH,
            "cutamp",
            (PRICE, DERIVATIVE),
        ),
        FeatureIncrement(
            mif.FEATURE_ID, mif.DEFINITION_VERSION, mif.PARAM_HASH, "mif", (PRICE, DERIVATIVE)
        ),
        FeatureIncrement(
            moneyflowh.FEATURE_ID,
            moneyflowh.DEFINITION_VERSION,
            moneyflowh.PARAM_HASH,
            "moneyflow",
            (PRICE, MONEY_FLOW, DERIVATIVE),
        ),
        FeatureIncrement(
            actlargemedcut.FEATURE_ID,
            actlargemedcut.DEFINITION_VERSION,
            actlargemedcut.PARAM_HASH,
            "moneyflow",
            (PRICE, MONEY_FLOW, DERIVATIVE),
        ),
        FeatureIncrement(
            abso_umr.FEATURE_ID,
            abso_umr.DEFINITION_VERSION,
            abso_umr.PARAM_HASH,
            "moneyflow",
            (PRICE, MONEY_FLOW, INDEX, DERIVATIVE),
        ),
        FeatureIncrement(
            tr_umr.FEATURE_ID,
            tr_umr.DEFINITION_VERSION,
            tr_umr.PARAM_HASH,
            "tr_umr",
            (PRICE, INDEX, DERIVATIVE),
        ),
        # did_ratio 的日频就绪依赖只有衍生指标：all_a 成员与市值都由它决定。
        # 财报（分红/利润表/财务指标）是事件驱动、按 ANN_DT 截止，没有"当日行数就绪"概念，
        # 不作为就绪输入；它们的采集血缘在 orchestration 资产的 deps 里表达。
        FeatureIncrement(
            did_ratio.FEATURE_ID,
            did_ratio.DEFINITION_VERSION,
            did_ratio.PARAM_HASH,
            "did_ratio",
            (DERIVATIVE,),
        ),
        # nap_adj_ratio 的就绪依赖同 did_ratio：all_a 成员由当日衍生指标表决定。
        # 朝阳永续调整行是事件驱动、按 entrytime 截止，没有“当日行数就绪”概念，
        # 不作为就绪输入；其采集血缘在 orchestration 资产的 deps 里表达。
        FeatureIncrement(
            nap_adj_ratio.FEATURE_ID,
            nap_adj_ratio.DEFINITION_VERSION,
            nap_adj_ratio.PARAM_HASH,
            "nap_adj_ratio",
            (DERIVATIVE,),
        ),
        # event_sue 的就绪依赖同理：all_a 域由当日衍生指标决定。财报三表与业绩预告/快报
        # 都是事件驱动、按 declare_date 截止，无当日行数就绪概念，不作就绪输入；其采集血缘
        # 在 orchestration 资产的 deps 里表达。事件驱动稀疏因子，只在新事件日产值。
        FeatureIncrement(
            event_sue.FEATURE_ID,
            event_sue.DEFINITION_VERSION,
            event_sue.PARAM_HASH,
            "event_sue",
            (DERIVATIVE,),
        ),
        # event_aog 需要行情就绪（个股+中证500夜盘涨幅）与 all_a 域（衍生指标）。
        # 财报三源同为事件驱动不作就绪输入。event_dt=open_date，open_date 行情当晚可见。
        FeatureIncrement(
            event_aog.FEATURE_ID,
            event_aog.DEFINITION_VERSION,
            event_aog.PARAM_HASH,
            "event_aog",
            (PRICE, INDEX, DERIVATIVE),
        ),
    ]
    items.extend(
        FeatureIncrement(
            spec.feature_id, MINUTE_VERSION, spec.param_hash, "minute", (MINUTE, DERIVATIVE)
        )
        for spec in MINUTE_SPECS
    )
    # 第二批分钟因子的 PARAM_HASHES 以 feature_id 为键。中性化还需要日行情算 pxret21。
    items.extend(
        FeatureIncrement(
            feature_id, MINUTE_2B_VERSION, param_hash, "minute_2b", (MINUTE, PRICE, DERIVATIVE)
        )
        for feature_id, param_hash in MINUTE_2B_PARAM_HASHES.items()
    )
    return tuple(items)


# 日更的因子清单，键为 feature_id。新增因子时同步 orchestration/assets/daily_feature.py。
FEATURE_INCREMENTS: tuple[FeatureIncrement, ...] = _feature_increments()


@dataclass(frozen=True)
class IncrementPlan:
    """一次增量的决定：起点、截止与依据。``start`` 为 ``None`` 时本次不写。"""

    name: str
    as_of: date
    last_event: date
    start: date | None
    cutoff: date | None
    # 物化时传入的 as_of。因子为 ``cutoff``；前瞻收益为截止信号日的 ``end_dt``，保证只读到可见行情。
    materialize_as_of: date | None
    blocked_on: date | None
    reason: str
    inputs: tuple[str, ...]

    @property
    def writes(self) -> bool:
        return self.start is not None


@dataclass(frozen=True)
class IncrementResult:
    plan: IncrementPlan
    row_count: int | None
    digest: str | None

    def metadata(self) -> dict[str, str | int]:
        """Dagster 元数据。只放标量，便于在运行页面直接读到就绪依据。"""
        meta: dict[str, str | int] = {
            "status": "written" if self.plan.writes else "skipped",
            "as_of": self.plan.as_of.isoformat(),
            "last_event": self.plan.last_event.isoformat(),
            "readiness_rule": f"row_count>={READY_PERCENT}% of max over prior {PRIOR_OPEN_DAYS} opens",
            "inputs": ",".join(self.plan.inputs),
        }
        if self.plan.start is not None and self.plan.cutoff is not None:
            meta["start"] = self.plan.start.isoformat()
            meta["cutoff"] = self.plan.cutoff.isoformat()
        if self.plan.blocked_on is not None:
            meta["blocked_on"] = self.plan.blocked_on.isoformat()
        if self.plan.reason:
            meta["reason"] = self.plan.reason
        if self.row_count is not None and self.digest is not None:
            meta["row_count"] = self.row_count
            meta["digest"] = self.digest
        return meta


def feature_increment(feature_id: str) -> FeatureIncrement:
    for item in FEATURE_INCREMENTS:
        if item.feature_id == feature_id:
            return item
    raise IncrementError(f"未登记为日更的因子: {feature_id}")


def plan_feature_increment(
    settings: Settings, paths: VarPaths, *, feature_id: str, as_of: date
) -> IncrementPlan:
    item = feature_increment(feature_id)
    last = LakeFeatureRepository(paths.lake / "feature" / "value").latest_event_dt(
        as_of=as_of,
        feature_id=item.feature_id,
        definition_version=item.definition_version,
        param_hash=item.param_hash,
    )
    if last is None:
        raise IncrementError(f"lake 中没有 {feature_id} 的行，请先做历史回填，本命令不从头计算")
    opens = _open_days(paths, as_of=as_of, last=last)
    candidates = candidates_after(opens, after=last, as_of=as_of)
    data = _readiness(settings, as_of=as_of, opens=opens, inputs=item.inputs, pending=candidates)
    window = plan_window(candidates, lambda day: is_input_ready(data, day, item.inputs))
    return _plan(
        feature_id,
        as_of=as_of,
        last=last,
        window=window,
        materialize_as_of=window.cutoff,
        inputs=item.inputs,
        blocked_text="输入 {day} 未就绪",
    )


def plan_forward_return_increment(
    settings: Settings, paths: VarPaths, *, horizon: str, as_of: date
) -> IncrementPlan:
    steps = horizon_steps(horizon)
    last = LakeForwardReturnRepository(paths.lake / "mart" / "forward_return").latest_event_dt(
        as_of=as_of, horizon=horizon
    )
    name = f"forward_return:{horizon}"
    if last is None:
        raise IncrementError(f"lake 中没有 {name} 的行，请先做历史回填，本命令不从头计算")
    opens = _open_days(paths, as_of=as_of, last=last)
    candidates = candidates_after(opens, after=last, as_of=as_of)
    # 起点与终点的行情、以及信号日的 all_a 成员（来自衍生指标）都须就绪。
    # 起点缺行会静默丢掉该信号的收益，之后增量起点已越过，无法补回。
    inputs: tuple[Input, ...] = (PRICE, DERIVATIVE)
    data = _readiness(settings, as_of=as_of, opens=opens, inputs=inputs, pending=candidates)

    def ready(signal: date) -> bool:
        span = forward_span(opens, signal, steps)
        return (
            span is not None
            and is_input_ready(data, span[0], (PRICE,))
            and is_input_ready(data, span[1], (PRICE,))
            and is_input_ready(data, signal, (DERIVATIVE,))
        )

    window = plan_window(candidates, ready)
    materialize_as_of: date | None = None
    if window.cutoff is not None:
        span = forward_span(opens, window.cutoff, steps)
        if span is None:
            raise IncrementError(f"{window.cutoff} 的终点不在开市日历内，无法确定物化 as_of")
        materialize_as_of = span[1]
    return _plan(
        name,
        as_of=as_of,
        last=last,
        window=window,
        materialize_as_of=materialize_as_of,
        inputs=inputs,
        blocked_text="信号日 {day} 的前瞻区间（起点或终点行情）未就绪",
    )


def run_feature_increment(
    settings: Settings, paths: VarPaths, *, feature_id: str, as_of: date
) -> IncrementResult:
    plan = plan_feature_increment(settings, paths, feature_id=feature_id, as_of=as_of)
    if not plan.writes:
        return IncrementResult(plan=plan, row_count=None, digest=None)
    item = feature_increment(feature_id)
    started = datetime.now(UTC)
    row_count, digest = _materialize_feature(settings, paths, item, plan)
    _log(paths, plan, started=started, row_count=row_count, digest=digest)
    return IncrementResult(plan=plan, row_count=row_count, digest=digest)


def run_forward_return_increment(
    settings: Settings, paths: VarPaths, *, horizon: str, as_of: date
) -> IncrementResult:
    plan = plan_forward_return_increment(settings, paths, horizon=horizon, as_of=as_of)
    if not plan.writes:
        return IncrementResult(plan=plan, row_count=None, digest=None)
    if plan.start is None or plan.cutoff is None or plan.materialize_as_of is None:
        raise IncrementError("写入计划缺少起点、截止或物化 as_of")
    started = datetime.now(UTC)
    result = materialize_forward_return_cli(
        settings=settings,
        paths=paths,
        start=plan.start,
        end=plan.cutoff,
        as_of=plan.materialize_as_of,
        wind_codes=None,
        horizons=(horizon,),
    )
    _log(paths, plan, started=started, row_count=result.row_count, digest=result.digest)
    return IncrementResult(plan=plan, row_count=result.row_count, digest=result.digest)


def _materialize_feature(
    settings: Settings, paths: VarPaths, item: FeatureIncrement, plan: IncrementPlan
) -> tuple[int, str]:
    if plan.start is None or plan.cutoff is None or plan.materialize_as_of is None:
        raise IncrementError("写入计划缺少起点、截止或物化 as_of")
    start, end, as_of = plan.start, plan.cutoff, plan.materialize_as_of
    kind = item.materializer
    # 单因子直返的物化函数：签名统一为 (settings, paths, start, end, wind_codes, as_of)。
    # did_ratio 返回三元组（行数, digest, 冲突数），日更只取前两元。
    single = {
        "cutamp": materialize_cutamp,
        "mif": materialize_mif,
        "tr_umr": materialize_tr_umr,
        # nap_adj_ratio/event_sue 返回 (行数, digest) 二元组，签名与三因子一致，可同表分发。
        "nap_adj_ratio": materialize_nap_adj_ratio,
        "event_sue": materialize_event_sue,
        "event_aog": materialize_event_aog,
    }
    if kind in single:
        return single[kind](
            settings=settings, paths=paths, start=start, end=end, wind_codes=None, as_of=as_of
        )
    if kind == "did_ratio":
        row_count, digest, _conflicts = materialize_did_ratio(
            settings=settings, paths=paths, start=start, end=end, wind_codes=None, as_of=as_of
        )
        return row_count, digest
    if kind == "moneyflow":
        return materialize_moneyflow_factors(
            settings=settings,
            paths=paths,
            start=start,
            end=end,
            wind_codes=None,
            as_of=as_of,
            feature_ids=(item.feature_id,),
        )
    if kind == "minute":
        return materialize_minute_factors(
            settings=settings,
            paths=paths,
            start=start,
            end=end,
            as_of=as_of,
            codes=None,
            feature_ids=(item.feature_id,),
        )
    return materialize_minute_factors_2b(
        settings=settings,
        paths=paths,
        start=start,
        end=end,
        as_of=as_of,
        codes=None,
        feature_ids=(item.feature_id,),
    )


def _open_days(paths: VarPaths, *, as_of: date, last: date) -> tuple[date, ...]:
    """``last`` 之前的 pad 与 ``as_of`` 之间的开市日，覆盖就绪判定所需的前序开市日。"""
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    days = calendar.list_days(
        as_of=as_of,
        exchange=_EXCHANGE,
        start=last - timedelta(days=_CALENDAR_PAD_DAYS),
        end=as_of,
    )
    return open_dates(days)


def _readiness(
    settings: Settings,
    *,
    as_of: date,
    opens: tuple[date, ...],
    inputs: Sequence[str],
    pending: Sequence[date],
) -> ReadinessData:
    """读取输入计数。没有待判定的候选日时不连 PG，直接返回空快照。"""
    if not pending:
        return ReadinessData(opens=opens, counts={}, minute_days=frozenset())
    counts: dict[str, dict[date, int]] = {}
    minute_days: frozenset[date] = frozenset()
    conn = connect(settings, "src")
    try:
        conn.read_only = True
        repo = PostgresSourceReadinessRepository(conn)
        for name in inputs:
            if name == MINUTE_INPUT:
                minute_days = repo.registered_minute_days(as_of=as_of, start=opens[0], end=as_of)
                continue
            if name not in _DAILY_SOURCES:
                raise IncrementError(f"未知就绪输入: {name}")
            counts[name] = repo.daily_row_counts(
                as_of=as_of,
                source=cast("DailySource", name),
                start=opens[0],
                end=as_of,
                wind_codes=_SOURCE_CODES.get(name),
            )
    finally:
        conn.close()
    return ReadinessData(opens=opens, counts=counts, minute_days=minute_days)


def _plan(
    name: str,
    *,
    as_of: date,
    last: date,
    window: IncrementWindow,
    materialize_as_of: date | None,
    inputs: Sequence[str],
    blocked_text: str,
) -> IncrementPlan:
    """``blocked_text`` 描述第一个未就绪日的含义，含 ``{day}`` 占位符。"""
    if not window.candidates:
        reason = f"无新数据：{last.isoformat()} 之后到 {as_of.isoformat()} 之间没有开市日"
    elif window.blocked_on is None:
        reason = ""
    else:
        blocked = blocked_text.format(day=window.blocked_on.isoformat())
        if not window.days:
            reason = f"{blocked}，本次不写"
        else:
            reason = f"{blocked}，本次截止在 {_iso(window.cutoff)}"
    return IncrementPlan(
        name=name,
        as_of=as_of,
        last_event=last,
        start=window.start,
        cutoff=window.cutoff,
        materialize_as_of=materialize_as_of if window.days else None,
        blocked_on=window.blocked_on,
        reason=reason,
        inputs=tuple(inputs),
    )


def _iso(day: date | None) -> str:
    return "" if day is None else day.isoformat()


def _log(
    paths: VarPaths,
    plan: IncrementPlan,
    *,
    started: datetime,
    row_count: int,
    digest: str,
) -> None:
    """写入成功后落一份增量 run log。就绪依据（输入、阈值、截止与被挡日）进入 input digest，
    与物化函数自己的 run log 分开：那一份只记录区间与输出。
    """
    finished = datetime.now(UTC)
    record = RunLog(
        run_id=new_run_id(),
        action=ACTION,
        status="success",
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json(
            {
                "name": plan.name,
                "as_of": plan.as_of.isoformat(),
                "last_event": plan.last_event.isoformat(),
                "start": _iso(plan.start),
                "cutoff": _iso(plan.cutoff),
                "materialize_as_of": _iso(plan.materialize_as_of),
                "blocked_on": _iso(plan.blocked_on),
                "inputs": list(plan.inputs),
                "ready_percent": READY_PERCENT,
                "prior_open_days": PRIOR_OPEN_DAYS,
            }
        ),
        output_digest=digest,
        row_count=row_count,
        dml_count=0,
    )
    persist_run_log(record, paths)


__all__ = [
    "FEATURE_INCREMENTS",
    "IncrementPlan",
    "IncrementResult",
    "feature_increment",
    "plan_feature_increment",
    "plan_forward_return_increment",
    "run_feature_increment",
    "run_forward_return_increment",
]
