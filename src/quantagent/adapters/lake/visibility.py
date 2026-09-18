"""按数据集名加载可见性契约。缺规则 fail-closed。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import MissingVisibilityError

if TYPE_CHECKING:
    from quantagent.contracts.spec import VisibilityContract


def load_dataset_visibility(dataset: str) -> VisibilityContract:
    bundle = load_bundle()
    vis = bundle.visibilities.get(dataset)
    schema = bundle.schemas.get(dataset)
    if vis is None or schema is None:
        raise MissingVisibilityError(dataset)
    return vis
