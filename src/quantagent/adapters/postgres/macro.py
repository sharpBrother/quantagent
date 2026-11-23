"""宏观序列读取：领域序列 ID 到源表的唯一映射。

每个序列按自己数据集的可见性契约截止，版本选择统一走
``domain.macro.select_visible_versions``，与内存实现同一套规则。
新增序列在 ``_SOURCES`` 登记；未登记的序列在 domain 层就被拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import (
    InvalidQueryError,
    MacroLookupError,
    MissingVisibilityError,
    PitUnsupportedError,
)
from quantagent.domain.macro import MacroVersion, normalize_series_ids, select_visible_versions
from quantagent.domain.pit import pit_cutoff

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import psycopg

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.macro import MacroObservation

_YMD_LEN = 8


@dataclass(frozen=True)
class _Source:
    dataset: str
    # point：一个观测一个版本，截止列是业务日（YYYYMMDD 文本）。
    # vintage：ALFRED 版本表，截止列是 realtime_start。
    # published：带发布时刻的源表（聚源 InfoPublDate），截止列是 timestamp，
    #   读取时按 ``::date`` 比较，发布日期当天可见。
    kind: Literal["point", "vintage", "published"]
    cutoff_column: str
    statement: str
    fixed_params: tuple[object, ...]
    # 源端口径与领域单位之间的固定换算，只用于 published。目前只有 PPI 的
    # “上年同月=100”转同比（−100）；kind 不是 published 时值必须为 0。
    value_offset: Decimal = Decimal(0)


def _point_sql(schema: str, table: str, date_col: str, value_col: str, where: str) -> str:
    statement = (
        f"SELECT {quote_ident(date_col)} AS obs, {quote_ident(value_col)} AS value "
        f"FROM {quote_ident(schema)}.{quote_ident(table)} "
        f"WHERE {quote_ident(date_col)} BETWEEN %s AND %s AND {where} "
        f"ORDER BY {quote_ident(date_col)}"
    )
    return assert_src_dml_sql(statement)


_VINTAGE_SQL = assert_src_dml_sql(
    "SELECT observation_date AS obs, realtime_start, realtime_end, value "
    f"FROM {quote_ident('src_macro')}.{quote_ident('fred_observation_vintage')} "
    "WHERE observation_date BETWEEN %s AND %s AND realtime_start <= %s AND series_id = %s "
    "ORDER BY observation_date, realtime_start"
)

# 聚源宏观指标表：EndDate 是统计期（月末），InfoPublDate 是源端发布时刻。
# 发布日为空的行无法定可见日，直接过滤掉而不是猜。
# DataValue 的数量级由 PowerNumber 描述，读取时要求它为 0（见 ``_published_versions``）。
_PUBLISHED_SQL = assert_src_dml_sql(
    f"SELECT {quote_ident('EndDate')}::date AS obs, "
    f"{quote_ident('InfoPublDate')}::date AS published, "
    f"{quote_ident('DataValue')} AS value, {quote_ident('PowerNumber')} "
    f"FROM {quote_ident('src_jydb')}.{quote_ident('C_ED_MacroIndicatorData')} "
    f"WHERE {quote_ident('EndDate')}::date BETWEEN %s AND %s "
    f"AND {quote_ident('InfoPublDate')} IS NOT NULL "
    f"AND {quote_ident('InfoPublDate')}::date <= %s "
    f"AND {quote_ident('IndicatorCode')} = %s "
    f"ORDER BY {quote_ident('EndDate')}, {quote_ident('InfoPublDate')}"
)

# 中债曲线过滤值与旧仓 MarketDataService.get_china_cgb_10y_yield_curve 一致：
# 曲线 1232（中债国债收益率曲线）、类型 2（到期收益率）、期限 10 年。
_SOURCES: Mapping[str, _Source] = {
    "cn_cgb_10y": _Source(
        dataset="src.wind.cbondcurvecnbd",
        kind="point",
        cutoff_column="TRADE_DT",
        statement=_point_sql(
            "src_wind",
            "CBONDCURVECNBD",
            "TRADE_DT",
            "B_ANAL_YIELD",
            f"{quote_ident('B_ANAL_CURVENUMBER')} = %s AND {quote_ident('B_ANAL_CURVETYPE')} = %s "
            f"AND {quote_ident('B_ANAL_CURVETERM')} = %s",
        ),
        fixed_params=(1232, "2", Decimal(10)),
    ),
    "us_ust_10y": _Source(
        dataset="src.tushare.us_treasury_yield",
        kind="point",
        cutoff_column="trade_date",
        statement=_point_sql(
            "src_tushare", "us_treasury_yield", "trade_date", "yield", "maturity = %s"
        ),
        fixed_params=("10y",),
    ),
    "us_tips_10y": _Source(
        dataset="src.macro.fred_observation_vintage",
        kind="vintage",
        cutoff_column="realtime_start",
        statement=_VINTAGE_SQL,
        fixed_params=("DFII10",),
    ),
    "cn_cpi_yoy": _Source(
        dataset="src.macro.fred_observation_vintage",
        kind="vintage",
        cutoff_column="realtime_start",
        statement=_VINTAGE_SQL,
        fixed_params=("CPALTT01CNM659N",),
    ),
    "cn_cpi_yoy_nbs": _Source(
        dataset="src.jydb.c_ed_macroindicatordata",
        kind="published",
        cutoff_column="InfoPublDate",
        statement=_PUBLISHED_SQL,
        fixed_params=(110255493,),
    ),
    # 源端 DataValue 是“上年同月=100”的指数，减 100 才是同比百分数。
    "cn_ppi_yoy_nbs": _Source(
        dataset="src.jydb.c_ed_macroindicatordata",
        kind="published",
        cutoff_column="InfoPublDate",
        statement=_PUBLISHED_SQL,
        fixed_params=(110002644,),
        value_offset=Decimal(-100),
    ),
    "cn_cpi_nonfood_yoy_nbs": _Source(
        dataset="src.jydb.c_ed_macroindicatordata",
        kind="published",
        cutoff_column="InfoPublDate",
        statement=_PUBLISHED_SQL,
        fixed_params=(191001482,),
    ),
    "cn_ibo_7d": _Source(
        dataset="src.jydb.c_ed_macroindicatordata",
        kind="published",
        cutoff_column="InfoPublDate",
        statement=_PUBLISHED_SQL,
        fixed_params=(601230002,),
    ),
    "cn_usdcny_fix": _Source(
        dataset="src.jydb.c_ed_macroindicatordata",
        kind="published",
        cutoff_column="InfoPublDate",
        statement=_PUBLISHED_SQL,
        fixed_params=(110253785,),
    ),
    "de_bund_10y": _Source(
        dataset="src.macro.fred_observation_vintage",
        kind="vintage",
        cutoff_column="realtime_start",
        statement=_VINTAGE_SQL,
        fixed_params=("IRLTLT01DEM156N",),
    ),
    "jp_jgb_10y": _Source(
        dataset="src.macro.fred_observation_vintage",
        kind="vintage",
        cutoff_column="realtime_start",
        statement=_VINTAGE_SQL,
        fixed_params=("IRLTLT01JPM156N",),
    ),
}


def _assert_offset_only_published(sources: Mapping[str, _Source]) -> None:
    """value_offset 只在 published 读取路径上应用；其他 kind 带上它会被静默忽略。

    这是 ``_SOURCES`` 的静态配置错误（写代码时的手误），不是运行时数据问题，
    所以抛 ValueError 而不是 MacroLookupError；在模块加载时暴露，不等到读数据。
    """
    for series_id, source in sources.items():
        if source.kind != "published" and source.value_offset != Decimal(0):
            raise ValueError(f"宏观序列 {series_id} 的 value_offset 只支持 published 源")


_assert_offset_only_published(_SOURCES)


class PostgresMacroRepository:
    def __init__(
        self,
        conn: psycopg.Connection[object],
        *,
        contracts: Mapping[str, VisibilityContract] | None = None,
    ) -> None:
        self._conn = conn
        self._contracts = dict(contracts) if contracts is not None else load_macro_visibilities()

    def list_observations(
        self,
        *,
        as_of: date,
        start: date,
        end: date,
        series_ids: tuple[str, ...],
    ) -> tuple[MacroObservation, ...]:
        ids = normalize_series_ids(series_ids)
        if ids is None:
            return ()
        if start > end:
            raise InvalidQueryError("start 晚于 end")
        out: list[MacroObservation] = []
        for series_id in ids:
            out.extend(self._one(series_id, as_of=as_of, start=start, end=end))
        return tuple(sorted(out, key=lambda row: (row.series_id, row.observation_date)))

    def _one(
        self, series_id: str, *, as_of: date, start: date, end: date
    ) -> tuple[MacroObservation, ...]:
        source = _SOURCES.get(series_id)
        if source is None:
            raise MacroLookupError(f"宏观序列没有源表映射: {series_id}")
        contract = self._contracts.get(source.dataset)
        if contract is None:
            raise MissingVisibilityError(source.dataset)
        cutoff = pit_cutoff(contract, as_of=as_of)
        if cutoff.column != source.cutoff_column:
            # 契约换了截止列而映射没跟上，按旧列过滤会悄悄放宽或收紧可见性。
            raise PitUnsupportedError(
                f"{source.dataset} 契约截止列 {cutoff.column} 与读取映射 {source.cutoff_column} 不符"
            )
        if cutoff.fallback is not None:
            # 宏观序列只读主截止列；按 fallback 推断可见日要逐行定级，这里没实现也不估计。
            raise PitUnsupportedError(f"宏观读取不支持 fallback 可见性契约: {source.dataset}")
        if source.kind == "published" and not cutoff.date_only:
            # 截止列是 timestamp，不按 ::date 比较会把发布当天带时刻的记录漏成次日可见。
            raise PitUnsupportedError(
                f"{source.dataset} 截止列 {cutoff.column} 是 timestamp，契约必须声明 date_only"
            )
        with self._conn.cursor() as cur:
            if source.kind == "point":
                visible_end = min(end, cutoff.on_or_before)
                if start > visible_end:
                    return ()
                cur.execute(
                    source.statement, (_ymd(start), _ymd(visible_end), *source.fixed_params)
                )
                versions = [_point_version(series_id, row) for row in cur.fetchall()]
            elif source.kind == "published":
                cur.execute(
                    source.statement, (start, end, cutoff.on_or_before, *source.fixed_params)
                )
                versions = _published_versions(
                    series_id, cur.fetchall(), value_offset=source.value_offset
                )
            else:
                cur.execute(
                    source.statement, (start, end, cutoff.on_or_before, *source.fixed_params)
                )
                versions = [_vintage_version(series_id, row) for row in cur.fetchall()]
        return select_visible_versions(
            versions,
            start=start,
            end=end,
            visible_on_or_before=cutoff.on_or_before,
            pit_grade=cutoff.grade,
        )


def load_macro_visibilities() -> dict[str, VisibilityContract]:
    bundle = load_bundle()
    out: dict[str, VisibilityContract] = {}
    for source in _SOURCES.values():
        vis = bundle.visibilities.get(source.dataset)
        if vis is None:
            raise MissingVisibilityError(source.dataset)
        out[source.dataset] = vis
    return out


def _point_version(series_id: str, row: object) -> MacroVersion:
    obs, value = _unpack(row, 2, series_id)
    observed = _parse_ymd(obs)
    return MacroVersion(
        series_id=series_id,
        observation_date=observed,
        value=_decimal(value, series_id),
        visible_from=observed,
        visible_to=None,
    )


def _published_versions(
    series_id: str, rows: Iterable[object], *, value_offset: Decimal
) -> list[MacroVersion]:
    """同一观测的多个发布版本按发布日排队：前一版在下一版发布前一天失效。

    对应 pit-rules“同指标同期取最晚发布”：截止日可见的是发布日不晚于截止日的最后一版。
    两行发布日相同则无法判定谁是最终值，fail-closed 不挑一版。
    """
    grouped: dict[date, list[tuple[date, Decimal | None]]] = {}
    for row in rows:
        obs, published, value, power = _unpack(row, 4, series_id)
        if not isinstance(obs, date) or not isinstance(published, date):
            raise MacroLookupError(f"{series_id} 观测日或发布日不是日期: {obs!r} {published!r}")
        if power is None or power != 0:
            # PowerNumber 是源端数量级标记；非 0 时 DataValue 还要换算，口径未定不猜。
            raise MacroLookupError(f"{series_id} 数量级不明: {obs} PowerNumber={power!r}")
        grouped.setdefault(obs, []).append((published, _decimal(value, series_id)))
    out: list[MacroVersion] = []
    for obs in sorted(grouped):
        released = sorted(grouped[obs], key=lambda item: item[0])
        for index, (visible_from, value) in enumerate(released):
            visible_to: date | None = None
            if index + 1 < len(released):
                following = released[index + 1][0]
                if following == visible_from:
                    raise MacroLookupError(f"{series_id} {obs} 同一发布日有多个版本")
                visible_to = following - timedelta(days=1)
            out.append(
                MacroVersion(
                    series_id=series_id,
                    observation_date=obs,
                    value=None if value is None else value + value_offset,
                    visible_from=visible_from,
                    visible_to=visible_to,
                )
            )
    return out


def _vintage_version(series_id: str, row: object) -> MacroVersion:
    obs, realtime_start, realtime_end, value = _unpack(row, 4, series_id)
    if not isinstance(obs, date) or not isinstance(realtime_start, date):
        raise MacroLookupError(f"{series_id} 版本日期缺失: {obs!r} {realtime_start!r}")
    if realtime_end is not None and not isinstance(realtime_end, date):
        raise MacroLookupError(f"{series_id} realtime_end 非日期: {realtime_end!r}")
    return MacroVersion(
        series_id=series_id,
        observation_date=obs,
        value=_decimal(value, series_id),
        visible_from=realtime_start,
        visible_to=realtime_end,
    )


def _unpack(row: object, width: int, series_id: str) -> tuple[object, ...]:
    if not isinstance(row, tuple) or len(row) != width:
        raise MacroLookupError(f"{series_id} 读取行形状不符: {row!r}")
    return row


def _parse_ymd(value: object) -> date:
    if not isinstance(value, str) or len(value) != _YMD_LEN or not value.isdigit():
        raise MacroLookupError(f"业务日必须是 YYYYMMDD: {value!r}")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise MacroLookupError(f"业务日不是合法日期: {value!r}") from exc


def _decimal(value: object, series_id: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MacroLookupError(f"{series_id} 观测值不是有限值")
        return value
    raise MacroLookupError(f"{series_id} 观测值不是数值: {type(value).__name__}")


def _ymd(value: date) -> str:
    return value.strftime("%Y%m%d")
