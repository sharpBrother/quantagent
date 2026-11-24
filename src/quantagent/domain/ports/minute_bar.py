"""按日 PIT 可见的分钟行情读取接口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date


class MinuteBarTable(Protocol):
    """领域只依赖表格能力，具体内存格式由适配器选择。"""

    @property
    def num_rows(self) -> int: ...

    def to_pylist(self) -> list[dict[str, Any]]: ...


class MinuteBarRepository(Protocol):
    def excluded_codes(self, *, as_of: date, day: date) -> frozenset[str]:
        """``day`` 当日分区已裁定排除的代码。这些股票当日没有分钟行，不是数据缺失。

        排除集来自分区元数据与已裁定名单。无排除返回空集。``day`` 不可见则报错。
        """
        ...

    def scan_window(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        codes: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> MinuteBarTable: ...
