"""FRED／ALFRED 带版本观测采集作业。CLI 与 Dagster 共用。

每个序列一个批次、一个事务：分片拉取全部历史版本（见 ``sources/macro/fred.py``），校验不变量后，
跟随源端写入 ``src_macro.fred_observation_vintage``。
重跑幂等。版本没变的行指纹相同即跳过；源端修订的行（主要是某版本的 ``realtime_end`` 从
9999-12-31 改成具体日期，这是同键值变）按主键替换，计入 ``replaced``。
每个序列都全量拉取，日更不设起点，也不读批次水位。
只在 Mac（``QUANTAGENT_PROFILE=local``）上跑。``src_macro`` 只有 local 档位可写。
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from quantagent.adapters.postgres.src_targets import FRED_OBSERVATION_VINTAGE
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.errors import IngestError
from quantagent.ingest.sources.macro.fred import (
    FRED_SERIES,
    REALTIME_END,
    REALTIME_START,
    FredHttp,
    RequestsFredHttp,
    fetch_observation_vintages,
)
from quantagent.ingest.writers.src_follow import SrcFollowWriteResult, write_src_follow
from quantagent.platform.errors import ConfigError, RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.macro.fred"


@dataclass(frozen=True)
class MacroFredSeriesResult:
    series_id: str
    pages: int
    write: SrcFollowWriteResult


@dataclass(frozen=True)
class MacroFredIngestResult:
    """干跑时 ``written`` 为 False，各计数为 0，只有 ``row_count`` 与 digest 有意义。"""

    dataset: str
    written: bool
    series: tuple[MacroFredSeriesResult, ...]

    @property
    def row_count(self) -> int:
        return sum(item.write.row_count for item in self.series)

    @property
    def inserted(self) -> int:
        return sum(item.write.inserted for item in self.series)

    @property
    def replaced(self) -> int:
        return sum(item.write.replaced for item in self.series)

    @property
    def skipped(self) -> int:
        return sum(item.write.skipped for item in self.series)

    @property
    def metadata_skipped(self) -> int:
        return sum(item.write.metadata_skipped for item in self.series)

    @property
    def dml_count(self) -> int:
        return sum(item.write.dml_count for item in self.series)


def ingest_macro_fred(
    *,
    settings: Settings,
    paths: VarPaths,
    write_db: bool = False,
    series_ids: Sequence[str] | None = None,
    http: FredHttp | None = None,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
) -> MacroFredIngestResult:
    ids = _resolve_series(series_ids)
    api_key = settings.fred_api_key.get_secret_value().strip()
    if not api_key:
        raise ConfigError("QUANTAGENT_FRED_API_KEY 未配置")
    resolved_http = http or RequestsFredHttp()
    clock = now or (lambda: datetime.now(UTC))
    owned_conn = None
    try:
        if write_db and store is None:
            owned_conn = connect(settings, "src")
            store = PostgresSrcStore(owned_conn)
        outcomes = [
            _ingest_series(
                settings=settings,
                paths=paths,
                api_key=api_key,
                http=resolved_http,
                store=store,
                write_db=write_db,
                series_id=series_id,
                clock=clock,
            )
            for series_id in ids
        ]
    finally:
        if owned_conn is not None:
            owned_conn.close()
    return MacroFredIngestResult(
        dataset=FRED_OBSERVATION_VINTAGE.dataset,
        written=write_db,
        series=tuple(outcomes),
    )


def _resolve_series(series_ids: Sequence[str] | None) -> tuple[str, ...]:
    if series_ids is None:
        return FRED_SERIES
    ids = tuple(series_ids)
    unknown = [item for item in ids if item not in FRED_SERIES]
    if unknown:
        raise IngestError(f"FRED 序列只允许 {'、'.join(FRED_SERIES)}，收到 {unknown}")
    if len(set(ids)) != len(ids):
        raise IngestError(f"FRED 序列重复: {list(ids)}")
    return ids


def _ingest_series(
    *,
    settings: Settings,
    paths: VarPaths,
    api_key: str,
    http: FredHttp,
    store: SrcWriteStore | None,
    write_db: bool,
    series_id: str,
    clock: Callable[[], datetime],
) -> MacroFredSeriesResult:
    started = datetime.now(UTC)
    try:
        fetched = fetch_observation_vintages(series_id, api_key=api_key, http=http)
        # 同一序列的所有行共用一个采集时刻，经写入器落到 _ingested_at。表没有原生 ingested_at 列。
        stamp = clock()
        write = write_src_follow(
            spec=FRED_OBSERVATION_VINTAGE,
            rows=fetched.rows,
            settings=settings,
            write_db=write_db,
            store=store,
            window_start=REALTIME_START,
            window_end=REALTIME_END,
            now=lambda: stamp,
        )
    except Exception as exc:
        # 失败的序列也要落 run log。已提交的序列各自有 run log，不受影响。
        with suppress(RunLogError):
            _persist_run_log(
                paths=paths,
                started=started,
                series_id=series_id,
                write_db=write_db,
                result=None,
                error=str(exc),
            )
        raise
    _persist_run_log(
        paths=paths,
        started=started,
        series_id=series_id,
        write_db=write_db,
        result=write,
        error=None,
    )
    return MacroFredSeriesResult(series_id=series_id, pages=fetched.pages, write=write)


def _persist_run_log(
    *,
    paths: VarPaths,
    started: datetime,
    series_id: str,
    write_db: bool,
    result: SrcFollowWriteResult | None,
    error: str | None,
) -> None:
    # 输入摘要不含 api_key，run log 不记录任何凭据。
    finished = datetime.now(UTC)
    status: Literal["success", "failure"] = "failure" if error is not None else "success"
    record = RunLog(
        action=ACTION,
        status=status,
        started_at=started,
        finished_at=finished,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        input_digest=digest_json(
            {
                "dataset": FRED_OBSERVATION_VINTAGE.dataset,
                "series_id": series_id,
                "realtime_start": REALTIME_START,
                "realtime_end": REALTIME_END,
                "write_db": write_db,
            }
        ),
        output_digest=None if result is None else result.output_digest,
        row_count=0 if result is None else result.row_count,
        dml_count=0 if result is None else result.dml_count,
        error=error,
    )
    persist_run_log(record, paths)
