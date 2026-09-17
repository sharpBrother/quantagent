"""契约完整性检查。

缺可见性规则是全系统唯一的 PIT fail-closed 硬阻断：没有「什么时候能知道」
的定义，任何时间序列研究都不成立。本模块把这条规则变成可在 CI 跑的检查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from quantagent.contracts.loader import ContractBundle, load_bundle
from quantagent.contracts.spec import TRAINING_FEATURE_DATASETS
from quantagent.platform.storage.paths import detect_repo_root

if TYPE_CHECKING:
    from pathlib import Path

    from quantagent.contracts.spec import DatasetSchemaSpec, VisibilityContract


@dataclass(frozen=True)
class CheckIssue:
    dataset: str
    path: str
    message: str

    def render(self) -> str:
        return f"{self.dataset} ({self.path}): {self.message}"


@dataclass
class CheckReport:
    issues: list[CheckIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, dataset: str, path: Path | str, message: str) -> None:
        self.issues.append(CheckIssue(dataset=dataset, path=str(path), message=message))


def run_check(
    *,
    bundle: ContractBundle | None = None,
    repo_root: Path | None = None,
) -> CheckReport:
    loaded = bundle or load_bundle()
    root = repo_root or detect_repo_root()
    report = CheckReport()
    _check_pairing(loaded, report)
    for dataset, schema in loaded.schemas.items():
        visibility = loaded.visibilities.get(dataset)
        if visibility is None:
            continue
        _check_schema_visibility_alignment(
            schema,
            visibility,
            schema_path=loaded.schema_paths[dataset],
            report=report,
        )
        _check_doc_ref(
            dataset,
            schema.doc_ref,
            path=loaded.schema_paths[dataset],
            repo_root=root,
            report=report,
        )
        _check_doc_ref(
            dataset,
            visibility.doc_ref,
            path=loaded.visibility_paths[dataset],
            repo_root=root,
            report=report,
        )
        _check_reads(schema, loaded, report)
        _check_evaluation_only_reads(schema, loaded, report)
    for dataset, visibility in loaded.visibilities.items():
        if dataset in loaded.schemas:
            continue
        _check_doc_ref(
            dataset,
            visibility.doc_ref,
            path=loaded.visibility_paths[dataset],
            repo_root=root,
            report=report,
        )
    return report


def _check_pairing(bundle: ContractBundle, report: CheckReport) -> None:
    schema_ids = set(bundle.schemas)
    vis_ids = set(bundle.visibilities)
    for dataset in sorted(schema_ids - vis_ids):
        report.add(
            dataset,
            bundle.schema_paths[dataset],
            "缺少可见性规则；没有 visibility 的数据集不得参与 PIT 查询",
        )
    for dataset in sorted(vis_ids - schema_ids):
        report.add(
            dataset,
            bundle.visibility_paths[dataset],
            "可见性规则没有对应的 schema",
        )


def _check_schema_visibility_alignment(
    schema: DatasetSchemaSpec,
    visibility: VisibilityContract,
    *,
    schema_path: Path,
    report: CheckReport,
) -> None:
    if schema.temporal_kind != visibility.temporal_kind:
        report.add(
            schema.dataset,
            schema_path,
            "schema 与 visibility 的 temporal_kind 不一致",
        )
    if schema.event_field != visibility.event_field:
        report.add(
            schema.dataset,
            schema_path,
            "schema 与 visibility 的 event_field 不一致",
        )
    vis_field = visibility.visibility.field
    if vis_field is not None and vis_field not in schema.columns:
        report.add(
            schema.dataset,
            schema_path,
            f"visibility.field={vis_field} 不是 schema 中的列",
        )


def _check_reads(schema: DatasetSchemaSpec, bundle: ContractBundle, report: CheckReport) -> None:
    for upstream in schema.reads:
        if upstream not in bundle.schemas:
            report.add(
                schema.dataset,
                bundle.schema_paths[schema.dataset],
                f"reads 引用了尚未声明 schema 的数据集 {upstream}",
            )


def _check_evaluation_only_reads(
    schema: DatasetSchemaSpec,
    bundle: ContractBundle,
    report: CheckReport,
) -> None:
    if schema.dataset not in TRAINING_FEATURE_DATASETS:
        return
    for upstream in schema.reads:
        up = bundle.schemas.get(upstream)
        if up is not None and up.usage == "evaluation_only":
            report.add(
                schema.dataset,
                bundle.schema_paths[schema.dataset],
                f"不得读取 usage=evaluation_only 的数据集 {upstream}",
            )


def _check_doc_ref(
    dataset: str,
    doc_ref: str,
    *,
    path: Path,
    repo_root: Path,
    report: CheckReport,
) -> None:
    rel, _, anchor = doc_ref.partition("#")
    target = repo_root / rel
    if not target.is_file():
        report.add(dataset, path, f"doc_ref 指向不存在的文档 {rel}")
        return
    if not anchor:
        return
    if anchor not in _heading_anchors(target.read_text(encoding="utf-8")):
        report.add(dataset, path, f"doc_ref 锚点 #{anchor} 在 {rel} 中不存在")


def _heading_anchors(markdown: str) -> set[str]:
    """兼容「### point_event：说明」这类标题：锚点取全角/半角冒号前的标识。"""
    anchors: set[str] = set()
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip().strip("`")
        if not title:
            continue
        anchors.add(title)
        for sep in ("：", ":"):
            if sep in title:
                anchors.add(title.split(sep, 1)[0].strip())
                break
        token = title.split()[0]
        anchors.add(token)
    return anchors
