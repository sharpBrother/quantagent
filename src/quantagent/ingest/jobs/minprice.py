"""单日分钟源镜像任务。异常和未知事务状态均停止，不自动重试。"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from datetime import time as time_of_day
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import Field

from quantagent.domain.minute_exclusions import JANUARY_21, JANUARY_21_EXCLUDED
from quantagent.ingest.errors import ReplaceRequiredError, SourceFetchError, SourceNotReadyError
from quantagent.ingest.jobs.minprice_corrections import (
    correct_known_row,
    reconcile_negative_amounts,
)
from quantagent.ingest.jobs.minprice_validation import content_digest, validate_day
from quantagent.ingest.sources.minprice import read_day
from quantagent.ingest.writers.minprice_manifest import register_partition
from quantagent.ingest.writers.minprice_parquet import stage_partition
from quantagent.platform.config import assert_db_write_allowed
from quantagent.platform.identity import digest_file
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Iterable

    from quantagent.domain.ports.calendar import CalendarRepository
    from quantagent.domain.ports.prices import DailyPriceRepository
    from quantagent.platform.config import Settings
    from quantagent.platform.storage.paths import VarPaths

_NAMES = ("ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount")
_EXPECTED_BARS = 241
_JANUARY_21_NEGATIVE_COUNT = 103
_APPROVED_NEGATIVE_VOLUME = {
    date(2026, 1, 22): (("002485.SZ", Decimal("-28")),),
    date(2026, 3, 26): (("920242.BJ", Decimal("-31")),),
    date(2026, 4, 16): (("920855.BJ", Decimal("-37")),),
    date(2026, 4, 30): (("920608.BJ", Decimal("422")),),
    date(2026, 6, 2): (("920112.BJ", Decimal("1037")),),
    date(2026, 6, 8): (("920608.BJ", Decimal("-51")),),
    date(2026, 6, 22): (("920855.BJ", Decimal("-7")),),
    date(2026, 6, 29): (("920608.BJ", Decimal("11")),),
    date(2026, 7, 6): (("920455.BJ", Decimal("-41")), ("920541.BJ", Decimal("391"))),
    date(2026, 7, 8): (("920132.BJ", Decimal("-56")),),
    date(2026, 7, 9): (("920422.BJ", Decimal("337")),),
    date(2026, 7, 14): (("920422.BJ", Decimal("11")),),
    date(2026, 7, 15): (("920112.BJ", Decimal("28")), ("920168.BJ", Decimal("-53"))),
    date(2026, 7, 17): (("920121.BJ", Decimal("2063")),),
    date(2026, 7, 22): (("603869.SH", Decimal("-22")), ("920108.BJ", Decimal("19"))),
    date(2026, 7, 24): (("920112.BJ", Decimal("-12")),),
    date(2026, 7, 28): (("920370.BJ", Decimal("129")),),
    date(2026, 8, 4): (("920395.BJ", Decimal("91")),),
    date(2026, 8, 17): (("920121.BJ", Decimal("1462")), ("920679.BJ", Decimal("10"))),
    date(2026, 8, 20): (("920146.BJ", Decimal("37")), ("920395.BJ", Decimal("-42"))),
    date(2026, 8, 24): (
        ("920168.BJ", Decimal("378")),
        ("920275.BJ", Decimal("-62")),
        ("920679.BJ", Decimal("-37")),
    ),
    date(2026, 9, 10): (("920177.BJ", Decimal("971")),),
    date(2026, 9, 15): (
        ("920121.BJ", Decimal("205")),
        ("920166.BJ", Decimal("2")),
        ("920168.BJ", Decimal("542")),
    ),
}
_PREVIOUSLY_APPROVED_DATES = frozenset(
    {
        date(2025, 10, 17),
        date(2025, 10, 28),
        date(2025, 11, 26),
        date(2025, 12, 8),
        date(2025, 12, 11),
        date(2025, 12, 29),
        date(2026, 1, 13),
    }
)
_SCHEMA = pa.schema(
    [
        ("ts_code", pa.string()),
        ("trade_time", pa.timestamp("us")),
        *[(name, pa.decimal128(20, 4)) for name in _NAMES[2:]],
    ]
)


class MinuteRunLog(RunLog):
    trade_date: date
    unusual_bar_counts: dict[str, int] = Field(default_factory=dict)
    tolerated_open_below_low: list[dict[str, str]] = Field(default_factory=list)
    source_corrections: list[dict[str, str]] = Field(default_factory=list)
    excluded_codes: list[str] = Field(default_factory=list)
    amount_comparisons: list[dict[str, str]] = Field(default_factory=list)
    outcome: str = "unknown"


def assert_daily_ready(table: pa.Table, previous_code_count: int) -> None:
    """当前数据至少到 15:00，股票数不低于上一个交易日的 95%。"""
    if previous_code_count <= 0 or table.num_rows == 0:
        raise SourceNotReadyError("上一交易日股票数不可用或当日无行情")
    latest = pc.max(table["trade_time"]).as_py()
    codes = len(pc.unique(table["ts_code"]))
    if latest.time() != time_of_day(15) or codes * 100 < previous_code_count * 95:
        raise SourceNotReadyError("当日分钟行情尚未出齐")


def ingest_day(  # noqa: PLR0912, PLR0915
    mysql: Any,
    pg: Any,
    *,
    trade_date: date,
    settings: Settings,
    paths: VarPaths,
    calendar: CalendarRepository,
    previous_code_count: int | None = None,
    daily_prices: DailyPriceRepository | None = None,
    source_batches: Iterable[list[Any]] | None = None,
    source_table: str | None = None,
    write_db: bool = False,
) -> str:
    """处理一个日期，写入前完成内容验证；已有相同 digest 不重复写。"""
    if (source_batches is None and source_table is not None) or (
        source_batches is not None and source_table != "eastmoney.trends2"
    ):
        raise ValueError("分钟行情来源和输入不匹配")
    if write_db:
        assert_db_write_allowed(settings=settings, write_db=True)
    started = datetime.now(UTC)
    started_clock = time.monotonic()
    input_digest: str | None = None
    original_input_digest: str | None = None
    output_digest: str | None = None
    row_count: int | None = None
    dml_count = 0
    failure: str | None = None
    outcome = "failed"
    unusual_bar_counts: dict[str, int] = {}
    tolerated_open_below_low: list[dict[str, str]] = []
    source_corrections: list[dict[str, str]] = []
    excluded_codes: list[str] = []
    amount_comparisons: list[dict[str, str]] = []
    try:
        table_name = "m" + trade_date.strftime("%Y%m%d")
        batches = []
        source = (
            source_batches
            if source_batches is not None
            else read_day(mysql, database=settings.minprice_mysql_database, table=table_name)
        )
        for rows in source:
            arrays = [
                pa.array([row[i] for row in rows], type=field.type)
                for i, field in enumerate(_SCHEMA)
            ]
            batches.append(pa.RecordBatch.from_arrays(arrays, schema=_SCHEMA))
        table = pa.Table.from_batches(batches, schema=_SCHEMA)
        volume_fixes = (
            _APPROVED_NEGATIVE_VOLUME.get(trade_date, ()) if source_batches is None else ()
        )
        if volume_fixes:
            original_input_digest = content_digest(
                table.append_column(
                    "trade_date", pa.array([trade_date] * table.num_rows, type=pa.date32())
                )
            )
        for fix_code, fix_amount in volume_fixes:
            fix_time = datetime.combine(trade_date, time_of_day(15))
            # 只修复用户确认的源记录；负成交额仍交由日行情规则校验。
            mask = pc.and_(
                pc.equal(table["ts_code"], fix_code),
                pc.equal(table["trade_time"], fix_time),
            )
            matches = table.filter(mask).select(["vol", "amount"]).to_pylist()
            if matches != [{"vol": Decimal("-1"), "amount": fix_amount}]:
                raise SourceFetchError(f"{trade_date} 指定修正记录不存在、重复或原值已变化")
            index = table.schema.get_field_index("vol")
            table = table.set_column(
                index, "vol", pc.if_else(mask, pa.scalar(0, type=table["vol"].type), table["vol"])
            )
            if fix_amount >= 0:
                # 正成交额也置零仅适用于负责人明确确认的这一行。
                index = table.schema.get_field_index("amount")
                table = table.set_column(
                    index,
                    "amount",
                    pc.if_else(mask, pa.scalar(0, type=table["amount"].type), table["amount"]),
                )
        if source_batches is None and trade_date == JANUARY_21:
            # 源异常集合变化时停止，不能套用过期裁定。
            negative = table.filter(pc.less(table["amount"], 0))
            affected = set(negative["ts_code"].to_pylist())
            if (
                negative.num_rows != _JANUARY_21_NEGATIVE_COUNT
                or affected
                != JANUARY_21_EXCLUDED
                | {
                    "899002.BJ",
                    "899050.BJ",
                }
            ):
                raise ValueError("2026-01-21 异常代码集合已变化")
            original_input_digest = content_digest(
                table.append_column(
                    "trade_date", pa.array([trade_date] * table.num_rows, type=pa.date32())
                )
            )
            excluded_codes = sorted(JANUARY_21_EXCLUDED)
            table = table.filter(
                pc.invert(pc.is_in(table["ts_code"], value_set=pa.array(excluded_codes)))
            )
        if (
            source_batches is None
            and trade_date != JANUARY_21
            and trade_date not in _PREVIOUSLY_APPROVED_DATES
            and pc.any(pc.less(table["amount"], 0)).as_py()
        ):
            if daily_prices is None:
                raise ValueError("负成交额需要同日日行情才能判断")
            if original_input_digest is None:
                original_input_digest = content_digest(
                    table.append_column(
                        "trade_date", pa.array([trade_date] * table.num_rows, type=pa.date32())
                    )
                )
            corrected, source_corrections, excluded_codes, amount_comparisons = (
                reconcile_negative_amounts(table, trade_date=trade_date, prices=daily_prices)
            )
        else:
            corrected, source_corrections = correct_known_row(
                table, trade_date=trade_date, is_mysql=source_batches is None
            )
        for fix_code, fix_amount in volume_fixes:
            fix_time = datetime.combine(trade_date, time_of_day(15))
            if fix_amount >= 0:
                if fix_code in excluded_codes:
                    raise SourceFetchError(f"{trade_date} 指定记录的股票被排除，停止入库")
                source_corrections.append(
                    {
                        "ts_code": fix_code,
                        "trade_time": fix_time.isoformat(sep=" "),
                        "vol_before": "-1.0000",
                        "vol_after": "0.0000",
                        "amount_before": f"{fix_amount:.4f}",
                        "amount_after": "0.0000",
                    }
                )
            else:
                # 记录原始负成交量，确保日志反映两个字段的修正。
                matches = [
                    item
                    for item in source_corrections
                    if item["ts_code"] == fix_code
                    and item["trade_time"] == fix_time.isoformat(sep=" ")
                ]
                if len(matches) != 1:
                    raise SourceFetchError(f"{trade_date} 指定记录未通过成交额对比，停止入库")
                matches[0]["vol_before"] = "-1.0000"
        if source_corrections and original_input_digest is None:
            source_dates = pa.array([trade_date] * table.num_rows, type=pa.date32())
            original_input_digest = content_digest(table.append_column("trade_date", source_dates))
        table = corrected
        checked = validate_day(table, trade_date=trade_date)
        tolerated = checked.filter(pc.less(checked["open"], checked["low"]))
        tolerated_open_below_low = [
            {key: str(value) for key, value in item.items()}
            for item in tolerated.select(["ts_code", "trade_time", "open", "low"]).to_pylist()
        ]
        if previous_code_count is not None:
            assert_daily_ready(checked, previous_code_count)
        row_count = checked.num_rows
        counts = checked.group_by("ts_code").aggregate([("ts_code", "count")]).to_pylist()
        unusual_bar_counts = {
            item["ts_code"]: item["ts_code_count"]
            for item in counts
            if item["ts_code_count"] != _EXPECTED_BARS
        }
        input_digest = content_digest(checked)
        if not write_db:
            return "dry_run"
        with pg.cursor() as cur:
            cur.execute(
                "SELECT content_digest,file_name,row_count,file_sha256 FROM src_minprice.lake_partition "
                "WHERE dataset=%s AND trade_date=%s",
                ("ashare_minute_bar", trade_date),
            )
            existing = cur.fetchone()
        if existing is not None and existing[0] == input_digest:
            root = (paths.lake / "src" / "minprice" / "ashare_minute_bar").resolve()
            existing_path = (root / existing[1]).resolve()
            if (
                not existing_path.is_relative_to(root)
                or not existing_path.is_file()
                or pq.ParquetFile(existing_path).metadata.num_rows != existing[2]
                or digest_file(existing_path) != existing[3]
            ):
                raise ValueError("已登记分钟分区缺失或校验失败，不可跳过")
            output_digest = input_digest
            outcome = "skipped"
            return "skipped"
        if existing is not None:
            raise ReplaceRequiredError("分钟分区已存在且内容不同，禁止自动覆盖")
        partition = stage_partition(
            table,
            trade_date=trade_date,
            calendar=calendar,
            settings=settings,
            paths=paths,
            write_db=True,
            excluded_codes=excluded_codes,
        )
        register_partition(
            pg,
            partition=partition,
            trade_date=trade_date,
            settings=settings,
            expected_digest=None if existing is None else existing[0],
            source_table=source_table,
            write_db=True,
        )
        output_digest = partition.content_digest
        dml_count = 2
        outcome = "inserted"
        return "inserted"
    except SourceNotReadyError:
        outcome = "not_ready"
        raise
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if write_db:
            finished = datetime.now(UTC)
            record = MinuteRunLog(
                trade_date=trade_date,
                outcome=outcome,
                unusual_bar_counts=unusual_bar_counts,
                tolerated_open_below_low=tolerated_open_below_low,
                source_corrections=source_corrections,
                excluded_codes=excluded_codes,
                amount_comparisons=amount_comparisons,
                action="ingest.minprice.day",
                status="failure" if failure else "success",
                started_at=started,
                finished_at=finished,
                elapsed_ms=int((time.monotonic() - started_clock) * 1000),
                input_digest=original_input_digest or input_digest,
                output_digest=output_digest,
                row_count=row_count,
                dml_count=dml_count,
                error=failure,
            )
            persist_run_log(record, paths)
