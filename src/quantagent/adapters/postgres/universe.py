"""PostgreSQL all_a 股票池读取。规则判断全部在 ``domain.universe.all_a``。

这里只做三件事：取 PIT 截止（来自衍生指标的契约）、读两张源表、把字符串日期
转成 ``date``。不在 SQL 里写上市/退市/BSE 等规则，也不物化成员表。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import (
    EmptyDomainError,
    InvalidQueryError,
    MissingVisibilityError,
)
from quantagent.domain.pit import is_cutoff_visible, pit_cutoff
from quantagent.domain.universe import (
    ALL_A_UNIVERSE_ID,
    ListingRow,
    UniverseMember,
    all_a_members,
)

if TYPE_CHECKING:
    from datetime import date

    import psycopg

    from quantagent.contracts.spec import VisibilityContract

DERIVATIVE_DATASET = "src.wind.ashareeodderivativeindicator"
_YMD_LEN = 8


class PostgresUniverseRepository:
    """``members_at`` 的 PostgreSQL 实现。实例内缓存规则池，同一连接下只读一次整表。"""

    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contract: VisibilityContract | None = None,
    ) -> None:
        self._conn = conn
        self._contract = contract
        self._listings: tuple[ListingRow, ...] | None = None

    def members_at(
        self,
        *,
        as_of: date,
        dt: date,
        universe_id: str,
    ) -> tuple[UniverseMember, ...]:
        if universe_id != ALL_A_UNIVERSE_ID:
            raise InvalidQueryError(f"不支持的 universe_id: {universe_id!r}")
        contract = self._contract if self._contract is not None else load_derivative_visibility()
        cutoff = pit_cutoff(contract, as_of=as_of)
        # 不可见的日期不查库：空域直接报错，避免读到 as_of 之后才有的衍生指标。
        if not is_cutoff_visible(value=dt, cutoff=cutoff):
            raise EmptyDomainError(f"dt {dt.isoformat()} 晚于 as_of {as_of.isoformat()} 的可见截止")
        members = all_a_members(
            self._load_listings(),
            dt=dt,
            observed=self._load_observed(dt),
        )
        if not members:
            raise EmptyDomainError(f"all_a 在 {dt.isoformat()} 为空域")
        return members

    def _load_listings(self) -> tuple[ListingRow, ...]:
        if self._listings is None:
            self._listings = self._fetch_listings()
        return self._listings

    def _fetch_listings(self) -> tuple[ListingRow, ...]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_DESCRIPTION_SQL)
            fetched = cur.fetchall()
        rows = tuple(_listing_from_mapping(item) for item in fetched)
        seen: set[str] = set()
        for row in rows:
            if row.asset_id in seen:
                raise InvalidQueryError(f"ASHAREDESCRIPTION 代码重复: {row.asset_id}")
            seen.add(row.asset_id)
        return rows

    def _load_observed(self, dt: date) -> frozenset[str]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_OBSERVED_SQL, (_ymd(dt),))
            fetched = cur.fetchall()
        codes: list[str] = []
        for item in fetched:
            code = item.get("S_INFO_WINDCODE")
            if not isinstance(code, str) or not code.strip():
                raise InvalidQueryError(f"衍生指标代码为空: {dt.isoformat()}")
            codes.append(code)
        if len(set(codes)) != len(codes):
            raise InvalidQueryError(f"衍生指标同日代码重复: {dt.isoformat()}")
        return frozenset(codes)


def load_derivative_visibility() -> VisibilityContract:
    vis = load_bundle().visibilities.get(DERIVATIVE_DATASET)
    if vis is None:
        raise MissingVisibilityError(DERIVATIVE_DATASET)
    return vis


def parse_ymd_optional(value: object, field: str) -> date | None:
    """``None`` 表示空值。其他值必须是合法 YYYYMMDD，空串也算非法，不静默当空值。"""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != _YMD_LEN or not value.isdigit():
        raise InvalidQueryError(f"{field} 必须是 YYYYMMDD 或 NULL: {value!r}")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise InvalidQueryError(f"{field} 不是合法日期: {value!r}") from exc


def _listing_from_mapping(row: dict[str, object]) -> ListingRow:
    code = row.get("S_INFO_WINDCODE")
    if not isinstance(code, str) or not code.strip():
        raise InvalidQueryError("ASHAREDESCRIPTION 代码为空")
    exchange = row.get("S_INFO_EXCHMARKET")
    if exchange is not None and not isinstance(exchange, str):
        raise InvalidQueryError(f"S_INFO_EXCHMARKET 类型非法: {code}")
    return ListingRow(
        asset_id=code,
        list_date=parse_ymd_optional(row.get("S_INFO_LISTDATE"), "S_INFO_LISTDATE"),
        delist_date=parse_ymd_optional(row.get("S_INFO_DELISTDATE"), "S_INFO_DELISTDATE"),
        exchange_market=exchange,
    )


def _ymd(value: date) -> str:
    return value.strftime("%Y%m%d")


_DESCRIPTION_SQL = assert_src_dml_sql(
    "SELECT "
    + ", ".join(
        quote_ident(name)
        for name in (
            "S_INFO_WINDCODE",
            "S_INFO_LISTDATE",
            "S_INFO_DELISTDATE",
            "S_INFO_EXCHMARKET",
        )
    )
    + f" FROM {quote_ident('src_wind')}.{quote_ident('ASHAREDESCRIPTION')}"
    + f" ORDER BY {quote_ident('S_INFO_WINDCODE')}"
)

_OBSERVED_SQL = assert_src_dml_sql(
    f"SELECT {quote_ident('S_INFO_WINDCODE')}"
    f" FROM {quote_ident('src_wind')}.{quote_ident('ASHAREEODDERIVATIVEINDICATOR')}"
    f" WHERE {quote_ident('TRADE_DT')} = %s"
    f" AND {quote_ident('S_VAL_MV')} IS NOT NULL"
    f" AND {quote_ident('S_DQ_MV')} IS NOT NULL"
)
