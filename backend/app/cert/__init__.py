"""证照打印模块门面：主程序只允许从这里 import。

导出：router（用户侧）/ admin_router（管理侧）/ ensure_schema（database.py 钩子）/
start_cleanup_scheduler（main.py 启动钩子）。依赖方向见 doc/CERT_PRINT_PLAN.md 第 1.4 节。
"""

from .admin_router import router as admin_router
from .cleanup import start_cleanup_scheduler
from .router import router
from .schema import ensure_schema

__all__ = ["router", "admin_router", "ensure_schema", "start_cleanup_scheduler"]
