"""证照生成件保留期清理线程：每小时清理到期生成件（隐私红线）。

清理规则见 `service.cleanup_expired_docs`：磁盘文件必删；跳过仍被未支付/待派发
订单引用的文件；被历史订单引用的 files 行置 expired 保留外键完整性。
"""

import logging
import threading
import time

from ..database import connect
from .service import cleanup_expired_docs

logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = 3600
_started = False
_lock = threading.Lock()


def _cleanup_loop() -> None:
    while True:
        time.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            db = connect()
            try:
                cleaned = cleanup_expired_docs(db)
                if cleaned:
                    logger.info("证照生成件清理完成：%s 条", cleaned)
            finally:
                db.close()
        except Exception:
            logger.exception("证照生成件清理线程异常")


def start_cleanup_scheduler() -> None:
    """启动清理守护线程（幂等，重复调用不叠加线程）。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    thread = threading.Thread(target=_cleanup_loop, name="cert-cleanup", daemon=True)
    thread.start()
    logger.info("证照生成件清理线程已启动（每 %s 秒执行一次）", _CLEANUP_INTERVAL_SECONDS)
