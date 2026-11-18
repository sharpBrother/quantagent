"""从已保存的 wx2 快照迁入日期无法确认的历史 ISM 记录。"""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from quantagent.adapters.postgres.errors import TransactionUnknownError
from quantagent.adapters.postgres.src_targets import JIN10_ECONOMIC_CALENDAR
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.errors import IngestError
from quantagent.ingest.writers.src_insert import write_src_snapshot
from quantagent.ingest.writers.tables import assert_writable
from quantagent.platform.config.write_gate import assert_db_write_allowed
from quantagent.platform.errors import RunLogError
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.ingest.writers.src_insert import SrcWriteResult
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

_HISTORICAL_MONTHS = 456
_RECENT_ROWS = 215

# 同期报告只用于核正发布时间和统计期； actual/forecast/previous 仍逐字取金十快照。
_VERIFIED_RELEASES: dict[date, tuple[date, date, str]] = {
    date(2002, 3, 1): (
        date(2002, 3, 1),
        date(2002, 2, 28),
        "https://www.sdcexec.com/warehousing/press-release/10311046/institute-for-supply-management-ism-ism-index-surges-to-547",
    ),
    date(2007, 3, 1): (
        date(2007, 3, 1),
        date(2007, 2, 28),
        "https://documents1.worldbank.org/curated/en/560871468330965394/pdf/604870NEWS0DEC1BOX0358321B01PUBLIC1.pdf",
    ),
    date(2007, 4, 1): (
        date(2007, 4, 2),
        date(2007, 3, 31),
        "https://whattheythink.com/news/3261-march-manufacturing-ism-report-business-pmi-509/",
    ),
    date(2007, 5, 1): (
        date(2007, 5, 1),
        date(2007, 4, 30),
        "https://www.manufacturing.net/supply-chain/news/13061540/manufacturing-expands-in-april-beating-expectations-and-a-sluggish-economy",
    ),
    date(2007, 6, 1): (
        date(2007, 6, 1),
        date(2007, 5, 31),
        "https://fraser.stlouisfed.org/title/us-financial-data-5335/june-1-2007-537326/content/fulltext/frbsl_usfd_20070601",
    ),
    date(2007, 7, 1): (
        date(2007, 7, 2),
        date(2007, 6, 30),
        "https://whattheythink.com/news/1818-june-manufacturing-ism-report-business-pmi-56/",
    ),
    date(2007, 8, 1): (
        date(2007, 8, 1),
        date(2007, 7, 31),
        "https://fraser.stlouisfed.org/title/us-financial-data-5335/august-3-2007-537335/content/fulltext/frbsl_usfd_20070803",
    ),
    date(2007, 9, 1): (
        date(2007, 9, 4),
        date(2007, 8, 31),
        "https://fraser.stlouisfed.org/title/us-financial-data-5335/september-7-2007-537340/content/fulltext/frbsl_usfd_20070906",
    ),
    date(2007, 10, 1): (
        date(2007, 10, 1),
        date(2007, 9, 30),
        "https://fraser.stlouisfed.org/title/us-financial-data-5335/october-5-2007-537344/content/fulltext/frbsl_usfd_20071004",
    ),
    date(2007, 11, 1): (
        date(2007, 11, 1),
        date(2007, 10, 31),
        "https://www.ftportfolios.com/Commentary/EconomicResearch/2007/11/1/ISM_Manufacturing_Index_declines_to_50.9_in_October",
    ),
    date(2008, 1, 1): (
        date(2008, 1, 2),
        date(2007, 12, 31),
        "https://fraser.stlouisfed.org/title/us-financial-data-5335/january-4-2008-537357/content/fulltext/frbsl_usfd_20080103",
    ),
    date(2008, 2, 1): (
        date(2008, 2, 1),
        date(2008, 1, 31),
        "https://www.ftportfolios.com/Commentary/EconomicResearch/2008/2/1/_ISM_Manufacturing_Index_increased_to_50.7_in_January",
    ),
    date(2018, 12, 3): (
        date(2018, 12, 3),
        date(2018, 11, 30),
        "https://www.prnewswire.com/news-releases/pmi-at-59-3-november-manufacturing-ism-report-on-business-300757695.html",
    ),
}


def _legacy_values(item: dict[str, object]) -> dict[str, Decimal | None]:
    values: dict[str, Decimal | None] = {}
    for column in ("actual_value", "forecast_value", "previous_value"):
        raw = item[column]
        number = None if raw is None else Decimal(str(raw))
        if number is not None and not number.is_finite():
            raise IngestError("ISM 历史值不是有限数")
        values[column] = number
    return values


