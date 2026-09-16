"""``python -m quantagent.cli`` 与 ``quantagent`` 控制台脚本的入口。"""

from quantagent.cli.app import app

__all__ = ["app"]

if __name__ == "__main__":
    app()
