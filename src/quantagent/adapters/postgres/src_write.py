"""PostgreSQL 源表 insert-only 写入原语。只有 ingest 调用本模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row

from quantagent.adapters.postgres.errors import (
    SrcConflictError,
    TransactionUnknownError,
)
from quantagent.adapters.postgres.sql_types import quote_ident
from quantagent.adapters.postgres.src_dml import assert_src_dml_sql, assert_src_replace_sql

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from quantagent.adapters.postgres.src_targets import SrcTableWriteSpec

_KEY_CHUNK = 500


class PostgresSrcStore:
    """同一连接上的批次 INSERT + 数据 INSERT + 回读。默认不自动提交。"""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def existing_keys(
        self,
        spec: SrcTableWriteSpec,
        keys: Sequence[tuple[object, ...]],
    ) -> set[tuple[object, ...]]:
        found: set[tuple[object, ...]] = set()
        if not keys:
            return found
        key_sql = ", ".join(quote_ident(name) for name in spec.keys)
        table_sql = _table_sql(spec)
        width = len(spec.keys)
        row_placeholder = "(" + ", ".join(["%s"] * width) + ")"
        for offset in range(0, len(keys), _KEY_CHUNK):
            chunk = keys[offset : offset + _KEY_CHUNK]
            values_sql = ", ".join([row_placeholder] * len(chunk))
            statement = (
                f"SELECT {key_sql} FROM {table_sql} WHERE ({key_sql}) IN (VALUES {values_sql})"
            )
            assert_src_dml_sql(statement)
            params = [item for key in chunk for item in key]
            with self._conn.cursor() as cur:
                cur.execute(statement, params)
                for row in cur.fetchall():
                    found.add(tuple(row))
        return found

    def insert_batch(
        self,
        *,
        spec: SrcTableWriteSpec,
        window_start: str | None,
        window_end: str | None,
        row_count: int,
        payload_digest: str,
        started_at: datetime,
        finished_at: datetime,
        source_cursor: str | None = None,
    ) -> int:
        table_sql = f"{quote_ident(spec.pg_schema)}.{quote_ident('_batch')}"
        statement = (
            f"INSERT INTO {table_sql} ("
            "dataset, window_start, window_end, source_cursor, row_count, "
            "payload_digest, status, detail, started_at, finished_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {quote_ident('_batch_id')}"
        )
        assert_src_dml_sql(statement)
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    statement,
                    (
                        spec.dataset,
                        window_start,
                        window_end,
                        source_cursor,
                        row_count,
                        payload_digest,
                        "success",
                        None,
                        started_at,
                        finished_at,
                    ),
                )
            except psycopg.errors.IntegrityError as exc:
                raise SrcConflictError(f"{spec.dataset} 批次插入冲突") from exc
            fetched = cur.fetchone()
            if fetched is None:
                raise SrcConflictError(f"{spec.dataset} 批次 INSERT 未返回 _batch_id")
            return int(fetched[0])

    def existing_hashes(
        self,
        spec: SrcTableWriteSpec,
        keys: Sequence[tuple[object, ...]],
    ) -> dict[tuple[object, ...], str]:
        found: dict[tuple[object, ...], str] = {}
        if not keys:
            return found
        key_sql = ", ".join(quote_ident(name) for name in spec.keys)
        table_sql = _table_sql(spec)
        width = len(spec.keys)
        row_placeholder = "(" + ", ".join(["%s"] * width) + ")"
        for offset in range(0, len(keys), _KEY_CHUNK):
            chunk = keys[offset : offset + _KEY_CHUNK]
            values_sql = ", ".join([row_placeholder] * len(chunk))
            statement = (
                f"SELECT {key_sql}, {quote_ident('_row_hash')} FROM {table_sql} "
                f"WHERE ({key_sql}) IN (VALUES {values_sql})"
            )
            assert_src_dml_sql(statement)
            params = [item for key in chunk for item in key]
            with self._conn.cursor() as cur:
                cur.execute(statement, params)
                for row in cur.fetchall():
                    found[tuple(row[:-1])] = str(row[-1])
        return found

    def latest_source_cursor(self, spec: SrcTableWriteSpec) -> str | None:
        table_sql = f"{quote_ident(spec.pg_schema)}.{quote_ident('_batch')}"
        statement = (
            f"SELECT source_cursor FROM {table_sql} "
            "WHERE dataset = %s AND status = %s AND source_cursor IS NOT NULL "
            f"ORDER BY {quote_ident('_batch_id')} DESC LIMIT 1"
        )
        assert_src_dml_sql(statement)
        with self._conn.cursor() as cur:
            cur.execute(statement, (spec.dataset, "success"))
            fetched = cur.fetchone()
        if fetched is None or fetched[0] is None:
            return None
        return str(fetched[0])

    def delete_keys(
        self,
        spec: SrcTableWriteSpec,
        keys: Sequence[tuple[object, ...]],
    ) -> None:
        if not keys:
            return
        key_sql = ", ".join(quote_ident(name) for name in spec.keys)
        table_sql = _table_sql(spec)
        width = len(spec.keys)
        row_placeholder = "(" + ", ".join(["%s"] * width) + ")"
        for offset in range(0, len(keys), _KEY_CHUNK):
            chunk = keys[offset : offset + _KEY_CHUNK]
            values_sql = ", ".join([row_placeholder] * len(chunk))
            statement = f"DELETE FROM {table_sql} WHERE ({key_sql}) IN (VALUES {values_sql})"
            assert_src_replace_sql(statement)
            params = [item for key in chunk for item in key]
            with self._conn.cursor() as cur:
                cur.execute(statement, params)

    def insert_rows(
        self,
        spec: SrcTableWriteSpec,
        rows: Sequence[Mapping[str, object]],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None:
        if len(rows) != len(hashes):
            raise SrcConflictError(f"{spec.dataset} 行与 hash 数量不一致")
        columns = (*spec.native_columns, "_batch_id", "_ingested_at", "_row_hash")
        col_sql = ", ".join(quote_ident(name) for name in columns)
        placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
        statement = f"INSERT INTO {_table_sql(spec)} ({col_sql}) VALUES {placeholders}"
        assert_src_dml_sql(statement)
        payload = [
            tuple([row[name] for name in spec.native_columns] + [batch_id, ingested_at, digest])
            for row, digest in zip(rows, hashes, strict=True)
        ]
        with self._conn.cursor() as cur:
            try:
                cur.executemany(statement, payload)
            except psycopg.errors.IntegrityError as exc:
                raise SrcConflictError(f"{spec.dataset} 数据插入冲突") from exc

    def readback_hashes(self, spec: SrcTableWriteSpec, batch_id: int) -> list[str]:
        statement = (
            f"SELECT {quote_ident('_row_hash')} FROM {_table_sql(spec)} "
            f"WHERE {quote_ident('_batch_id')} = %s"
        )
        assert_src_dml_sql(statement)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(statement, (batch_id,))
            return [str(row["_row_hash"]) for row in cur.fetchall()]

    def commit(self) -> None:
        try:
            self._conn.commit()
        except psycopg.Error as exc:
            raise TransactionUnknownError("提交结果未知，已停止且不会重试") from exc

    def rollback(self) -> None:
        try:
            self._conn.rollback()
        except psycopg.Error as exc:
            raise TransactionUnknownError("回滚结果未知，已停止且不会重试") from exc


def _table_sql(spec: SrcTableWriteSpec) -> str:
    return f"{quote_ident(spec.pg_schema)}.{quote_ident(spec.pg_table)}"
