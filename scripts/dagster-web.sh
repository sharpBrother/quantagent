#!/bin/sh
set -eu

repo_root=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
cd "$repo_root"

python="$repo_root/.venv/bin/python"
webserver="$repo_root/.venv/bin/dagster-webserver"
if [ ! -x "$python" ] || [ ! -x "$webserver" ]; then
    echo "Dagster webserver is missing. Run: uv sync --all-extras --dev" >&2
    exit 1
fi

if [ -z "${DAGSTER_HOME:-}" ]; then
    # 使用项目配置解析 var_root，Mac 的运行存储可能在外接盘。
    DAGSTER_HOME=$("$python" -c 'from quantagent.platform.config import get_settings; from quantagent.platform.storage import detect_repo_root, resolve_var_paths; print(resolve_var_paths(get_settings(), repo_root=detect_repo_root()).root / "dagster")')
    export DAGSTER_HOME
fi

if [ ! -f "$DAGSTER_HOME/dagster.yaml" ] || [ ! -f "$DAGSTER_HOME/workspace.yaml" ]; then
    echo "Dagster configuration or workspace is missing in: $DAGSTER_HOME" >&2
    echo "Start the configured Dagster daemon first, or set DAGSTER_HOME." >&2
    exit 1
fi

echo "Dagster home: $DAGSTER_HOME"
echo "Dagster UI: http://127.0.0.1:3000/"
echo "Keep this terminal open while using the UI."
exec "$webserver" --host 127.0.0.1 --port 3000 --workspace "$DAGSTER_HOME/workspace.yaml"
