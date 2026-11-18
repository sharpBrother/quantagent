"""允许写入的源表白名单。

目标表必须写死在代码常量里，不能从运行时参数或 YAML 临时指定——旧仓
``fut_holding`` 被两个脚本双写，就是因为写入目标可以漂移。
"""

from __future__ import annotations

from quantagent.adapters.postgres.src_targets import (
    AINDEXEODPRICES,
    AINDEXVALUATION,
    ASHAREBALANCESHEET,
    ASHARECALENDAR,
    ASHARECASHFLOW,
    ASHAREEODDERIVATIVEINDICATOR,
    ASHAREEODPRICES,
    ASHAREINCOME,
    ASHAREMONEYFLOW,
    FIRST_BATCH_WIND_SPECS,
    SHIBOR,
    TRADE_CAL,
    US_TREASURY_YIELD,
    SrcTableWriteSpec,
)
from quantagent.ingest.errors import TargetNotAllowedError

ALLOWED_SRC_WRITE_TARGETS: dict[str, SrcTableWriteSpec] = {
    TRADE_CAL.dataset: TRADE_CAL,
    SHIBOR.dataset: SHIBOR,
    US_TREASURY_YIELD.dataset: US_TREASURY_YIELD,
    ASHARECALENDAR.dataset: ASHARECALENDAR,
    ASHAREEODPRICES.dataset: ASHAREEODPRICES,
    AINDEXEODPRICES.dataset: AINDEXEODPRICES,
    ASHAREMONEYFLOW.dataset: ASHAREMONEYFLOW,
    ASHAREEODDERIVATIVEINDICATOR.dataset: ASHAREEODDERIVATIVEINDICATOR,
    ASHARECASHFLOW.dataset: ASHARECASHFLOW,
    ASHAREINCOME.dataset: ASHAREINCOME,
    ASHAREBALANCESHEET.dataset: ASHAREBALANCESHEET,
    AINDEXVALUATION.dataset: AINDEXVALUATION,
    **{spec.dataset: spec for spec in FIRST_BATCH_WIND_SPECS.values()},
}

# 旁表只允许写入器按批次协议 INSERT，不能当业务目标表；其余 tushare 表本
# 切片尚未开通写入。
FORBIDDEN_SRC_WRITE_TARGETS: frozenset[str] = frozenset(
    {
        "src_tushare._batch",
        "src_wind._batch",
        "src_jydb._batch",
        "src_suntime._batch",
        "src_macro._batch",
        "src.tushare.fund_share",
        "src.tushare.tushare_ths_industry_mapping_citics",
        "src_tushare.fund_share",
        "src_tushare.tushare_ths_industry_mapping_citics",
    }
)


# 每台机器只写自己负责的源 schema（负责人 2026-11-18 裁定）。两台机器跑同一份代码，
# 目标白名单分不出机器，所以按 QUANTAGENT_PROFILE 再限一层：公司电脑（office）连 Wind、
# 聚源、朝阳永续；Mac（local）跑公开源与 Tushare。各自有自己的 _batch，游标互不相干。
PROFILE_WRITABLE_SCHEMAS: dict[str, frozenset[str]] = {
    "office": frozenset({"src_wind", "src_jydb", "src_suntime"}),
    "local": frozenset({"src_tushare", "src_macro"}),
}


def assert_writable(spec: SrcTableWriteSpec, *, profile: str) -> None:
    if spec.dataset in FORBIDDEN_SRC_WRITE_TARGETS:
        raise TargetNotAllowedError(f"目标数据集显式禁写: {spec.dataset}")
    if spec.qualified_table in FORBIDDEN_SRC_WRITE_TARGETS:
        raise TargetNotAllowedError(f"目标表显式禁写: {spec.qualified_table}")
    allowed = ALLOWED_SRC_WRITE_TARGETS.get(spec.dataset)
    if allowed is None:
        raise TargetNotAllowedError(f"目标数据集不在写入白名单: {spec.dataset}")
    if allowed != spec:
        raise TargetNotAllowedError(
            f"写入规格与白名单不一致: {spec.dataset} -> {spec.qualified_table}"
        )
    schemas = PROFILE_WRITABLE_SCHEMAS.get(profile)
    if schemas is None or spec.pg_schema not in schemas:
        raise TargetNotAllowedError(
            f"本机 profile={profile} 不负责写 {spec.pg_schema}: {spec.dataset}"
        )


__all__ = [
    "AINDEXEODPRICES",
    "ALLOWED_SRC_WRITE_TARGETS",
    "ASHARECALENDAR",
    "ASHAREEODPRICES",
    "FORBIDDEN_SRC_WRITE_TARGETS",
    "PROFILE_WRITABLE_SCHEMAS",
    "TRADE_CAL",
    "SrcTableWriteSpec",
    "assert_writable",
]
