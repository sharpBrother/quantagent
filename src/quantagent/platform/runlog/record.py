"""运行记录的字段合同。

目的是三个月后能复现一次运行，不是向审计者举证。因此只记录输入/输出
digest、行数、耗时、DML 条数和成败原因，不做 digest 链或身份绑定。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from quantagent.platform.identity import new_run_id

RunStatus = Literal["started", "success", "failure"]


class RunLog(BaseModel):
    run_id: str = Field(default_factory=new_run_id)
    action: str
    status: RunStatus = "started"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    elapsed_ms: int | None = None
    input_digest: str | None = None
    output_digest: str | None = None
    row_count: int | None = None
    dml_count: int = 0
    error: str | None = None

    @model_validator(mode="after")
    def _finish_fields_match_status(self) -> Self:
        if self.status in {"success", "failure"} and self.finished_at is None:
            msg = "成功或失败的 run log 必须有 finished_at"
            raise ValueError(msg)
        if self.status == "failure" and not self.error:
            msg = "失败的 run log 必须有 error"
            raise ValueError(msg)
        return self
