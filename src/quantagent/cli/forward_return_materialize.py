"""组装前瞻收益物化：接上 PG 行情、lake 日历和 all_a 默认代码池，业务规则不在这里。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID
from quantagent.lake.materialize.forward_return import materialize_forward_return
from quantagent.platform.pg import connect

if TYPE_CHECKING:
    from datetime import date

    import psycopg

    from quantagent.lake.materialize.forward_return import ForwardReturnWriteResult
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths


def materialize_forward_return_cli(
    *,
    settings: Settings,
    paths: VarPaths,
    start: date,
    end: date,
    as_of: date,
    wind_codes: tuple[str, ...] | None,
) -> ForwardReturnWriteResult:
    """``wind_codes`` 为 ``None`` 时，代码取 ``all_a`` 池在 ``min(end, as_of)`` 的成员。
    这只覆盖截止日仍在池内的股票。窗口内已退市的股票需要显式传 ``--codes``。
    """
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    conn = connect(settings, "src")
    try:
        conn.read_only = True
        codes = wind_codes if wind_codes else _all_a_codes(conn, as_of=as_of, end=end)
        return materialize_forward_return(
            paths=paths,
            calendar=calendar,
            prices=PostgresDailyPriceRepository(conn, contract=load_price_visibility()),
            contract=load_price_visibility(),
            start=start,
            end=end,
            as_of=as_of,
            wind_codes=codes,
        )
    finally:
        conn.close()


def _all_a_codes(conn: psycopg.Connection[object], *, as_of: date, end: date) -> tuple[str, ...]:
    dt = min(end, as_of)
    members = PostgresUniverseRepository(conn).members_at(
        as_of=as_of,
        dt=dt,
        universe_id=ALL_A_UNIVERSE_ID,
    )
    return tuple(sorted(member.asset_id for member in members))
