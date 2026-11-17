"""只读核对 Wind 源镜像：用库里的值重算 ``_row_hash``，与写入时记下的指纹比对。

``_row_hash`` 是写入前在客户端对源值算的。若传输中某列被改坏，库里的值重算出的指纹
就与记下的不同。用于事后核对经端口转发写入的历史数据，不写库。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql
from quantagent.ingest.sources.wind.tables import resolve_wind_paged_table
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.wind.verify"
_FETCH = 20_000
_SAMPLE = 20


@dataclass(frozen=True)
class WindVerifyResult:
    dataset: str
    row_count: int
    mismatched: int
    # 只差在整数与 Decimal 的表示：PG 列建成 integer、源端是 numeric(p,0)，值相等。
    type_only: int
    samples: tuple[str, ...]


def verify_wind_table(*, settings: Settings, paths: VarPaths, table: str) -> WindVerifyResult:
    started = datetime.now(UTC)
    spec = resolve_wind_paged_table(table).spec
    cols = ", ".join(quote_ident(c) for c in spec.native_columns)
    statement = assert_src_dml_sql(
        f"SELECT {cols}, {quote_ident('_row_hash')} "
        f"FROM {quote_ident(spec.pg_schema)}.{quote_ident(spec.pg_table)}"
    )
    rows = 0
    bad = 0
    type_only = 0
    samples: list[str] = []
    # 服务端游标分批取，内存只随批大小增长。
    with (
        connect(settings, "src") as conn,
        conn.transaction(),
        conn.cursor(name="wind_verify", row_factory=dict_row) as cur,
    ):
        cur.itersize = _FETCH
        cur.execute(statement)
        for row in cur:
            rows += 1
            if row_hash(row, spec.native_columns) != row["_row_hash"]:
                if row_hash(_ints_as_decimal(row), spec.native_columns) == row["_row_hash"]:
                    type_only += 1
                    continue
                bad += 1
                if len(samples) < _SAMPLE:
                    samples.append(str(tuple(row[k] for k in spec.keys)))
    result = WindVerifyResult(spec.dataset, rows, bad, type_only, tuple(samples))
    finished = datetime.now(UTC)
    persist_run_log(
        RunLog(
            action=ACTION,
            status="success" if bad == 0 else "failure",
            started_at=started,
            finished_at=finished,
            elapsed_ms=int((finished - started).total_seconds() * 1000),
            input_digest=digest_json({"dataset": spec.dataset}),
            output_digest=digest_json(
                {"rows": rows, "mismatched": bad, "type_only": type_only, "samples": samples}
            ),
            row_count=rows,
            dml_count=0,
            error=None if bad == 0 else f"{bad} 行重算指纹不一致，样例 {samples[:5]}",
        ),
        paths,
    )
    return result


def _ints_as_decimal(row: dict[str, object]) -> dict[str, object]:
    return {
        k: Decimal(v) if isinstance(v, int) and not isinstance(v, bool) else v
        for k, v in row.items()
    }
