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
    ) -> int: ...

    def insert_rows(
        self,
        spec: SrcTableWriteSpec,
        rows: Sequence[Mapping[str, object]],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None: ...

    def readback_hashes(self, spec: SrcTableWriteSpec, batch_id: int) -> list[str]: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
