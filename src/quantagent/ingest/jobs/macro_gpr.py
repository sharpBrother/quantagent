"""GPR 日频采集作业。CLI 与 Dagster 共用。
一次运行 = 一个文件 = 一个批次，单事务。
- 文件的 sha256 与最近一次写入库的 ``file_sha256`` 相同：报告“无更新”，不写库，也不登记批次。
- 否则只写相对库里已有内容真正变了的行（见 ``select_changed_points``）。库里每个
  ``(series_id, observation_date)`` 只保留值变化时的那个版本，历史全量不再每个文件重写一遍。
  同一 file_vintage 下已有的同键行交给写入器按跟随源端替换（file_sha256 是业务列）。
- 没有任何需要写入的行时不登记批次，报告“无更新”。
PIT 读法：每个 ``(series_id, observation_date)`` 取 ``file_vintage`` 严格早于 ``as_of`` 的最新一行。
值没变的版本不落库，所以读到的是最早得知这个值的那一行，取值与逐版本落库的结果一致。
公开源按自然日跑，不做交易日判断，也不按 as_of 切片：文件总是全量历史。
"""

from __future__ import annotations

from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.postgres.src_progress import (
    latest_version_values,
    latest_written_value,
    values_at_version,
)
from quantagent.adapters.postgres.src_targets import GPR_DAILY
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.sources.macro.gpr import (
    SOURCE_LABEL,
    GprDailyFile,
    GprPoint,
    fetch_gpr_daily_dta,
    parse_gpr_daily_dta,
)
from quantagent.ingest.writers.src_follow import write_src_follow
from quantagent.platform.errors import RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from decimal import Decimal

    import psycopg

    from quantagent.ingest.writers.src_follow import SrcFollowWriteResult
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.macro.gpr_daily"
_YMD = "%Y%m%d"
_KEY_COLUMNS: tuple[str, str] = ("series_id", "observation_date")


class MacroGprRunLog(RunLog):
    """GPR 的运行记录。在通用字段上加文件身份与写入计数，三个月后能看出这次换了多少行。
    不改 ``platform.runlog.RunLog``：那是跨源共用的模型，这里的计数只属于 GPR。
    """

    file_sha256: str | None = None
    file_vintage: str | None = None
    unchanged: bool = False
    written: bool = False
    inserted: int = 0
    replaced: int = 0
    skipped: int = 0
    metadata_skipped: int = 0
    unchanged_points: int = 0


@dataclass(frozen=True)
class GprStoredState:
    """库里 ``src_macro.gpr_daily`` 与本次文件相关的只读快照。

    ``latest``：每个 ``(series_id, observation_date)`` 的 ``(file_vintage, value)``，即 file_vintage 最大的那一行。
    ``at_vintage``：本次 file_vintage 下已有的同键行的 ``(value, file_sha256)``。
    """

    latest: Mapping[tuple[str, date], tuple[date, Decimal | None]]
    at_vintage: Mapping[tuple[str, date], tuple[Decimal | None, str]]


@dataclass(frozen=True)
class MacroGprIngestResult:
    """干跑与无更新时 ``written`` 为 False，写入计数为 0。
    ``row_count`` 是本次要写入（或已写入）的行数。``series_rows`` 是文件里每个序列的非缺失行数，
    无论是否写库都有，便于核对文件内容。``unchanged_points`` 是文件里不需要写入的行数（库里已有相同值）。
    """

    dataset: str
    written: bool
    unchanged: bool
    file_sha256: str
    file_vintage: date
    observation_min: date
    observation_max: date
    row_count: int
    series_rows: tuple[tuple[str, int], ...]
    inserted: int
    replaced: int
    skipped: int
    metadata_skipped: int
    unchanged_points: int
    dml_count: int
    batch_id: int | None
    payload_digest: str | None
    output_digest: str | None


def select_changed_points(
    points: Sequence[GprPoint],
    stored: GprStoredState,
    *,
    file_sha256: str,
) -> list[GprPoint]:
    """决定本次文件里哪些行需要交给写入器。纯函数，不读库。

    - 本次 file_vintage 下已有同键行：值与 file_sha256 都相同则不写；任一不同则交给写入器整键替换。
      file_sha256 是业务列，同一版本的文件内容变了，即使某个值没变，该行也要按跟随源端更新。
    - 库里没有这个 ``(series_id, observation_date)``：插入。
    - 库里最新版本的值与本次不等（``Decimal`` 按数值比较）：以本次 file_vintage 插入新版本。
    - 其余（库里最新版本值相等）：不写。这不是丢弃，库里那一行已经代表这个值。
    文件里没有的旧日期不做任何事，不删除也不改写。
    """
    changed: list[GprPoint] = []
    for point in points:
        key = (point.series_id, point.observation_date)
        same_vintage = stored.at_vintage.get(key)
        if same_vintage is not None:
            if same_vintage[0] != point.value or same_vintage[1] != file_sha256:
                changed.append(point)
            continue
        latest = stored.latest.get(key)
        if latest is None or latest[1] != point.value:
            changed.append(point)
    return changed