def read_legacy_snapshot(path: Path, *, segment: str = "1970-2007") -> list[dict[str, object]]:
    """保留原始月初占位日期，不推测发布时间和统计期。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("source") != "wx2.dbo.macro_jin10_usa_ism_pmi"
        ):
            raise IngestError("ISM 快照来源不匹配")
        records = payload["records"]
        if not isinstance(records, list) or len(records) != payload["row_count"]:
            raise IngestError("ISM 快照行数不匹配")
        if segment not in {"1970-2007", "2008-2025"}:
            raise IngestError("ISM 历史分段无效")
        historical = segment == "1970-2007"
        start, end = (
            (date(1970, 1, 1), date(2008, 1, 1))
            if historical
            else (date(2008, 1, 1), date(2025, 10, 1))
        )
        expected_rows = _HISTORICAL_MONTHS if historical else _RECENT_ROWS
        rows: list[dict[str, object]] = []
        for item in records:
            source_date = date.fromisoformat(item["publish_date"])
            if not start <= source_date < end:
                continue
            if historical and source_date.day != 1:
                raise IngestError("ISM 历史占位日期不是月初")
            values = _legacy_values(item)
            base_source = (
                "jin10.wx2.legacy_unknown_release" if historical else "jin10.wx2.reports_list_v2"
            )
            verified = _VERIFIED_RELEASES.get(source_date)
            if verified is None:
                published_date = source_date
                period_end = (
                    None
                    if historical or item["period_end"] is None
                    else date.fromisoformat(item["period_end"])
                )
                source = base_source
            else:
                published_date, period_end, url = verified
                source = f"{base_source};publish_date_verified={url}"
            rows.append(
                {
                    "indicator_id": 129,
                    "publish_date": published_date,
                    "data_id": 0,
                    "period_end": period_end,
                    "time_period": None,
                    "published_at": None,
                    **values,
                    "revised_value": None,
                    "source": source,
                }
            )
        if len(rows) != expected_rows or len({r["publish_date"] for r in rows}) != expected_rows:
            raise IngestError("ISM 历史月份缺失或重复")
        return rows
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation) as exc:
        raise IngestError(f"ISM 快照无效: {type(exc).__name__}") from exc


def _delete_existing_legacy(
    store: PostgresSrcStore, original_date: date, *, verified: tuple[date, date, str]
) -> None:
    key = (129, verified[0], 0)
    found = store.existing_values(JIN10_ECONOMIC_CALENDAR, [key], ["source"])
    source = found.get(key, (None,))[0]
    allowed_sources = {
        "jin10.wx2.legacy_unknown_release",
        "jin10.wx2.reports_list_v2",
        f"ism.first_release:{verified[2]}",
        f"ism.first_release+jin10.wx2:{verified[2]}",
        f"jin10.wx2.legacy_unknown_release;publish_date_verified={verified[2]}",
        f"jin10.wx2.reports_list_v2;publish_date_verified={verified[2]}",
    }
    if source not in allowed_sources:
        raise IngestError(f"替换目标 {original_date} 不存在或来源已变化")
    store.delete_keys(JIN10_ECONOMIC_CALENDAR, [key])
    if store.existing_keys(JIN10_ECONOMIC_CALENDAR, [key]):
        raise IngestError("替换目标删除后仍存在")


def ingest_jin10_ism_legacy(
    *,
    settings: Settings,
    paths: VarPaths,
    snapshot: Path,
    write_db: bool = False,
    replace_original_date: date | None = None,
    segment: str = "1970-2007",
) -> SrcWriteResult:
    started = datetime.now(UTC)
    conn = None
    store = None
    try:
        rows = read_legacy_snapshot(snapshot, segment=segment)
        if replace_original_date is not None:
            verified = _VERIFIED_RELEASES.get(replace_original_date)
            if verified is None:
                raise IngestError("替换须指定已有证据的原始日期")
            rows = [row for row in rows if row["publish_date"] == verified[0]]
            if len(rows) != 1:
                raise IngestError("替换范围没有唯一行")
        if write_db:
            assert_writable(JIN10_ECONOMIC_CALENDAR, profile=settings.profile)
            assert_db_write_allowed(settings=settings, write_db=True)
            conn = connect(settings, "src")
            store = PostgresSrcStore(conn)
            if replace_original_date is not None:
                if verified is None:
                    raise IngestError("更正证据在本批次中不存在")
                _delete_existing_legacy(store, replace_original_date, verified=verified)
        result = write_src_snapshot(
            spec=JIN10_ECONOMIC_CALENDAR,
            rows=rows,
            settings=settings,
            write_db=write_db,
            store=store,
        )
        if write_db and replace_original_date is not None:
            result = replace(result, dml_count=result.dml_count + 1)
    except Exception as exc:
        if store is not None and not isinstance(exc, TransactionUnknownError):
            try:
                store.rollback()
            except TransactionUnknownError as rollback_exc:
                exc = rollback_exc
        finished = datetime.now(UTC)
        with suppress(RunLogError):
            persist_run_log(
                RunLog(
                    action="ingest.macro.jin10_ism_legacy",
                    status="failure",
                    started_at=started,
                    finished_at=finished,
                    elapsed_ms=int((finished - started).total_seconds() * 1000),
                    error=type(exc).__name__,
                ),
                paths,
            )
        raise exc
    finally:
        if conn is not None:
            conn.close()
    finished = datetime.now(UTC)
    persist_run_log(
        RunLog(
            action="ingest.macro.jin10_ism_legacy",
            status="success",
            started_at=started,
            finished_at=finished,
            elapsed_ms=int((finished - started).total_seconds() * 1000),
            input_digest=result.payload_digest,
            output_digest=result.output_digest,
            row_count=result.row_count,
            dml_count=result.dml_count,
        ),
        paths,
    )
    return result
