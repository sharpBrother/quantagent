"""WGC HTML 周更：按旧仓报告期映射、保留每个变化版本。"""

from __future__ import annotations

import hashlib
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from quantagent.adapters.postgres.src_targets import WGC_GOLD_DEMAND
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.adapters.postgres.wgc_legacy import wgc_report_dates
from quantagent.ingest.errors import IngestError
from quantagent.ingest.sources.macro.wgc_html import fetch_latest_report
from quantagent.ingest.writers.src_insert import write_src_snapshot
from quantagent.platform.errors import RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from decimal import Decimal

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

_SOURCE = "wgc:gdt_html"
_COMPARE = ("period_end", "geography", "category", "value_tonnes", "publish_date", "source")


def build_rows(
    publish: str,
    sha: str,
    points: Sequence[tuple[str, str, Decimal]],
    dates: Mapping[str, str],
    stamp: datetime,
) -> list[dict[str, object]]:
    rows = []
    for period, category, value in points:
        visible = dates.get(period, publish)
        text = "|".join((period, "WORLD", category, format(value, "f"), visible, _SOURCE))
        rows.append(
            {
                "period_end": period,
                "geography": "WORLD",
                "category": category,
                "value_tonnes": value,
                "publish_date": visible,
                "source": _SOURCE,
                "file_sha256": sha,
                "record_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "ingested_at": stamp,
            }
        )
    return rows


def select_new_rows(
    rows: Sequence[dict[str, object]],
    existing: Mapping[tuple[object, ...], tuple[object, ...]],
) -> list[dict[str, object]]:
    """已有业务值一致则跳过页面动态变化；同键异值停止。"""
    new: list[dict[str, object]] = []
    for row in rows:
        old = existing.get((row["record_hash"],))
        if old is None:
            new.append(row)
        elif old != tuple(row[col] for col in _COMPARE):
            raise IngestError(f"WGC record_hash 与旧业务列冲突: {row['record_hash']}")
    return new


def ingest_wgc_html(
    *, settings: Settings, paths: VarPaths, write_db: bool = False
) -> tuple[int, int, str]:
    started = datetime.now(UTC)
    try:
        publish, sha, points = fetch_latest_report()
        with connect(settings, "src") as conn:
            dates = wgc_report_dates(conn)
            stamp = datetime.now(UTC).replace(tzinfo=None)
            rows = build_rows(publish, sha, points, dates, stamp)
            store = PostgresSrcStore(conn)
            keys = [(r["record_hash"],) for r in rows]
            existing = store.existing_values(WGC_GOLD_DEMAND, keys, _COMPARE)
            new = select_new_rows(rows, existing)
            # 内容身份不含本次采集时间，输入相同时可复现。
            digest = digest_json({"publish_date": publish, "file_sha256": sha, "points": points})
            result = None
            if new:
                result = write_src_snapshot(
                    spec=WGC_GOLD_DEMAND,
                    rows=new,
                    settings=settings,
                    write_db=write_db,
                    store=store,
                )
            finished = datetime.now(UTC)
            persist_run_log(
                RunLog(
                    action="ingest.macro.wgc_html",
                    status="success",
                    started_at=started,
                    finished_at=finished,
                    elapsed_ms=int((finished - started).total_seconds() * 1000),
                    input_digest=digest,
                    output_digest=result.output_digest if result else digest,
                    row_count=len(new),
                    dml_count=result.dml_count if result else 0,
                ),
                paths,
            )
            return len(rows), len(new), sha
    except Exception as exc:
        finished = datetime.now(UTC)
        with suppress(RunLogError):
            persist_run_log(
                RunLog(
                    action="ingest.macro.wgc_html",
                    status="failure",
                    started_at=started,
                    finished_at=finished,
                    elapsed_ms=int((finished - started).total_seconds() * 1000),
                    error=type(exc).__name__,
                ),
                paths,
            )
        raise
