"""QuantAgent：以研究证据为基础的量化投研系统。

分层与依赖方向见 ``docs/architecture/overview.md``，每层职责见
``docs/architecture/layers/``。依赖方向由 ``pyproject.toml`` 的 import-linter
契约做机械防护，但职责定义以文档和契约测试为准。

顶层包不导出任何符号，避免建立隐式的跨层捷径。
"""

__all__: list[str] = []
