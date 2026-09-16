"""features：因子与特征面板。

负责：声明式因子定义（``FeatureSpec``）、因子实现库、因子值长表的计算与
写入、因子定义与参数的旁置注册表。

因子长表是因子的唯一交换与保存格式。身份分三段：``feature_id``（语义
身份）、``definition_version``（计算逻辑版本）、``param_hash``（参数配置
指纹）。配置全文存 ``var/lake/feature/_registry/``，长表只存两个短字段。

硬约束：
- ``knowledge_dt`` 与 ``pit_grade`` **由血缘自动推导，不接受人工填写**。
  ``knowledge_dt`` 默认取所有输入的最大值加计算延迟，只允许更严格；
  ``pit_grade`` 沿依赖图取最差值继承，不可手工抬升。
- 读取上游必须传 ``as_of``，不存在无 ``as_of`` 的读取路径。

不负责：宽矩阵物化（属于 ``models.matrix``）、模型训练、信号生成。

允许依赖：``platform``、``contracts``、``domain``。

见 ``docs/architecture/feature-storage.md``。
"""

__all__: list[str] = []
