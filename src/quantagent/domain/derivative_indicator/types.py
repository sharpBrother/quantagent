"""衍生指标中的换手率行。数值保持源端精度，缺失保持为空。
字段依据：旧仓 ``factors/factors.py`` 的 ``MIF.col_lag`` 中的 ``S_DQ_TURN``。
该表行集含非交易日，读取方必须按行情的交易日取值，不能直接把本表当截面。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Turnover:
    trade_dt: date
    wind_code: str
    turnover: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketValue:
    """衍生指标中的总市值行，单位与源端 ``S_VAL_MV`` 一致（万元）。空值保留为 None。"""

    trade_dt: date
    wind_code: str
    total_mv: Decimal | None


@dataclass(frozen=True, slots=True)
class DqMarketValue:
    """衍生指标中的**流通市值**行（``S_DQ_MV``），单位与源端一致（万元）。空值保留为 None。

    与 ``MarketValue``（总市值 ``S_VAL_MV``）是两个独立类型：barra descriptor_process 的市值加权
    用的是旧仓 ``fetch_cap`` 的 ``S_DQ_MV``（流通市值），与 ``S_VAL_MV`` 在大市值股上可差 11%级。
    独立类型防止与总市值混用——市值加权权重的口径直接决定标准化结果，串口径即串因子。
    """

    trade_dt: date
    wind_code: str
    dq_mv: Decimal | None
