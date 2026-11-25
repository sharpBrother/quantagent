"""日更增量的纯规则：输入就绪判定、连续就绪截止、前瞻收益的成熟区间。不读存储。

为什么要就绪判定：Wind 按 OPDATE 增量同步，没有"当日完整"标志，曾出现当日只到一部分。
如果在部分数据上算出因子并写入，增量起点随即越过该日，缺的行之后不会再被补上。
所以只有输入行数达到近期正常水平，才认为当日就绪；遇到第一个不就绪的日子就停，
后面即使已就绪也不算，避免 lake 里出现空洞。
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import TYPE_CHECKING

from quantagent.domain.errors import IncrementError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import date

# 行数阈值：当日行数 ≥ 前序 5 个开市日最大行数的 99%。
# 整数比较（count * 100 ≥ 99 * peak），不用浮点，避免边界上的舍入误差。
READY_PERCENT = 99
PRIOR_OPEN_DAYS = 5

# 分钟分区没有行数概念，只看 manifest 是否登记了该日分区。
MINUTE_INPUT = "minute"


@dataclass(frozen=True)
class ReadinessData:
    """判定所需的快照。``opens`` 须升序，且覆盖被判定日之前至少 ``PRIOR_OPEN_DAYS`` 个开市日。
    ``counts[源]`` 是该源每个交易日的行数，无行的日子可以不出现（视为 0）。
    """

    opens: tuple[date, ...]
    counts: Mapping[str, Mapping[date, int]]
    minute_days: frozenset[date]


@dataclass(frozen=True)
class IncrementWindow:
    """候选日里连续就绪的前缀。``days`` 为空表示第一个候选就未就绪，本次不写。"""

    candidates: tuple[date, ...]
    days: tuple[date, ...]

    @property
    def start(self) -> date | None:
        return self.days[0] if self.days else None

    @property
    def cutoff(self) -> date | None:
        return self.days[-1] if self.days else None

    @property
    def blocked_on(self) -> date | None:
        """第一个未就绪的候选日。全部就绪时为 ``None``。"""
        if len(self.days) < len(self.candidates):
            return self.candidates[len(self.days)]
        return None


def is_row_count_ready(count: int, prior_counts: Sequence[int]) -> bool:
    """``count`` 是否达到前序 5 个开市日最大行数的 99%。前序全为 0 时无基准，判为未就绪。"""
    if len(prior_counts) != PRIOR_OPEN_DAYS:
        raise IncrementError(
            f"就绪判定需要 {PRIOR_OPEN_DAYS} 个前序开市日，实际 {len(prior_counts)}"
        )
    peak = max(prior_counts)
    if peak <= 0:
        return False
    return count * 100 >= READY_PERCENT * peak


def is_input_ready(data: ReadinessData, day: date, inputs: Sequence[str]) -> bool:
    """``day`` 上所有输入都就绪才为真。任一输入未就绪即为假，不猜测。"""
    for name in inputs:
        if name == MINUTE_INPUT:
            if day not in data.minute_days:
                return False
            continue
        if name not in data.counts:
            raise IncrementError(f"就绪快照缺少输入 {name}")
        if not _row_count_ready(data, day, name):
            return False
    return True


def _row_count_ready(data: ReadinessData, day: date, name: str) -> bool:
    position = _open_position(data.opens, day)
    if position < PRIOR_OPEN_DAYS:
        raise IncrementError(
            f"{day.isoformat()} 之前的开市日不足 {PRIOR_OPEN_DAYS} 个，无法判定就绪"
        )
    source = data.counts[name]
    prior = [
        source.get(prior_day, 0) for prior_day in data.opens[position - PRIOR_OPEN_DAYS : position]
    ]
    return is_row_count_ready(source.get(day, 0), prior)


def _open_position(opens: Sequence[date], day: date) -> int:
    position = bisect_left(opens, day)
    if position >= len(opens) or opens[position] != day:
        raise IncrementError(f"{day.isoformat()} 不在开市日历中")
    return position


def candidates_after(opens: Sequence[date], *, after: date, as_of: date) -> tuple[date, ...]:
    """``after`` 之后、``as_of`` 之前（含）的开市日。``after`` 是 lake 已有的最大 event_dt。"""
    return tuple(day for day in opens if after < day <= as_of)


def forward_span(opens: Sequence[date], signal: date, steps: int) -> tuple[date, date] | None:
    """信号日 T 的前瞻区间 ``(start_dt, end_dt)``：起点为 T 之后第一个开市日，终点为第 ``steps + 1`` 个。
    日历里找不到终点（尚未到期或日历不可见）时返回 ``None``，调用方视为未就绪。
    与 ``domain.forward_return`` 的口径一致：``end_dt`` 为 T 之后第 h+1 个开市日。
    """
    position = _open_position(opens, signal)
    end_position = position + steps + 1
    if end_position >= len(opens):
        return None
    return opens[position + 1], opens[end_position]


def plan_window(candidates: Sequence[date], is_ready: Callable[[date], bool]) -> IncrementWindow:
    """从第一个候选起取连续就绪的前缀。遇到第一个未就绪日即停，之后的日子不计入。"""
    days: list[date] = []
    for day in candidates:
        if not is_ready(day):
            break
        days.append(day)
    return IncrementWindow(candidates=tuple(candidates), days=tuple(days))
