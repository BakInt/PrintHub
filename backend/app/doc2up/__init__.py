"""文档两页合一（doc2up）模块门面：主程序只从这里 import router。

依赖方向 doc2up → core 允许（config/routers.deps/database）；core → doc2up
仅 main.py 一处注册（隔离钩子，见 doc/AGENTS.md 6.10）。
"""

from .router import router

__all__ = ["router"]
