"""运行身份。

``run_id`` 只表达「这一次运行」，不编码业务含义。业务身份（feature_key、
matrix_id）走 digest，混在一起会让失败重跑对不上原 run。
"""

from __future__ import annotations

import uuid


def new_run_id() -> str:
    return uuid.uuid4().hex