def ingest_macro_gpr(
    *,
    settings: Settings,
    paths: VarPaths,
    write_db: bool = False,
    fetch: Callable[[], bytes] | None = None,
    last_file_sha256: Callable[[], str | None] | None = None,
    stored_state: Callable[[date], GprStoredState] | None = None,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> MacroGprIngestResult:
    """``fetch``、``last_file_sha256``、``stored_state``、``store``、``now`` 是测试注入点，正式调用都不传。"""
    started = datetime.now(UTC)
    clock = now or (lambda: datetime.now(UTC))
    try:
        payload = (fetch or fetch_gpr_daily_dta)()
        parsed = parse_gpr_daily_dta(payload)
        previous = (last_file_sha256 or (lambda: _read_last_file_sha256(settings)))()
        if previous == parsed.file_sha256:
            result = _result(parsed, write=None)
        else:
            write = _write(
                settings=settings,
                parsed=parsed,
                write_db=write_db,
                store=store,
                clock=clock,
                stored_state=stored_state,
            )
            result = _result(parsed, write=write)
    except Exception as exc:
        # 失败也要落 run log。run log 本身写失败时，原异常照常抛出，不被掩盖。
        with suppress(RunLogError):
            _persist_run_log(
                paths=paths,
                started=started,
                write_db=write_db,
                parsed=None,
                result=None,
                error=str(exc),
            )
        raise
    _persist_run_log(
        paths=paths,
        started=started,
        write_db=write_db,
        parsed=parsed,
        result=result,
        error=None,
    )
    return result


def _read_last_file_sha256(settings: Settings) -> str | None:
    """库里最近一次写入的 file_sha256。只读。表为空时返回 None，即首次运行必定写入。"""
    conn = connect(settings, "src")
    try:
        return latest_written_value(
            conn,
            pg_schema=GPR_DAILY.pg_schema,
            table=GPR_DAILY.pg_table,
            column="file_sha256",
        )
    finally:
        conn.close()


def _read_stored_state(conn: psycopg.Connection[object], file_vintage: date) -> GprStoredState:
    latest = latest_version_values(
        conn,
        pg_schema=GPR_DAILY.pg_schema,
        table=GPR_DAILY.pg_table,
        key_columns=_KEY_COLUMNS,
        version_column="file_vintage",
        value_column="value",
    )
    at_vintage = values_at_version(
        conn,
        pg_schema=GPR_DAILY.pg_schema,
        table=GPR_DAILY.pg_table,
        key_columns=_KEY_COLUMNS,
        version_column="file_vintage",
        version=file_vintage,
        value_columns=("value", "file_sha256"),
    )
    return GprStoredState(
        latest={
            (str(key[0]), key[1]): (version, value) for key, (version, value) in latest.items()
        },
        at_vintage={
            (str(key[0]), key[1]): (value, str(sha)) for key, (value, sha) in at_vintage.items()
        },
    )


def _load_stored_state(
    *,
    settings: Settings,
    conn: psycopg.Connection[object] | None,
    file_vintage: date,
    injected: Callable[[date], GprStoredState] | None,
) -> GprStoredState:
    """写入时在同一连接上读，保证判断依据与写入处于同一事务。干跑没有写连接，单独开一个只读连接。"""
    if injected is not None:
        return injected(file_vintage)
    if conn is not None:
        return _read_stored_state(conn, file_vintage)
    fresh = connect(settings, "src")
    try:
        return _read_stored_state(fresh, file_vintage)
    finally:
        fresh.close()


def _write(
    *,
    settings: Settings,
    parsed: GprDailyFile,
    write_db: bool,
    store: SrcWriteStore | None,
    clock: Callable[[], datetime],
    stored_state: Callable[[date], GprStoredState] | None,
) -> SrcFollowWriteResult | None:
    """返回写入结果；没有任何需要写入的行时返回 None，不登记批次。"""
    stamp = clock()
    owned_conn = None
    try:
        if write_db and store is None:
            owned_conn = connect(settings, "src")
            store = PostgresSrcStore(owned_conn)
        state = _load_stored_state(
            settings=settings,
            conn=owned_conn,
            file_vintage=parsed.file_vintage,
            injected=stored_state,
        )
        changed = select_changed_points(parsed.points, state, file_sha256=parsed.file_sha256)
        if not changed:
            return None
        return write_src_follow(
            spec=GPR_DAILY,
            rows=_rows(changed, parsed),
            settings=settings,
            write_db=write_db,
            store=store,
            window_start=parsed.observation_min.strftime(_YMD),
            window_end=parsed.file_vintage.strftime(_YMD),
            now=lambda: stamp,
        )
    finally:
        if owned_conn is not None:
            owned_conn.close()


def _rows(points: Sequence[GprPoint], parsed: GprDailyFile) -> list[Mapping[str, object]]:
    # 不带 ingested_at：gpr_daily 没有原生采集时刻列，采集时刻由写入器统一写入 _ingested_at。
    return [
        {
            "series_id": point.series_id,
            "observation_date": point.observation_date,
            "file_vintage": parsed.file_vintage,
            "value": point.value,
            "file_sha256": parsed.file_sha256,
            "source": SOURCE_LABEL,
        }
        for point in points
    ]


def _result(parsed: GprDailyFile, *, write: SrcFollowWriteResult | None) -> MacroGprIngestResult:
    """``write`` 为 None 表示无更新（文件未变或没有需要写入的行），此时不写库，计数全部为 0。"""
    counts = Counter(point.series_id for point in parsed.points)
    series_rows = tuple((series_id, counts.get(series_id, 0)) for series_id in parsed.series_ids)
    observation_dates = [point.observation_date for point in parsed.points]
    written_rows = 0 if write is None else write.row_count
    unchanged_points = len(parsed.points) - written_rows
    if write is None:
        return MacroGprIngestResult(
            dataset=GPR_DAILY.dataset,
            written=False,
            unchanged=True,
            file_sha256=parsed.file_sha256,
            file_vintage=parsed.file_vintage,
            observation_min=min(observation_dates),
            observation_max=max(observation_dates),
            row_count=0,
            series_rows=series_rows,
            inserted=0,
            replaced=0,
            skipped=0,
            metadata_skipped=0,
            unchanged_points=unchanged_points,
            dml_count=0,
            batch_id=None,
            payload_digest=None,
            output_digest=None,
        )
    return MacroGprIngestResult(
        dataset=write.dataset,
        written=write.written,
        unchanged=False,
        file_sha256=parsed.file_sha256,
        file_vintage=parsed.file_vintage,
        observation_min=min(observation_dates),
        observation_max=max(observation_dates),
        row_count=write.row_count,
        series_rows=series_rows,
        inserted=write.inserted,
        replaced=write.replaced,
        skipped=write.skipped,
        metadata_skipped=write.metadata_skipped,
        unchanged_points=unchanged_points,
        dml_count=write.dml_count,
        batch_id=write.batch_id,
        payload_digest=write.payload_digest,
        output_digest=write.output_digest,
    )


def _persist_run_log(
    *,
    paths: VarPaths,
    started: datetime,
    write_db: bool,
    parsed: GprDailyFile | None,
    result: MacroGprIngestResult | None,
    error: str | None,
) -> None:
    finished = datetime.now(UTC)
    status: Literal["success", "failure"] = "failure" if error is not None else "success"
    record = MacroGprRunLog(
        action=ACTION,
        status=status,
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json(
            {
                "dataset": GPR_DAILY.dataset,
                "file_sha256": None if parsed is None else parsed.file_sha256,
                "write_db": write_db,
            }
        ),
        output_digest=None if result is None else result.output_digest,
        row_count=0 if result is None else result.row_count,
        dml_count=0 if result is None else result.dml_count,
        error=error,
        file_sha256=None if parsed is None else parsed.file_sha256,
        file_vintage=None if parsed is None else parsed.file_vintage.isoformat(),
        unchanged=False if result is None else result.unchanged,
        written=False if result is None else result.written,
        inserted=0 if result is None else result.inserted,
        replaced=0 if result is None else result.replaced,
        skipped=0 if result is None else result.skipped,
        metadata_skipped=0 if result is None else result.metadata_skipped,
        unchanged_points=0 if result is None else result.unchanged_points,
    )
    persist_run_log(record, paths)
