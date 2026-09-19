"""允许写入的源表白名单。

目标表必须写死在代码常量里，不能从运行时参数或 YAML 临时指定——旧仓
``fut_holding`` 被两个脚本双写，就是因为写入目标可以漂移。
"""

from __future__ import annotations

from quantagent.adapters.postgres.src_targets import (
    ASHAREEODPRICES,
    TRADE_CAL,
    SrcTableWriteSpec,
)
from quantagent.ingest.errors import TargetNotAllowedError

ALLOWED_SRC_WRITE_TARGETS: dict[str, SrcTableWriteSpec] = {
    TRADE_CAL.dataset: TRADE_CAL,
    ASHAREEODPRICES.dataset: ASHAREEODPRICES,
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


def assert_writable(spec: SrcTableWriteSpec) -> None:
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


__all__ = [
    "ALLOWED_SRC_WRITE_TARGETS",
    "ASHAREEODPRICES",
    "FORBIDDEN_SRC_WRITE_TARGETS",
    "TRADE_CAL",
    "SrcTableWriteSpec",
    "assert_writable",
]
