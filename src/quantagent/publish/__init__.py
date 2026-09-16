"""publish：发布产物装配。

负责：把任意上游层的结果装配为 ``publish/*.json``，并按
``contracts.schemas.publish`` 校验。读取 ``frozen/`` 下的冻结输入制品
（校验 digest 与行列合同后使用，不重算、不覆盖）。

允许依赖任意上游数据层——宏观指标可以从 ``std`` / ``mart`` 直达发布，
因子评价可以从 ``feature`` 直达发布，不需要绕路制造中间层。

硬约束：
- 每个发布产物必须携带 ``pit_report``（各输入的 ``grade``、``pit_from``、
  不可信区间样本占比），发布层强制展示，不得隐藏。
- 前端不直连数据库，也不反向写入任何数据层。

不负责：计算。装配脚本里不允许出现业务计算。

职责定义见 ``docs/architecture/layers/publish.md``。
"""

__all__: list[str] = []
