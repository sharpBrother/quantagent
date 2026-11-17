"""``std.trade_calendar``：将源适配器生成的日历快照写为 Parquet。

两种写法：
- 整快照（默认）：目录里只允许一个分片，``rebuild=True`` 才能整体替换。
- 追加（``append_only=True``）：每天只把快照里新出现的日期写成新分片，既有分片一律不动。
"""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
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

# 日更只落到 as_of 之后 7 个自然日。
# 原因：Wind 日历把 SSE/SZSE 预填到 2040 年，年底公布休市安排时会改写这些远期行。
# 远期行若落盘，每次改写都会被判为"已写入的行被改"而拒绝。读取端按 cal_dt <= as_of
# 可见，远期行本来就读不到，截断不影响 PIT 查询。
DAILY_HORIZON_DAYS = 7

_STD_COLUMNS = ("cal_dt", "exchange", "is_open", "prev_trade_dt")
_YMD_LEN = 8
_SHARD_RE = re.compile(r"part-(\d{5})\.parquet")
_KEY_PREVIEW = 5

# 键为 (cal_dt, exchange)，值为两个可变字段；追加模式只允许新增键，不允许改值。
_Key = tuple["date", str]
_Value = tuple[bool, "date | None"]


@dataclass(frozen=True)
class TradeCalendarMaterializeResult:
    dataset: str
    # 本次写入的行数；追加模式下为增量行数，无增量时为 0。
    row_count: int
    output_digest: str
    # 整快照模式为写入的文件；追加模式为目录，分片数随运行增长。
    path: Path
    rebuilt: bool
    appended: int


@dataclass(frozen=True)
class _WriteOutcome:
    path: Path
    digest: str
    appended: int
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
    append_only: bool = False,
    horizon_days: int | None = None,
) -> TradeCalendarMaterializeResult:
    started = datetime.now(UTC)
    dest = paths.lake / "std" / "trade_calendar"
    owned_conn = None
    try:
        _check_options(rebuild=rebuild, append_only=append_only, horizon_days=horizon_days)
        rows: list[dict[str, object]]
        if src_rows is not None:
            rows = [dict(row) for row in src_rows]
        elif conn is not None:
            rows = scan_trade_cal(conn)
        else:
            owned_conn = connect(settings, "src")
            rows = scan_trade_cal(owned_conn)
        table = src_rows_to_std(rows)
        if horizon_days is not None:
            table = _truncate_horizon(table, as_of=as_of, horizon_days=horizon_days)
        if append_only:
            outcome = _append_std_parquet(table, dest)
        else:
            outcome = _write_std_parquet(table, dest, rebuild=rebuild)
        result = TradeCalendarMaterializeResult(
            dataset=DATASET,
            row_count=outcome.appended,
            output_digest=outcome.digest,
            path=outcome.path,
            rebuilt=outcome.rebuilt,
            appended=outcome.appended,
        )
    except Exception as exc:
        with suppress(RunLogError):
            _persist(
                paths=paths,
                started=started,
                as_of=as_of,
                rebuild=rebuild,
                append_only=append_only,
                horizon_days=horizon_days,
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
        append_only=append_only,
        horizon_days=horizon_days,
        dest=dest,
        status="success",
        result=result,
    )
    return result


def _check_options(
    *,
    rebuild: bool,
    append_only: bool,
    horizon_days: int | None,
) -> None:
    # 追加模式从不改写既有分片，与整体替换互斥；混用会让"替换"的范围不明。
    if append_only and rebuild:
        raise LakeLayoutError("append_only 与 rebuild 互斥：追加模式不改写既有分片")
    if append_only and horizon_days is None:
        # 不截断就追加，会把 Wind 预填的远期行（到 2040 年）落盘，之后远期休市安排一改就失败。
        raise LakeLayoutError("append_only 必须同时给 horizon_days")
    if horizon_days is not None and horizon_days < 0:
        raise LakeLayoutError(f"horizon_days 不能为负: {horizon_days}")


def _truncate_horizon(table: pa.Table, *, as_of: date, horizon_days: int) -> pa.Table:
    cutoff = as_of + timedelta(days=horizon_days)
    kept = table.filter(pc.less_equal(table["cal_dt"], pa.scalar(cutoff, type=pa.date32())))
    if kept.num_rows == 0:
        raise LakeLayoutError(
            f"std.trade_calendar 截断后为空: as_of={as_of.isoformat()} horizon_days={horizon_days}"
        )
    return kept


def _write_std_parquet(table: pa.Table, dest: Path, *, rebuild: bool) -> _WriteOutcome:
    dest.mkdir(parents=True, exist_ok=True)
    final_path = dest / "part-00000.parquet"
    existing = [path for path in dest.glob("*.parquet") if path.is_file()]
    if existing and not rebuild:
        raise LakeLayoutError(f"拒绝覆盖既有分区: {dest}")
    tmp_path, file_digest = _stage_shard(table, final_path)
    # 必须先删旧分片再 rename：part-00000 同时是旧文件和新文件的路径，顺序反了会删掉新文件。
    if rebuild:
        for path in existing:
            path.unlink()
    tmp_path.replace(final_path)
    return _WriteOutcome(
        path=final_path,
        digest=file_digest,
        appended=table.num_rows,
        rebuilt=rebuild,
    )


