"""std.trade_calendar 的 Parquet 读取。PIT 截止日来自 domain.pit，不在 SQL 里手写规则名。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import pandas as pd

from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.domain.calendar.types import CalendarDay
from quantagent.domain.errors import (
    CalendarLookupError,
    EmptyDomainError,
    MissingVisibilityError,
)
from quantagent.domain.pit import visible_event_on_or_before
from quantagent.platform.duck import duck_session, register_parquet

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.contracts.spec import VisibilityContract

DATASET = "std.trade_calendar"
_VIEW = "trade_calendar"

_SQL = """
SELECT cal_dt, exchange, is_open, prev_trade_dt
FROM trade_calendar
WHERE exchange = $exchange
  AND cal_dt BETWEEN $start AND $end
  AND cal_dt <= $visible_on_or_before
ORDER BY cal_dt
"""


class LakeCalendarRepository:
    def __init__(self, source: Path, *, contract: VisibilityContract | None = None) -> None:
        self._source = source
        self._contract = contract if contract is not None else load_trade_calendar_visibility()

    def list_days(
        self,
        *,
        as_of: date,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[CalendarDay, ...]:
        if not exchange.strip():
            raise CalendarLookupError("exchange 为空")
        if start > end:
            raise CalendarLookupError("start 晚于 end")
        cutoff = visible_event_on_or_before(self._contract, as_of=as_of)
        with duck_session() as conn:
            register_parquet(conn, _VIEW, self._source)
            frame = conn.execute(
                _SQL,
                {
                    "exchange": exchange,
                    "start": start,
                    "end": end,
                    "visible_on_or_before": cutoff,
                },
            ).df()
        if frame.empty:
            raise EmptyDomainError(
                f"日历域为空: exchange={exchange} start={start.isoformat()} "
                f"end={end.isoformat()} as_of={as_of.isoformat()}"
            )
        spec = load_bundle().schemas[DATASET]
        to_pandera(spec).validate(frame)
        return tuple(_row_from_series(frame.iloc[i]) for i in range(len(frame)))


def load_trade_calendar_visibility() -> VisibilityContract:
    bundle = load_bundle()
    vis = bundle.visibilities.get(DATASET)
    schema = bundle.schemas.get(DATASET)
    if vis is None or schema is None:
        raise MissingVisibilityError(DATASET)
    return vis


def _row_from_series(row: pd.Series) -> CalendarDay:
    return CalendarDay(
        cal_dt=_as_date(row["cal_dt"]),
        exchange=str(row["exchange"]),
        is_open=bool(row["is_open"]),
        prev_trade_dt=_as_optional_date(row["prev_trade_dt"]),
    )


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise CalendarLookupError(f"cal_dt 无法转为 date: {value!r}")


def _as_optional_date(value: object) -> date | None:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    return _as_date(value)
