"""本地路径与对象布局。DuckDB 会话见 ``quantagent.platform.duck``。"""

from quantagent.platform.storage.paths import VarPaths, detect_repo_root, resolve_var_paths

__all__ = ["VarPaths", "detect_repo_root", "resolve_var_paths"]
