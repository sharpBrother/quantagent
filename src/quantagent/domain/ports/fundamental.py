"""财报与分红的窄读取端口。只提供 did_ratio 需要的字段，不做修订去重与季度差分。

三个端口都要求 ``as_of``。可见性来自各自的契约（ANN_DT <= as_of，空公告日不可见）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from quantagent.domain.fundamental.types import (
        DividendRecord,
        IndicatorRecord,
        NetProfitRecord,
    )


class DividendRepository(Protocol):
    def list_dividends(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[DividendRecord, ...]:
        """``ANN_DT`` 在 ``[start, end]`` 且 ``<= as_of`` 的分红行，闭区间。
        不过滤报告期，不去重，不补缺。空代码列表或窗口无行时返回空元组。
        """
        ...


class NetProfitRepository(Protocol):
    def list_net_profits(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        statement_type: str,
        wind_codes: tuple[str, ...],
    ) -> tuple[NetProfitRecord, ...]:
        """``STATEMENT_TYPE`` 等于 ``statement_type``、``ANN_DT`` 在 ``[start, end]`` 且 ``<= as_of`` 的利润表行。
        不去重，不补缺。
        """
        ...


class FinancialIndicatorRepository(Protocol):
    def list_indicator_rows(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        wind_codes: tuple[str, ...],
    ) -> tuple[IndicatorRecord, ...]:
        """``ANN_DT`` 在 ``[start, end]`` 且 ``<= as_of`` 的财务指标行。只返回代码、公告日与报告期。"""
        ...
