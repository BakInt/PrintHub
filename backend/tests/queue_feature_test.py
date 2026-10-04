"""排队系统与打印状态修复的定向验证脚本。

该脚本只验证本次新增的排队计算、排队接口、后台看板接口、状态刷新接口，
以及监控线程的关键修复点（`_check_cups_health` 已定义、`check_printing_orders`
可正常执行而不抛 NameError）。不依赖真实 CUPS / pycups，可在 Windows 直接运行。

运行：
    python tests/queue_feature_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmpdir = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(_tmpdir.name) / "cloud_print.db")
os.environ["UPLOAD_DIR"] = str(Path(_tmpdir.name) / "uploads")
os.environ["EPAY_PID"] = "1001"
os.environ["EPAY_KEY"] = "queue-epay-key"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ["FRONTEND_BASE_URL"] = "http://frontend.test"

from fastapi.testclient import TestClient

from app.main import app
from app.database import connect, init_db
from app.services import queue as queue_service
from app.services import print_monitor
from app.services import printer as printer_service

# init_db 平时在 FastAPI 启动事件中执行；直接跑 DB 断言前需先建表。
init_db()


def _seed_order(order_id: str, status: str, order_type: str = "print", **overrides) -> None:
    """直接写入一条订单，用于构造排队场景，避免依赖上传/支付链路。"""
    fields = {
        "id": order_id,
        "order_type": order_type,
        "status": status,
        "total_amount": 1.0,
        "base_amount": 1.0,
        "discount_amount": 0.0,
        "sheet_count": 1,
        "copies": 1,
        "is_double_sided": 0,
        "payment_method": "balance",
        "contact_name": f"顾客-{order_id}",
        "printer_name": "测试打印机",
        "print_job_id": None,
        "printed_at": None,
        "paid_at": None,
        "created_at": overrides.get("created_at", "2026-08-03T10:00:00"),
    }
    fields.update(overrides)
    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    with connect() as db:
        db.execute(f"INSERT INTO orders ({columns}) VALUES ({placeholders})", tuple(fields.values()))
        db.commit()


def test_queue_service_direct() -> None:
    """直接测试排队服务的计算逻辑（不经过 HTTP）。"""
    # 三个进入队列的打印单：先派发的排前面。
    _seed_order("Q-PRINTING", "printing", printed_at="2026-08-03T10:00:00", created_at="2026-08-03T09:00:00")
    _seed_order("Q-PAID-1", "paid", paid_at="2026-08-03T10:05:00", created_at="2026-08-03T09:05:00")
    _seed_order("Q-PAID-2", "paid", paid_at="2026-08-03T10:10:00", created_at="2026-08-03T09:10:00")
    # 干扰项：不应计入队列。
    _seed_order("Q-COMPLETED", "completed", created_at="2026-08-03T08:00:00")
    _seed_order("Q-PENDING", "pending", created_at="2026-08-03T08:30:00")
    _seed_order("Q-RECHARGE", "paid", order_type="recharge", created_at="2026-08-03T08:40:00")
    _seed_order("Q-TEST", "printing", order_type="test", created_at="2026-08-03T08:50:00")

    with connect() as db:
        pos_printing = queue_service.queue_position(db, "Q-PRINTING")
        pos_paid1 = queue_service.queue_position(db, "Q-PAID-1")
        pos_paid2 = queue_service.queue_position(db, "Q-PAID-2")
        overview = queue_service.queue_overview(db)
        pos_missing = queue_service.queue_position(db, "不存在的订单")
        pos_completed = queue_service.queue_position(db, "Q-COMPLETED")

    assert pos_printing == {"in_queue": True, "ahead": 0, "position": 1, "total": 3, "printing": 1}, pos_printing
    assert pos_paid1["position"] == 2 and pos_paid1["ahead"] == 1, pos_paid1
    assert pos_paid2["position"] == 3 and pos_paid2["ahead"] == 2, pos_paid2
    assert overview["total"] == 3, overview
    assert overview["printing_count"] == 1, overview
    assert overview["waiting_count"] == 2, overview
    assert [item["id"] for item in overview["items"]] == ["Q-PRINTING", "Q-PAID-1", "Q-PAID-2"], overview
    assert pos_missing["in_queue"] is False and pos_missing["position"] == 0, pos_missing
    assert pos_completed["in_queue"] is False, pos_completed
    print("[OK] 排队服务计算：位置、前面人数、干扰订单排除均正确")


def test_monitor_no_nameerror() -> None:
    """验证监控线程关键修复：check_printing_orders 可执行且不抛 NameError。

    这正是“前台不刷新则后台状态不更新”的根因修复点。
    """
    # 打桩 print_jobs_active，模拟打印任务已完成（active=False -> 应置为 completed）。
    original = printer_service.print_jobs_active
    printer_service.print_jobs_active = lambda *a, **k: False
    # print_monitor 里以 from .printer import print_jobs_active 方式引用，需同步打桩。
    original_monitor = print_monitor.print_jobs_active
    print_monitor.print_jobs_active = lambda *a, **k: False
    try:
        _seed_order(
            "MON-1",
            "printing",
            print_job_id="cups-mon-job-1",
            printed_at="2026-08-03T10:00:00",
            created_at="2026-08-03T09:00:00",
        )
        changed = print_monitor.check_printing_orders()
        assert changed >= 1, f"应至少更新 1 个订单，实际 {changed}"
        with connect() as db:
            row = db.execute("SELECT status FROM orders WHERE id = 'MON-1'").fetchone()
        assert row["status"] == "completed", row["status"]
        print("[OK] 监控线程 check_printing_orders 正常执行，printing -> completed（NameError 已修复）")
    finally:
        printer_service.print_jobs_active = original
        print_monitor.print_jobs_active = original_monitor


def test_http_endpoints() -> None:
    """通过 HTTP 验证排队/看板/刷新接口。"""
    with TestClient(app) as client:
        # csrf 包装
        original_post = client.post

        def csrf_post(url, *args, **kwargs):
            headers = dict(kwargs.get("headers") or {})
            if "X-CSRF-Token" not in headers:
                token_resp = client.get("/api/auth/csrf")
                headers["X-CSRF-Token"] = token_resp.json()["csrf_token"]
            kwargs["headers"] = headers
            return original_post(url, *args, **kwargs)

        client.post = csrf_post

        def captcha_answer() -> str:
            client.get("/api/auth/captcha")
            session_id = client.cookies.get("cloud_print_session")
            with connect() as db:
                row = db.execute("SELECT captcha_answer FROM auth_sessions WHERE id = ?", (session_id,)).fetchone()
            return row["captcha_answer"]

        admin_login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123456", "captcha": captcha_answer()},
        )
        assert admin_login.status_code == 200, admin_login.text
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}

        # 构造一个 printing 订单用于查询。
        _seed_order(
            "HTTP-PRINTING",
            "printing",
            print_job_id="cups-http-job",
            printed_at="2026-08-03T11:00:00",
            created_at="2026-08-03T10:00:00",
        )

        # GET /api/orders/{id} 应带 queue 字段
        order_row = client.get("/api/orders/HTTP-PRINTING")
        assert order_row.status_code == 200, order_row.text
        assert "queue" in order_row.json(), order_row.json()
        assert order_row.json()["queue"]["in_queue"] is True

        # GET /api/orders/{id}/queue
        order_queue = client.get("/api/orders/HTTP-PRINTING/queue")
        assert order_queue.status_code == 200, order_queue.text
        assert order_queue.json()["position"] >= 1

        # 不存在订单的 queue 端点 -> 404
        assert client.get("/api/orders/NOPE/queue").status_code == 404

        # 后台看板
        admin_queue = client.get("/api/admin/print-queue", headers=admin_headers)
        assert admin_queue.status_code == 200, admin_queue.text
        data = admin_queue.json()
        assert data["total"] >= 1
        assert any(item["id"] == "HTTP-PRINTING" for item in data["items"])

        # 后台看板需要管理员身份：清除会话 cookie 与 Authorization 后应被拒绝。
        saved_cookies = dict(client.cookies)
        client.cookies.clear()
        anon = client.get("/api/admin/print-queue", headers={})
        client.cookies.update(saved_cookies)
        assert anon.status_code in {401, 403}, anon.status_code

        # dashboard 带排队统计
        dashboard = client.get("/api/admin/dashboard", headers=admin_headers)
        assert dashboard.status_code == 200
        totals = dashboard.json()["totals"]
        assert "printing_count" in totals and "queue_count" in totals

        # 管理员主动刷新（真实 print_jobs_active，在无 CUPS 环境返回 None -> 不改状态）
        refresh = client.post("/api/admin/orders/refresh-print-status", headers=admin_headers)
        assert refresh.status_code == 200, refresh.text
        assert refresh.json()["success"] is True
        assert "queue" in refresh.json()

        print("[OK] HTTP 接口：订单 queue 字段、排队端点、后台看板、权限校验、dashboard、刷新接口均正常")


def main() -> None:
    test_queue_service_direct()
    test_monitor_no_nameerror()
    test_http_endpoints()
    print("\n全部排队/状态修复定向测试通过。")
    # Windows 下 SQLite 文件在解释器退出时可能仍被占用，主动放弃临时目录自动清理，避免噪声报错。
    try:
        _tmpdir._finalizer.detach()
    except Exception:
        pass


if __name__ == "__main__":
    main()
