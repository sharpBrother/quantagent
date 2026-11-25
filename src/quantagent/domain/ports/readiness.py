"""输入就绪判定用的源表计数。只回答"某日有多少行"与"某日分钟分区是否已登记"，不返回行内容。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from datetime import date

# 参与行数就绪判定的源表。新增源时同步适配器的表名映射。
DailySource = Literal[
    "ashareeodprices",
    "ashareeodderivativeindicator",
    "asharemoneyflow",
    "aindexeodprices",
]


class SourceReadinessRepository(Protocol):
    def daily_row_counts(
        self,
        *,
        as_of: date,
        source: DailySource,
        start: date,
        end: date,
        wind_codes: tuple[str, ...] | None,
    ) -> dict[date, int]:
        """``[start, end]`` 内每个交易日的行数，无行的日子不在结果里。
        ``end`` 晚于 ``as_of`` 时报错。``wind_codes`` 为 None 时统计全部代码。
        """
        ...

    def registered_minute_days(self, *, as_of: date, start: date, end: date) -> frozenset[date]:
        """``[start, end]`` 内在分钟分区 manifest 里已登记的交易日。``end`` 晚于 ``as_of`` 时报错。"""
        ...
