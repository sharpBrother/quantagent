"""写库总闸。

两道开关必须同时打开：环境变量 ``QUANTAGENT_ALLOW_DB_WRITE=true``，以及
命令行 ``--write-db``。只开一道就放行，等于另一道形同虚设；旧仓的教训是
默认可写、事后靠人记得不要跑。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quantagent.platform.errors import WriteGateError

if TYPE_CHECKING:
    from quantagent.platform.config.settings import Settings


def assert_db_write_allowed(*, settings: Settings, write_db: bool) -> None:
    """未同时满足两道开关时抛 ``WriteGateError``，不得返回降级结果。"""
    if not write_db:
        raise WriteGateError("拒绝写库：未传 --write-db")
    if not settings.allow_db_write:
        raise WriteGateError("拒绝写库：QUANTAGENT_ALLOW_DB_WRITE 不为 true")
