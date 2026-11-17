"""源表写入存储端口。适配器实现它；ingest 不直接拼连接。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from quantagent.adapters.postgres.src_targets import SrcTableWriteSpec


class SrcWriteStore(Protocol):
    def existing_keys(
        self,
        spec: SrcTableWriteSpec,
        keys: Sequence[tuple[object, ...]],
    ) -> set[tuple[object, ...]]: ...

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
    ) -> int: ...

    def existing_hashes(
        self,
        spec: SrcTableWriteSpec,
        keys: Sequence[tuple[object, ...]],
    ) -> dict[tuple[object, ...], str]: ...

    def latest_source_cursor(self, spec: SrcTableWriteSpec) -> str | None: ...

    def delete_keys(
        self,
        spec: SrcTableWriteSpec,
        keys: Sequence[tuple[object, ...]],
    ) -> None: ...

    def insert_rows(
        self,
        spec: SrcTableWriteSpec,
        rows: Sequence[Mapping[str, object]],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None: ...

    def readback_hashes(
        self,
        spec: SrcTableWriteSpec,
        batch_id: int,
        keys: Sequence[tuple[object, ...]],
    ) -> list[str]:
        """按本页写入的主键回读 ``_row_hash``，只返回 ``_batch_id`` 等于本批次的行。"""
        ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
