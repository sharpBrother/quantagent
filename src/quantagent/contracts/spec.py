"""契约 YAML 的 pydantic 模型。

规则求解（给定 as_of 算出可见行）不在这里，那是 ``domain.pit``。本模块只
保证「形状合法、必填项在、fallback 不能抬高等级」。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

TemporalKind = Literal["point_event", "period_with_revision", "interval", "snapshot"]
PitGrade = Literal["A", "B", "C", "D"]
VisibilityRuleName = Literal[
    "same_day_close",
    "source_field",
    "release_calendar",
    "statutory_deadline",
    "fixed_lag",
    "ingest_time",
]
SchemaLayer = Literal["pg", "ops", "lake"]
ColumnDtype = Literal["date", "datetime", "string", "bool", "int64", "float64"]

_DATASET_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]+)+$")
_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


class VisibilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: VisibilityRuleName
    grade: PitGrade
    rationale: str = Field(min_length=8)
    field: str | None = None
    calendar: str | None = None
    lag_n: int | None = Field(default=None, ge=0)
    lag_unit: Literal["trading_day", "calendar_day"] | None = None
    fallback: VisibilitySpec | None = None

    @model_validator(mode="after")
    def _rule_payload_and_fallback_grade(self) -> Self:
        if self.rule == "source_field" and not self.field:
            raise ValueError("source_field 必须指定 field")
        if self.rule == "release_calendar" and not self.calendar:
            raise ValueError("release_calendar 必须指定 calendar")
        if self.rule == "fixed_lag" and (self.lag_n is None or self.lag_unit is None):
            raise ValueError("fixed_lag 必须指定 lag_n 与 lag_unit")
        if self.fallback is not None and _GRADE_RANK[self.fallback.grade] < _GRADE_RANK[self.grade]:
            # 推断可见日不可能比原生字段更可信；允许同级或更差。
            raise ValueError("fallback 的 grade 不得高于主规则")
        return self


class VisibilityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    doc_ref: str
    temporal_kind: TemporalKind
    visibility: VisibilitySpec
    pit_recoverable: bool
    event_field: str | None = None
    period_fields: list[str] | None = None
    pit_from: date | None = None
    origin: str | None = None
    recomputable: bool | None = None

    @model_validator(mode="after")
    def _dataset_and_pit_fields(self) -> Self:
        if not _DATASET_RE.match(self.dataset):
            raise ValueError(f"dataset 名非法: {self.dataset}")
        if self.temporal_kind == "point_event" and not self.event_field:
            raise ValueError("point_event 必须声明 event_field")
        if self.temporal_kind == "period_with_revision" and not self.period_fields:
            raise ValueError("period_with_revision 必须声明 period_fields")
        if not self.pit_recoverable and self.pit_from is None:
            raise ValueError("pit_recoverable 为 false 时必须提供 pit_from")
        if self.pit_from is not None and not isinstance(self.pit_from, date):
            raise ValueError("pit_from 必须是 date")
        return self


class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dtype: ColumnDtype
    nullable: bool = False
    description: str = ""


class DatasetSchemaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    layer: SchemaLayer
    doc_ref: str
    temporal_kind: TemporalKind
    keys: list[str] = Field(min_length=1)
    columns: dict[str, ColumnSpec] = Field(min_length=1)
    reads: list[str] = Field(default_factory=list)
    event_field: str | None = None
    period_fields: list[str] | None = None

    @model_validator(mode="after")
    def _keys_exist_and_published_at_nullable(self) -> Self:
        if not _DATASET_RE.match(self.dataset):
            raise ValueError(f"dataset 名非法: {self.dataset}")
        missing = [name for name in self.keys if name not in self.columns]
        if missing:
            raise ValueError(f"keys 引用了不存在的列: {missing}")
        if self.event_field is not None and self.event_field not in self.columns:
            raise ValueError(f"event_field {self.event_field} 不是已声明列")
        if self.period_fields:
            absent = [name for name in self.period_fields if name not in self.columns]
            if absent:
                raise ValueError(f"period_fields 引用了不存在的列: {absent}")
        published = self.columns.get("published_at")
        if published is not None and not published.nullable:
            # NULL 表示「源端没有发布时间」；非空会逼人填推测值。
            raise ValueError("published_at 必须可空，且不得给默认值")
        ingested = self.columns.get("_ingested_at") or self.columns.get("ingested_at")
        if ingested is not None and ingested.dtype not in {"datetime", "date"}:
            raise ValueError("_ingested_at / ingested_at 必须是时间类型")
        return self
