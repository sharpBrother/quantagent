"""``std.trade_calendar``：源镜像改名与类型规整，不做口径加工。"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quantagent.adapters.postgres.src_scan import scan_trade_cal
from quantagent.contracts.loader import load_bundle
from quantagent.contracts.pandera_schema import to_pandera
from quantagent.lake.partitions.layout import LakeLayoutError
from quantagent.platform.errors import RunLogError
from quantagent.platform.identity import digest_file, digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date
    from pathlib import Path

    import psycopg

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

DATASET = "std.trade_calendar"
ACTION = "lake.materialize.std.trade_calendar"
_STD_COLUMNS = ("cal_dt", "exchange", "is_open", "prev_trade_dt")
_YMD_LEN = 8


@dataclass(frozen=True)
class TradeCalendarMaterializeResult:
    dataset: str
    row_count: int
    output_digest: str
    path: Path
    rebuilt: bool


def src_rows_to_std(rows: Sequence[Mapping[str, object]]) -> pa.Table:
    if not rows:
        raise LakeLayoutError("std.trade_calendar 拒绝空表")
    records = [_src_row_to_std(row, index) for index, row in enumerate(rows)]
    frame = pd.DataFrame.from_records(records, columns=list(_STD_COLUMNS))
    to_pandera(load_bundle().schemas[DATASET]).validate(frame)
    table = pa.Table.from_pydict(
        {
            "cal_dt": pa.array([record["cal_dt"] for record in records], type=pa.date32()),
            "exchange": pa.array([record["exchange"] for record in records], type=pa.string()),
            "is_open": pa.array([record["is_open"] for record in records], type=pa.bool_()),
            "prev_trade_dt": pa.array(
                [record["prev_trade_dt"] for record in records],
                type=pa.date32(),
            ),
        }
    )
    return table.sort_by([("cal_dt", "ascending"), ("exchange", "ascending")])


def materialize_trade_calendar(
    *,
    settings: Settings,
    paths: VarPaths,
    as_of: date,
    rebuild: bool = False,
    src_rows: Sequence[Mapping[str, object]] | None = None,
    conn: psycopg.Connection[object] | None = None,
) -> TradeCalendarMaterializeResult:
    started = datetime.now(UTC)
    dest = paths.lake / "std" / "trade_calendar"
    owned_conn = None
    try:
        rows: list[dict[str, object]]
        if src_rows is not None:
            rows = [dict(row) for row in src_rows]
        elif conn is not None:
            rows = scan_trade_cal(conn)
        else:
            owned_conn = connect(settings, "src")
            rows = scan_trade_cal(owned_conn)
        table = src_rows_to_std(rows)
        written = _write_std_parquet(table, dest, rebuild=rebuild)
        result = TradeCalendarMaterializeResult(
            dataset=DATASET,
            row_count=table.num_rows,
            output_digest=str(written["digest"]),
            path=written["path"],  # type: ignore[arg-type]
            rebuilt=rebuild,
        )
    except Exception as exc:
        with suppress(RunLogError):
            _persist(
                paths=paths,
                started=started,
                as_of=as_of,
                rebuild=rebuild,
                dest=dest,
                status="failure",
                error=str(exc),
            )
        raise
    finally:
        if owned_conn is not None:
            owned_conn.close()
    _persist(
        paths=paths,
        started=started,
        as_of=as_of,
        rebuild=rebuild,
        dest=dest,
        status="success",
        result=result,
    )
    return result


def _write_std_parquet(table: pa.Table, dest: Path, *, rebuild: bool) -> dict[str, object]:
    dest.mkdir(parents=True, exist_ok=True)
    final_path = dest / "part-00000.parquet"
    existing = [path for path in dest.glob("*.parquet") if path.is_file()]
    if existing and not rebuild:
        raise LakeLayoutError(f"拒绝覆盖既有分区: {dest}")
    tmp_path = dest / "part-00000.parquet.tmp"
    if tmp_path.exists():
        tmp_path.unlink()
    pq.write_table(table, tmp_path, compression="zstd", write_statistics=True)
    readback = pq.read_table(tmp_path)
    if readback.num_rows != table.num_rows:
        tmp_path.unlink(missing_ok=True)
        raise LakeLayoutError(
            f"写后回读行数不一致: wrote={table.num_rows} read={readback.num_rows}"
        )
    file_digest = digest_file(tmp_path)
    if rebuild:
        for path in existing:
            path.unlink()
    tmp_path.replace(final_path)
    return {"path": final_path, "digest": file_digest}


def _src_row_to_std(row: Mapping[str, object], index: int) -> dict[str, object]:
    cal_dt = _parse_ymd(row.get("cal_date"), field="cal_date", nullable=False)
    prev = _parse_ymd(row.get("pretrade_date"), field="pretrade_date", nullable=True)
    is_open: object = row.get("is_open")
    item = getattr(is_open, "item", None)
    if callable(item):
        is_open = item()
    if is_open not in {0, 1}:
        raise LakeLayoutError(f"第 {index} 行 is_open 不是 0/1，拒绝填充: {is_open!r}")
    exchange = row.get("exchange")
    if not isinstance(exchange, str) or not exchange.strip():
        raise LakeLayoutError(f"第 {index} 行 exchange 为空")
    return {
        "cal_dt": cal_dt,
        "exchange": exchange,
        "is_open": bool(is_open),
        "prev_trade_dt": prev,
    }


def _parse_ymd(value: object, *, field: str, nullable: bool) -> object:
    if value is None:
        if nullable:
            return None
        raise LakeLayoutError(f"{field} 为空")
    text = str(value).strip()
    if len(text) != _YMD_LEN or not text.isdigit():
        raise LakeLayoutError(f"{field} 必须是 YYYYMMDD: {value!r}")
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise LakeLayoutError(f"{field} 不是合法日期: {value!r}") from exc


def _persist(
    *,
    paths: VarPaths,
    started: datetime,
    as_of: date,
    rebuild: bool,
    dest: Path,
    status: Literal["success", "failure"],
    result: TradeCalendarMaterializeResult | None = None,
    error: str | None = None,
) -> None:
    finished = datetime.now(UTC)
    record = RunLog(
        action=ACTION,
        status=status,
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json(
            {
                "dataset": DATASET,
                "as_of": as_of.isoformat(),
                "rebuild": rebuild,
                "dest": dest.as_posix(),
            }
        ),
        output_digest=None if result is None else result.output_digest,
        row_count=None if result is None else result.row_count,
        dml_count=0,
        error=error,
    )
    persist_run_log(record, paths)
