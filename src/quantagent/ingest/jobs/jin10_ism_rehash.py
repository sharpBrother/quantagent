"""金十 ISM 存量行 ``_row_hash`` 一次性订正。

背景：指纹 digest 此前对 datetime 按时区表示序列化、decimal 按源端任意标度序列化，
导致写入时与回读时对同一行算出不同 ``_row_hash``，复查永远无法命中 fast-path。
修复（datetime 统一 UTC、decimal 写入端量化到 numeric(18,8)）后，存量行的旧指纹
全部失效，需一次性刷新为当前算法值。

这是负责人 2026-11-27 批准的 UPDATE 例外，**仅限本表、仅限 ``_row_hash`` 元数据列、
一次性执行**。不改为任何业务列。它不走常规写入路径的 SQL 动词白名单——那是保护
日常 insert-only 链路的；本操作是运维订正，等价于 migrate 的手工性质，仍遵守：
显式范围、事务内写后回读、失败即停不重试、run log。

默认干跑：只计算需要订正的行数与前后 digest，不写库。
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from quantagent.adapters.postgres.src_targets import JIN10_ECONOMIC_CALENDAR
from quantagent.ingest.errors import IngestError
from quantagent.ingest.writers.src_follow import fingerprint_columns
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.platform.config.write_gate import assert_db_write_allowed
from quantagent.platform.errors import RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    import psycopg

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.macro.jin10_ism_rehash"
# 目标表白名单常量：本订正只允许这一张表，写死在代码里。
_TARGET_SCHEMA = "src_macro"
_TARGET_TABLE = "jin10_economic_calendar"

_NUMERIC_COLS = ("actual_value", "forecast_value", "previous_value", "revised_value")


@dataclass(frozen=True)
class Jin10RehashResult:
    written: bool
    total_rows: int
    need_update: int
    updated: int
    already_current: int
    dml_count: int
    output_digest: str


def _fetch_all(conn: psycopg.Connection) -> list[dict[str, object]]:
    cols = list(JIN10_ECONOMIC_CALENDAR.native_columns)
    sql = (
        f"SELECT {', '.join(chr(34) + c + chr(34) for c in cols)}, _row_hash "
        f"FROM {_TARGET_SCHEMA}.{_TARGET_TABLE} WHERE indicator_id = %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (129,))
        rows = cur.fetchall()
    result = []
    for r in rows:
        row = dict(zip(cols, r[: len(cols)], strict=True))
        row["_row_hash"] = r[len(cols)]
        result.append(row)
    return result


def _apply_update(
    conn: psycopg.Connection,
    plan: list[tuple[tuple[object, ...], str]],
) -> tuple[int, int]:
    """同事务内逐行 UPDATE ``_row_hash`` 并写后回读，不一致即回滚。返回 (updated, dml)。

    业务列一律不动，只刷新元数据指纹列。回读与写入同一事务，失败抛错由调用方回滚。
    """
    updated = 0
    with conn.cursor() as cur:
        for key, new_hash in plan:
            cur.execute(
                f"UPDATE {_TARGET_SCHEMA}.{_TARGET_TABLE} SET _row_hash = %s "
                "WHERE indicator_id = %s AND publish_date = %s AND data_id = %s",
                (new_hash, key[0], key[1], key[2]),
            )
            updated += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    # 写后回读：同事务重算每一行，必须全部与当前算法一致，否则回滚。
    mismatch = []
    for key, new_hash in plan:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT _row_hash FROM {_TARGET_SCHEMA}.{_TARGET_TABLE} "
                "WHERE indicator_id = %s AND publish_date = %s AND data_id = %s",
                (key[0], key[1], key[2]),
            )
            got = cur.fetchone()
        if got is None or got[0] != new_hash:
            mismatch.append(key)
    if mismatch:
        conn.rollback()
        raise IngestError(f"订正回读不一致 {len(mismatch)} 行，已回滚: {mismatch[:5]!r}")
    if updated != len(plan):
        conn.rollback()
        raise IngestError(f"订正行数不符：计划 {len(plan)} 实际 {updated}，已回滚")
    conn.commit()
    return updated, len(plan)


def rehash_jin10_ism(
    *,
    settings: Settings,
    paths: VarPaths,
    write_db: bool = False,
) -> Jin10RehashResult:
    """刷新存量行 ``_row_hash`` 为当前算法值。默认干跑。业务列不改动。"""
    started = datetime.now(UTC)
    conn = None
    try:
        conn = connect(settings, "src")
        fp = fingerprint_columns(JIN10_ECONOMIC_CALENDAR)
        rows = _fetch_all(conn)
        if not rows:
            raise IngestError("jin10_economic_calendar 无 ISM 行，无需订正")

        # 逐行重算当前算法的指纹，找出与库存 _row_hash 不一致的。
        plan: list[tuple[tuple[object, ...], str]] = []  # (key, new_hash)
        already = 0
        for row in rows:
            old_hash = row["_row_hash"]
            business = {c: row[c] for c in JIN10_ECONOMIC_CALENDAR.native_columns}
            new_hash = row_hash(business, fp)
            if new_hash != old_hash:
                key = tuple(row[c] for c in JIN10_ECONOMIC_CALENDAR.keys)
                plan.append((key, new_hash))
            else:
                already += 1

        updated = 0
        dml = 0
        if write_db:
            assert_db_write_allowed(settings=settings, write_db=True)
            if plan:
                updated, dml = _apply_update(conn, plan)

        out_digest = digest_json({"total": len(rows), "need_update": len(plan), "already": already})
        result = Jin10RehashResult(
            written=write_db,
            total_rows=len(rows),
            need_update=len(plan),
            updated=updated if write_db else 0,
            already_current=already,
            dml_count=dml,
            output_digest=out_digest,
        )
    except Exception as exc:
        if conn is not None and write_db:
            with suppress(Exception):
                conn.rollback()
        finished = datetime.now(UTC)
        with suppress(RunLogError):
            persist_run_log(
                RunLog(
                    action=ACTION,
                    status="failure",
                    started_at=started,
                    finished_at=finished,
                    elapsed_ms=int((finished - started).total_seconds() * 1000),
                    error=type(exc).__name__,
                ),
                paths,
            )
        raise
    finally:
        if conn is not None:
            conn.close()
    finished = datetime.now(UTC)
    persist_run_log(
        RunLog(
            action=ACTION,
            status="success",
            started_at=started,
            finished_at=finished,
            elapsed_ms=int((finished - started).total_seconds() * 1000),
            input_digest=digest_json({"table": _TARGET_TABLE, "write_db": write_db}),
            output_digest=result.output_digest,
            row_count=result.need_update,
            dml_count=result.dml_count,
        ),
        paths,
    )
    return result
