"""contracts：可执行契约。

负责：数据集 schema（pandera / pydantic）、发布产物 JSON schema、
可见性规则（PIT）YAML 的加载与校验、时间形态声明。

这一层取代旧仓 ``docs/data_dictionary/`` 的文档式数据字典——契约是代码，
能在 CI 中执行，不会与实现脱节。

不负责：读取数据、计算、任何 IO。契约只描述形状与语义，不实现搬运。

允许依赖：``platform``。

职责定义见 ``docs/architecture/layers/contracts.md``，契约变更流程见
``docs/contracts/README.md``。
"""

__all__: list[str] = []