def _append_std_parquet(table: pa.Table, dest: Path) -> _WriteOutcome:
    dest.mkdir(parents=True, exist_ok=True)
    shards = _list_shards(dest)
    if not shards:
        final_path = dest / "part-00000.parquet"
        tmp_path, file_digest = _stage_shard(table, final_path)
        tmp_path.replace(final_path)
        return _WriteOutcome(path=dest, digest=file_digest, appended=table.num_rows, rebuilt=False)

    existing = pa.concat_tables([pq.read_table(path) for path in shards])
    delta = _delta_rows(existing, table)
    if delta.num_rows == 0:
        # 没有新增日期：不写文件。输出 digest 由全部既有分片的文件摘要决定。
        shard_digests = [digest_file(path) for path in shards]
        return _WriteOutcome(
            path=dest,
            digest=digest_json(shard_digests),
            appended=0,
            rebuilt=False,
        )

    next_no = _shard_no(shards[-1]) + 1
    final_path = dest / f"part-{next_no:05d}.parquet"
    if final_path.exists():
        raise LakeLayoutError(f"拒绝覆盖既有分片: {final_path}")
    tmp_path, file_digest = _stage_shard(delta, final_path)
    tmp_path.replace(final_path)
    return _WriteOutcome(
        path=dest,
        digest=file_digest,
        appended=delta.num_rows,
        rebuilt=False,
    )


def _delta_rows(existing: pa.Table, new: pa.Table) -> pa.Table:
    """返回快照中尚未写入的行，同时对已写入的行做 fail-closed 校验。"""
    old_index = _index_by_key(existing, label="既有分片")
    new_index = _index_by_key(new, label="新快照")

    # 已写入的行不改：可见字段变化说明源端改写了历史结论，停下而不是覆盖。
    changed = sorted(
        key for key, value in new_index.items() if key in old_index and old_index[key] != value
    )
    if changed:
        raise LakeLayoutError(
            f"既有行的 is_open/prev_trade_dt 发生变化，拒绝改写已写入的行: "
            f"共 {len(changed)} 行，前 {_KEY_PREVIEW} 个: {_format_keys(changed)}"
        )

    # 只检查到新快照的上限。重跑较早的 as_of 时，较晚的既有行不属于本次快照范围，不算删除。
    upper = max(key[0] for key in new_index)
    removed = sorted(key for key in old_index if key[0] <= upper and key not in new_index)
    if removed:
        raise LakeLayoutError(
            f"既有日期在新快照中消失（源端删除了已写入的日期）: "
            f"共 {len(removed)} 行，前 {_KEY_PREVIEW} 个: {_format_keys(removed)}"
        )

    keys = list(zip(new["cal_dt"].to_pylist(), new["exchange"].to_pylist(), strict=True))
    mask = pa.array([key not in old_index for key in keys], type=pa.bool_())
    return new.filter(mask)


def _index_by_key(table: pa.Table, *, label: str) -> dict[_Key, _Value]:
    index: dict[_Key, _Value] = {}
    for row in table.to_pylist():
        key: _Key = (row["cal_dt"], row["exchange"])
        if key in index:
            raise LakeLayoutError(f"{label} 主键重复: {key[0].isoformat()}/{key[1]}")
        index[key] = (row["is_open"], row["prev_trade_dt"])
    return index


def _format_keys(keys: Sequence[_Key]) -> str:
    return ", ".join(f"{cal_dt.isoformat()}/{exchange}" for cal_dt, exchange in keys[:_KEY_PREVIEW])


def _list_shards(dest: Path) -> list[Path]:
    shards = sorted(path for path in dest.glob("*.parquet") if path.is_file())
    for path in shards:
        if _SHARD_RE.fullmatch(path.name) is None:
            raise LakeLayoutError(f"非分片命名的 parquet，拒绝追加: {path}")
    return shards


def _shard_no(path: Path) -> int:
    match = _SHARD_RE.fullmatch(path.name)
    if match is None:
        raise LakeLayoutError(f"非分片命名的 parquet: {path}")
    return int(match.group(1))


def _stage_shard(table: pa.Table, final_path: Path) -> tuple[Path, str]:
    """写到 ``.tmp`` 并回读行数。返回 (临时文件, digest)，由调用方决定何时 rename。"""
    tmp_path = final_path.with_name(f"{final_path.name}.tmp")
    tmp_path.unlink(missing_ok=True)
    pq.write_table(table, tmp_path, compression="zstd", write_statistics=True)
    readback = pq.read_table(tmp_path)
    if readback.num_rows != table.num_rows:
        tmp_path.unlink(missing_ok=True)
        raise LakeLayoutError(
            f"写后回读行数不一致: wrote={table.num_rows} read={readback.num_rows}"
        )
    return tmp_path, digest_file(tmp_path)


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
    append_only: bool,
    horizon_days: int | None,
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
                "append_only": append_only,
                "horizon_days": horizon_days,
                "dest": dest.as_posix(),
            }
        ),
        output_digest=None if result is None else result.output_digest,
        row_count=None if result is None else result.row_count,
        dml_count=0,
        error=error,
    )
    persist_run_log(record, paths)
