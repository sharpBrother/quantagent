"""quantagent/domain/pit

给定数据集可见性契约与 ``as_of``，算出哪些点事件可见。不读存储。
"""

from quantagent.domain.pit.solve import is_point_event_visible, visible_event_on_or_before

__all__ = ["is_point_event_visible", "visible_event_on_or_before"]
