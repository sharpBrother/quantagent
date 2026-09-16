"""models：建模层，线性与机器学习共用同一组抽象。

负责：``Dataset``（panel + label + 时间切分）、宽矩阵物化与缓存、
``Splitter``（WalkForward / PurgedKFold，防泄漏）、``Estimator``（Protocol，
``fit`` / ``predict``，兼容 sklearn API）、``Pipeline``、``Evaluation``
（IC / RankIC / ICIR / 分组收益，口径统一）。

现有的 WLS 中性化与截面 OLS 只是 ``estimators.linear`` 下的实现；后续接
LightGBM、torch 只需新增 ``estimators.ml``，上下游不动。这是「不止步于
线性模型」的扩展点。

宽矩阵由 ``matrix_id`` 唯一确定，与全部输入因子的 ``definition_version``
和 ``param_hash`` 强绑定，因此参数一变缓存自然失效。``var/lake/_matrix/``
是纯缓存，可整体删除重建。

不负责：因子计算（``features``）、交易信号与回测（``strategy``）。

允许依赖：``platform``、``contracts``、``domain``。

见 ``docs/architecture/modeling-extensibility.md``。
"""

__all__: list[str] = []
