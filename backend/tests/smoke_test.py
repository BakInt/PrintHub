import io
import json
import os
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmpdir = tempfile.TemporaryDirectory()
os.environ["CONFIG_ROOT"] = _tmpdir.name
os.environ["DATABASE_PATH"] = str(Path(_tmpdir.name) / "cloud_print.db")
os.environ["UPLOAD_DIR"] = str(Path(_tmpdir.name) / "uploads")
os.environ["EPAY_PID"] = "1001"
os.environ["EPAY_KEY"] = "smoke-epay-key"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ["FRONTEND_BASE_URL"] = "http://frontend.test"
# 上传的驱动落在这个目录，断言依赖它必须与 CUPS 驱动搜索目录一致。
_CONFIG_PATH = Path(_tmpdir.name) / "config.json"
_CONFIG_PATH.write_text(
    json.dumps({"cups_driver_dir": "cups-drivers"}, ensure_ascii=False),
    encoding="utf-8",
)

from app.main import app
from app.config import Settings, ensure_config_file, get_settings, reload_settings
from app.database import connect
from app.middleware import validate_production_config
from app.services import cups_printer as cups_printer_service
from app.services.cups_printer import _driver_row, _recommend_driver
from app.services.epay import build_success_notify_payload, epay_signature_payload, normalize_epay_gateway, sign_params
from app.services.files import inspect_ole_formula_risk, validate_file_signature
from app.services.pdf_postprocess import flatten_pdf_smask, rasterize_pdf_for_print
from app.services import printer as printer_service
from app.routers import orders as orders_router


def main() -> None:
    assert normalize_epay_gateway("https://pay.example.com") == "https://pay.example.com/submit.php"
    assert normalize_epay_gateway("https://pay.example.com/") == "https://pay.example.com/submit.php"
    assert normalize_epay_gateway("https://legacy-epay-gateway.example.com/api/pay/submit") == "https://your-epay-gateway.example.com/submit.php"
    assert epay_signature_payload({"b": "2", "a": "1", "sign": "old", "sign_type": "MD5", "empty": ""}) == "a=1&b=2"
    windows_printers = printer_service._parse_windows_printer_json(
        '[{"Name":"Huawei Print Queue","PortName":"IP_192.168.1.50","DriverName":"Huawei Driver","Default":true}]'
    )
    assert windows_printers["Huawei_Print_Queue"]["display_name"] == "Huawei Print Queue"
    assert windows_printers["Huawei_Print_Queue"]["uri"] == "IP_192.168.1.50"
    driver_rows = [
        _driver_row("everywhere"),
        _driver_row("drv:///hp/hpcups.drv/hp-laserjet_1020.ppd", {"ppd-make": "HP", "ppd-make-and-model": "HP LaserJet 1020"}),
        _driver_row("drv:///sample.drv/generic.ppd", {"ppd-make": "Generic", "ppd-make-and-model": "Generic PostScript Printer"}),
    ]
    hp_recommendation = _recommend_driver(driver_rows, "HP LaserJet 1020", "socket://192.168.1.45:9100", "socket")
    assert hp_recommendation["driver"] == "drv:///hp/hpcups.drv/hp-laserjet_1020.ppd"
    assert hp_recommendation["confidence"] == "high"
    assert hp_recommendation["install_hint"]["brand"] == "hp"
    huawei_recommendation = _recommend_driver(driver_rows, "HUAWEI PixLab CV81 AirPrint", "dnssd://HUAWEI%20CV81._ipp._tcp.local.", "dnssd")
    assert huawei_recommendation["driver"] == "everywhere"
    assert huawei_recommendation["confidence"] == "high"
    assert huawei_recommendation["install_hint"]["needs_driver_package"] is False
    generic_socket_recommendation = _recommend_driver(driver_rows, "Unknown Office Printer", "socket://192.168.1.45:9100", "socket")
    assert generic_socket_recommendation["driver"] == "drv:///sample.drv/generic.ppd"
    assert generic_socket_recommendation["install_hint"]["severity"] == "warning"
    admin_view_source = (Path(__file__).resolve().parents[2] / "frontend/src/views/AdminView.vue").read_text(encoding="utf-8")
    assert "队列路径" not in admin_view_source
    assert "manualPrinter.queue_path" not in admin_view_source
    # 打印机管理页已改为基于 CUPS 服务器发现/编辑的流程，不再使用自由填写队列路径的手动新增表单。
    assert "CUPS 服务器配置" in admin_view_source
    # 排队看板相关的关键 UI 元素应存在于后台订单管理页。
    assert "实时排队看板" in admin_view_source
    assert "refreshPrintStatus" in admin_view_source
    assert "print-queue" in admin_view_source
    cups_config_path = Path(__file__).resolve().parents[2] / "docker/cups/cupsd.conf"
    cups_entrypoint_path = Path(__file__).resolve().parents[2] / "docker/cups/entrypoint.sh"
    # docker/cups 相关配置只在完整部署仓库中存在；本地精简副本缺失时跳过该校验。
    if cups_config_path.exists() and cups_entrypoint_path.exists():
        cups_config_source = cups_config_path.read_text(encoding="utf-8")
        cups_entrypoint_source = cups_entrypoint_path.read_text(encoding="utf-8")
        assert "cloud-print-cups-policy-v20260705" in cups_config_source
        assert "AuthType None" in cups_config_source
        assert "CUPS-Add-Modify-Printer" in cups_config_source
        assert "CUPS-Delete-Printer" in cups_config_source
        assert "CUPS_REFRESH_CONFIG" in cups_entrypoint_source
    production_settings = Settings(
        environment="production",
        app_secret="x" * 40,
        admin_password="strong-admin-password",
        cors_origins="https://print.example.org",
        epay_gateway="https://epay.example.net/submit.php",
        epay_pid="1001",
        epay_key="production-key",
        public_base_url="https://print.example.org",
        frontend_base_url="https://print.example.org",
    )
    validate_production_config(production_settings)
    bad_production_settings = production_settings.model_copy(update={"frontend_base_url": "http://localhost:5173"})
    try:
        validate_production_config(bad_production_settings)
    except RuntimeError as exc:
        assert "前端返回地址" in str(exc)
    else:
        raise AssertionError("production frontend_base_url should not allow localhost")

    with TestClient(app) as client:
        original_post = client.post
        original_put = client.put
        original_delete = client.delete

        def csrf_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
            merged = dict(headers or {})
            if "X-CSRF-Token" not in merged:
                token_response = client.get("/api/auth/csrf")
                assert token_response.status_code == 200, token_response.text
                merged["X-CSRF-Token"] = token_response.json()["csrf_token"]
            return merged

        def csrf_post(url, *args, **kwargs):
            kwargs["headers"] = csrf_headers(kwargs.get("headers"))
            return original_post(url, *args, **kwargs)

        def csrf_put(url, *args, **kwargs):
            kwargs["headers"] = csrf_headers(kwargs.get("headers"))
            return original_put(url, *args, **kwargs)

        def csrf_delete(url, *args, **kwargs):
            kwargs["headers"] = csrf_headers(kwargs.get("headers"))
            return original_delete(url, *args, **kwargs)

        client.post = csrf_post
        client.put = csrf_put
        client.delete = csrf_delete

        def captcha_answer() -> str:
            captcha = client.get("/api/auth/captcha")
            assert captcha.status_code == 200, captcha.text
            session_id = client.cookies.get("cloud_print_session")
            assert session_id
            with connect() as db:
                row = db.execute("SELECT captcha_answer FROM auth_sessions WHERE id = ?", (session_id,)).fetchone()
                assert row is not None
                return row["captcha_answer"]

        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert health.headers["x-content-type-options"] == "nosniff"

        ready = client.get("/api/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}

        default_limits = client.get("/api/limits")
        assert default_limits.status_code == 200, default_limits.text
        assert default_limits.json() == {"max_file_size_mb": 50, "max_pages": 100}, default_limits.json()

        setup_restore_status = client.get("/api/setup/restore/status")
        assert setup_restore_status.status_code == 200
        assert setup_restore_status.json()["available"] is False

        price = client.post("/api/price", json={"page_count": 10, "copies": 2, "double_sided": True})
        assert price.status_code == 200
        assert price.json()["base_amount"] == 3.0
        assert price.json()["amount"] == 2.85
        assert price.json()["discount_amount"] == 0.15
        assert price.json()["sheet_count"] == 10

        default_promotions = client.get("/api/promotions")
        assert default_promotions.status_code == 200, default_promotions.text
        default_bulk = default_promotions.json()["bulk_discount"]
        assert default_bulk["enabled"] is True
        assert [rule["min_sheets"] for rule in default_bulk["rules"]] == [10, 100, 200]
        assert [rule["label"] for rule in default_bulk["rules"]] == ["满10张/份95折", "满100张/份90折", "满200张/份80折"]
        assert default_promotions.json()["daily_limited_offer"] is None

        register = client.post(
            "/api/auth/register",
            json={"username": "smoke_user", "password": "12345678", "email": "smoke@example.com", "captcha": captcha_answer()},
        )
        assert register.status_code in {200, 409}
        with connect() as db:
            smoke_user_hash = db.execute("SELECT password_hash FROM users WHERE username = ?", ("smoke_user",)).fetchone()
            if smoke_user_hash is not None:
                assert smoke_user_hash["password_hash"].startswith("bcrypt$")

        reused_captcha = captcha_answer()
        bad_login = client.post("/api/auth/login", json={"username": "smoke_user", "password": "wrongpass", "captcha": reused_captcha})
        assert bad_login.status_code == 401
        assert bad_login.json()["detail"] == "用户名或密码错误"
        reused_captcha_login = client.post("/api/auth/login", json={"username": "smoke_user", "password": "12345678", "captcha": reused_captcha})
        assert reused_captcha_login.status_code == 401
        assert reused_captcha_login.json()["detail"] == "用户名或密码错误"

        login = client.post("/api/auth/login", json={"username": "smoke_user", "password": "12345678", "captcha": captcha_answer()})
        assert login.status_code == 200
        token = login.json()["token"]

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["username"] == "smoke_user"
        user_id = me.json()["id"]

        update_profile = client.put(
            "/api/user/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"real_name": "烟测绑定用户", "phone": "13600136000"},
        )
        assert update_profile.status_code == 200, update_profile.text
        assert update_profile.json()["real_name"] == "烟测绑定用户"
        assert update_profile.json()["phone"] == "13600136000"

        me_after_profile = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_after_profile.status_code == 200
        assert me_after_profile.json()["real_name"] == "烟测绑定用户"
        assert me_after_profile.json()["phone"] == "13600136000"
        regular_admin_attempt = client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
        assert regular_admin_attempt.status_code == 403
        assert regular_admin_attempt.json()["detail"] == "无效请求"

        locked_username = "lock_user"
        with connect() as db:
            db.execute(
                """
                INSERT INTO users (id, username, password_hash, balance)
                VALUES (?, ?, ?, 0)
                """,
                ("lock-user-id", locked_username, "$2b$12$invalidhashvalueforforcedfailure"),
            )
            db.commit()
        for _ in range(5):
            locked_try = client.post(
                "/api/auth/login",
                json={"username": locked_username, "password": "wrongpass", "captcha": captcha_answer()},
            )
            assert locked_try.status_code == 401
            assert locked_try.json()["detail"] == "用户名或密码错误"
        locked_correct_try = client.post(
            "/api/auth/login",
            json={"username": locked_username, "password": "12345678", "captcha": captcha_answer()},
        )
        assert locked_correct_try.status_code == 401
        assert locked_correct_try.json()["detail"] == "用户名或密码错误"

        admin_login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123456", "captcha": captcha_answer()})
        assert admin_login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}

        payment_settings = client.get("/api/admin/payment-settings", headers=admin_headers)
        assert payment_settings.status_code == 200
        assert payment_settings.json()["epay_gateway"] == "https://your-epay-gateway.example.com/submit.php"
        assert payment_settings.json()["frontend_base_url"] == "http://frontend.test"
        # 默认网关为占位示例地址（含 example.com），validation 应判定为未就绪
        assert payment_settings.json()["validation"]["ready"] is False

        class FakeCups:
            class IPPError(Exception):
                pass

            def __init__(self, conn):
                self._conn = conn

            def Connection(self):
                return self._conn

            def setServer(self, _server):
                return None

            def setPort(self, _port):
                return None

        class ExistingQueueConnection:
            def __init__(self):
                self.add_called = False

            def getPrinters(self):
                return {
                    "Huawei_PixLab": {
                        "device-uri": "ipp://192.168.1.176/ipp/print",
                        "printer-info": "Huawei PixLab",
                        "printer-location": "smoke lab",
                    }
                }

            def getPrinterAttributes(self, name, requested_attributes=None):
                assert name == "Huawei_PixLab"
                return {
                    "printer-name": "Huawei_PixLab",
                    "printer-info": "Huawei PixLab",
                    "printer-location": "smoke lab",
                    "printer-make-and-model": "HUAWEI PixLab",
                    "printer-state": 3,
                    "printer-state-reasons": ["none"],
                    "printer-is-accepting-jobs": True,
                    "queued-job-count": 0,
                    "printer-uri-supported": "ipp://cups:631/printers/Huawei_PixLab",
                    "device-uri": "ipp://192.168.1.176/ipp/print",
                }

            def getDefault(self):
                return "Huawei_PixLab"

            def addPrinter(self, *_args, **_kwargs):
                self.add_called = True
                raise AssertionError("existing queue should be reused instead of addPrinter")

        fake_conn = ExistingQueueConnection()
        original_cups_module = cups_printer_service.cups
        try:
            cups_printer_service.cups = FakeCups(fake_conn)
            existing_queue_probe = client.post(
                "/api/admin/printer-uri/probe",
                headers=admin_headers,
                json={"host": "192.168.1.176", "connection_type": "ipp"},
            )
            assert existing_queue_probe.status_code == 200, existing_queue_probe.text
            existing_queue_probe_data = existing_queue_probe.json()
            assert existing_queue_probe_data["installed"] is True
            assert existing_queue_probe_data["installed_name"] == "Huawei_PixLab"
            legacy_manual_existing_queue = client.post(
                "/api/admin/printers",
                headers=admin_headers,
                json={
                    "name": "IPP_192_168_31_176",
                    "host": "192.168.1.176",
                    "connection_type": "ipp",
                    "queue_path": "/ipp/print",
                    "driver": "everywhere",
                    "location": "",
                    "description": "IPP 192.168.1.176",
                    "is_default": False,
                    "is_enabled": True,
                },
            )
            assert legacy_manual_existing_queue.status_code == 200, legacy_manual_existing_queue.text
            legacy_manual_data = legacy_manual_existing_queue.json()
            assert legacy_manual_data["message"] == "已连接到现有打印机"
            assert legacy_manual_data["printer"]["name"] == "Huawei_PixLab"
            assert legacy_manual_data["printer"]["uri"] == "ipp://192.168.1.176/ipp/print"
            assert fake_conn.add_called is False
            existing_queue_list = client.get("/api/admin/printers", headers=admin_headers)
            assert existing_queue_list.status_code == 200, existing_queue_list.text
            assert any(printer["name"] == "Huawei_PixLab" for printer in existing_queue_list.json())
        finally:
            cups_printer_service.cups = original_cups_module

        class EmptyPrinterConnection:
            def getPrinters(self):
                return {}

            def getDefault(self):
                return ""

        try:
            cups_printer_service.cups = FakeCups(EmptyPrinterConnection())
            metadata_fallback_list = client.get("/api/admin/printers", headers=admin_headers)
            assert metadata_fallback_list.status_code == 200, metadata_fallback_list.text
            metadata_fallback_printer = next(
                printer for printer in metadata_fallback_list.json() if printer["name"] == "Huawei_PixLab"
            )
            assert metadata_fallback_printer["installed"] is False
            assert metadata_fallback_printer["state"] == "unknown"
            metadata_fallback_detail = client.get("/api/admin/printers/Huawei_PixLab", headers=admin_headers)
            assert metadata_fallback_detail.status_code == 200, metadata_fallback_detail.text
            assert metadata_fallback_detail.json()["installed"] is False
            assert metadata_fallback_detail.json()["state"] == "unknown"
            metadata_fallback_jobs = client.get("/api/admin/printers/Huawei_PixLab/jobs", headers=admin_headers)
            assert metadata_fallback_jobs.status_code == 200, metadata_fallback_jobs.text
            assert metadata_fallback_jobs.json()["jobs"] == []
            metadata_fallback_default = client.put("/api/admin/printers/Huawei_PixLab/default", headers=admin_headers)
            assert metadata_fallback_default.status_code == 200, metadata_fallback_default.text
            metadata_fallback_enabled = client.put(
                "/api/admin/printers/Huawei_PixLab/enabled",
                headers=admin_headers,
                json={"enabled": False, "accepting_jobs": False},
            )
            assert metadata_fallback_enabled.status_code == 200, metadata_fallback_enabled.text
            metadata_fallback_test = client.post("/api/admin/printers/Huawei_PixLab/test", headers=admin_headers)
            assert metadata_fallback_test.status_code == 422, metadata_fallback_test.text
            assert "打印机不存在" not in metadata_fallback_test.text
            assert "暂时不能发送真实测试页" in metadata_fallback_test.text
        finally:
            cups_printer_service.cups = original_cups_module

        class PermissionDeniedNoQueueConnection:
            def getPrinters(self):
                return {}

            def getDefault(self):
                return ""

            def addPrinter(self, *_args, **_kwargs):
                raise RuntimeError("4096: Unauthorized")

        try:
            cups_printer_service.cups = FakeCups(PermissionDeniedNoQueueConnection())
            permission_metadata_printer = client.post(
                "/api/admin/printers",
                headers=admin_headers,
                json={
                    "name": "IPP_10_0_0_25",
                    "host": "10.0.0.25",
                    "connection_type": "ipp",
                    "driver": "everywhere",
                    "description": "IPP 10.0.0.25",
                    "is_default": False,
                    "is_enabled": True,
                },
            )
            assert permission_metadata_printer.status_code == 200, permission_metadata_printer.text
            permission_metadata_data = permission_metadata_printer.json()
            assert permission_metadata_data["message"] == "打印机配置已保存"
            assert permission_metadata_data["printer"]["name"] == "IPP_10_0_0_25"
            assert permission_metadata_data["printer"]["installed"] is False
            permission_metadata_list = client.get("/api/admin/printers", headers=admin_headers)
            assert permission_metadata_list.status_code == 200, permission_metadata_list.text
            assert any(printer["name"] == "IPP_10_0_0_25" for printer in permission_metadata_list.json())
        finally:
            cups_printer_service.cups = original_cups_module

        class PermissionDeniedSingleQueueConnection:
            def __init__(self):
                self.add_called = False

            def getPrinters(self):
                return {
                    "Huawei_PixLab": {
                        "device-uri": "implicitclass://Huawei_PixLab/",
                        "printer-info": "Huawei PixLab",
                        "printer-location": "smoke lab",
                    }
                }

            def getPrinterAttributes(self, name, requested_attributes=None):
                assert name == "Huawei_PixLab"
                return {
                    "printer-name": "Huawei_PixLab",
                    "printer-info": "Huawei PixLab",
                    "printer-location": "smoke lab",
                    "printer-make-and-model": "HUAWEI PixLab",
                    "printer-state": 3,
                    "printer-state-reasons": ["none"],
                    "printer-is-accepting-jobs": True,
                    "queued-job-count": 0,
                    "printer-uri-supported": "ipp://cups:631/printers/Huawei_PixLab",
                    "device-uri": "implicitclass://Huawei_PixLab/",
                }

            def getDefault(self):
                return "Huawei_PixLab"

            def addPrinter(self, *_args, **_kwargs):
                self.add_called = True
                raise RuntimeError("4096: Unauthorized")

        permission_conn = PermissionDeniedSingleQueueConnection()
        try:
            cups_printer_service.cups = FakeCups(permission_conn)
            permission_fallback_queue = client.post(
                "/api/admin/printers",
                headers=admin_headers,
                json={
                    "name": "IPP_192_168_31_176_Fallback",
                    "uri": "ipp://192.168.1.176/ipp/print",
                    "driver": "everywhere",
                    "description": "IPP 192.168.1.176",
                    "is_default": False,
                    "is_enabled": True,
                },
            )
            assert permission_fallback_queue.status_code == 200, permission_fallback_queue.text
            permission_fallback_data = permission_fallback_queue.json()
            assert permission_fallback_data["message"] == "已连接到现有打印机"
            assert permission_fallback_data["printer"]["name"] == "Huawei_PixLab"
            assert permission_conn.add_called is True
            assert "4096" not in permission_fallback_queue.text
        finally:
            cups_printer_service.cups = original_cups_module

        printer_system = client.get("/api/admin/printer-system", headers=admin_headers)
        assert printer_system.status_code == 200, printer_system.text
        assert printer_system.json()["success"] is True
        printer_devices = client.get("/api/admin/printer-devices", headers=admin_headers)
        assert printer_devices.status_code == 200, printer_devices.text
        assert printer_devices.json()["success"] is True
        printer_drivers = client.get("/api/admin/printer-drivers", headers=admin_headers)
        assert printer_drivers.status_code == 200, printer_drivers.text
        assert printer_drivers.json()["drivers"][0]["id"] == "everywhere"
        ppd_upload = client.post(
            "/api/admin/printer-drivers/ppd",
            headers=admin_headers,
            files={
                "file": (
                    "hp-laserjet-1020.ppd",
                    b'\n'.join(
                        [
                            b'*PPD-Adobe: "4.3"',
                            b'*Manufacturer: "HP"',
                            b'*ModelName: "HP LaserJet 1020"',
                            b'*NickName: "HP LaserJet 1020 Foo2zjs"',
                        ]
                    ),
                    "application/vnd.cups-ppd",
                )
            },
        )
        assert ppd_upload.status_code == 200, ppd_upload.text
        assert ppd_upload.json()["driver"]["source"] == "local-ppd"
        assert ppd_upload.json()["driver"]["label"] == "HP LaserJet 1020 Foo2zjs"
        ppd_drivers = client.get(
            "/api/admin/printer-drivers?search=LaserJet&make_model=HP%20LaserJet%201020&uri=socket://192.168.1.45:9100",
            headers=admin_headers,
        )
        assert ppd_drivers.status_code == 200, ppd_drivers.text
        imported_driver = next(item for item in ppd_drivers.json()["drivers"] if item["source"] == "local-ppd")
        assert imported_driver["recommended"] is True
        assert imported_driver["confidence"] == "high"
        package_buffer = io.BytesIO()
        with zipfile.ZipFile(package_buffer, "w") as archive:
            archive.writestr(
                "drivers/brother-hl-2260.ppd",
                "\n".join(
                    [
                        '*PPD-Adobe: "4.3"',
                        '*Manufacturer: "Brother"',
                        '*ModelName: "Brother HL-2260"',
                        '*NickName: "Brother HL-2260 CUPS"',
                    ]
                ),
            )
            archive.writestr(
                "drivers/hp-laserjet-1020.ppd",
                "\n".join(
                    [
                        '*PPD-Adobe: "4.3"',
                        '*Manufacturer: "HP"',
                        '*ModelName: "HP LaserJet 1020"',
                        '*NickName: "HP LaserJet 1020 HPLIP"',
                    ]
                ),
            )
            archive.writestr(
                "drivers/canon-lbp.ppd",
                "\n".join(
                    [
                        '*PPD-Adobe: "4.3"',
                        '*Manufacturer: "Canon"',
                        '*ModelName: "Canon LBP 2900"',
                        '*NickName: "Canon LBP 2900 CAPT"',
                    ]
                ),
            )
            archive.writestr("readme.txt", "vendor package")
        ppd_package_upload = client.post(
            "/api/admin/printer-drivers/ppd",
            headers=admin_headers,
            data={
                "make_model": "HP LaserJet 1020",
                "uri": "socket://192.168.1.45:9100",
                "connection_type": "socket",
            },
            files={"file": ("brother-driver.zip", package_buffer.getvalue(), "application/zip")},
        )
        assert ppd_package_upload.status_code == 200, ppd_package_upload.text
        assert ppd_package_upload.json()["imported_count"] == 3
        package_driver = ppd_package_upload.json()["driver"]
        assert package_driver["source"] == "local-ppd"
        assert package_driver["label"] == "HP LaserJet 1020 HPLIP"
        assert package_driver["recommended"] is True
        assert package_driver["confidence"] == "high"
        assert ppd_package_upload.json()["recommendation"]["driver"] == package_driver["id"]

        tar_package_buffer = io.BytesIO()
        epson_ppd = "\n".join(
            [
                '*PPD-Adobe: "4.3"',
                '*Manufacturer: "Epson"',
                '*ModelName: "Epson EcoTank L3250"',
                '*NickName: "Epson EcoTank L3250 ESC/P-R"',
            ]
        ).encode()
        with tarfile.open(fileobj=tar_package_buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo("epson/epson-l3250.ppd")
            info.size = len(epson_ppd)
            archive.addfile(info, io.BytesIO(epson_ppd))
        tar_ppd_upload = client.post(
            "/api/admin/printer-drivers/ppd",
            headers=admin_headers,
            data={
                "make_model": "Epson EcoTank L3250",
                "uri": "ipp://192.168.1.46/ipp/print",
                "connection_type": "ipp",
            },
            files={"file": ("epson-driver.tar.gz", tar_package_buffer.getvalue(), "application/gzip")},
        )
        assert tar_ppd_upload.status_code == 200, tar_ppd_upload.text
        assert tar_ppd_upload.json()["imported_count"] == 1
        assert tar_ppd_upload.json()["driver"]["label"] == "Epson EcoTank L3250 ESC/P-R"

        create_manual_ipp_printer = client.post(
            "/api/admin/printers",
            headers=admin_headers,
            json={
                "name": "Manual_IPP_Smoke",
                "host": "192.168.1.50",
                "connection_type": "ipp",
                "queue_path": "/ipp/print",
                "driver": "everywhere",
                "location": "smoke lab",
                "description": "Manual IPP smoke printer",
                "is_default": False,
                "is_enabled": True,
            },
        )
        assert create_manual_ipp_printer.status_code == 200, create_manual_ipp_printer.text
        manual_ipp_result = create_manual_ipp_printer.json()
        assert manual_ipp_result["printer"]["name"] == "Manual_IPP_Smoke"
        assert manual_ipp_result["printer"]["uri"] == "ipp://192.168.1.50/ipp/print"
        assert manual_ipp_result["printer"]["driver"] == "everywhere"
        manual_ipp_detail = client.get("/api/admin/printers/Manual_IPP_Smoke", headers=admin_headers)
        assert manual_ipp_detail.status_code == 200, manual_ipp_detail.text
        assert manual_ipp_detail.json()["state"] == "idle"
        manual_ipp_jobs = client.get("/api/admin/printers/Manual_IPP_Smoke/jobs", headers=admin_headers)
        assert manual_ipp_jobs.status_code == 200, manual_ipp_jobs.text
        assert manual_ipp_jobs.json()["jobs"] == []
        set_manual_ipp_default = client.put("/api/admin/printers/Manual_IPP_Smoke/default", headers=admin_headers)
        assert set_manual_ipp_default.status_code == 200, set_manual_ipp_default.text
        disable_manual_ipp = client.put(
            "/api/admin/printers/Manual_IPP_Smoke/enabled",
            headers=admin_headers,
            json={"enabled": False, "accepting_jobs": False},
        )
        assert disable_manual_ipp.status_code == 200, disable_manual_ipp.text
        manual_ipp_disabled = client.get("/api/admin/printers/Manual_IPP_Smoke", headers=admin_headers)
        assert manual_ipp_disabled.status_code == 200, manual_ipp_disabled.text
        assert manual_ipp_disabled.json()["is_enabled"] is False
        assert manual_ipp_disabled.json()["accepting_jobs"] is False
        rename_manual_ipp = client.put(
            "/api/admin/printers/Manual_IPP_Smoke",
            headers=admin_headers,
            json={"new_name": "Manual_IPP_Smoke_Renamed", "uri": "ipp://192.168.1.50/ipp/print", "is_enabled": True},
        )
        assert rename_manual_ipp.status_code == 200, rename_manual_ipp.text
        assert rename_manual_ipp.json()["printer"]["name"] == "Manual_IPP_Smoke_Renamed"

        create_manual_socket_printer = client.post(
            "/api/admin/printers",
            headers=admin_headers,
            json={
                "name": "Manual_Socket_Smoke",
                "host": "192.168.1.51",
                "connection_type": "socket",
                "driver": "everywhere",
                "location": "smoke lab",
                "description": "Manual socket smoke printer",
                "is_default": False,
                "is_enabled": True,
            },
        )
        assert create_manual_socket_printer.status_code == 200, create_manual_socket_printer.text
        manual_socket_result = create_manual_socket_printer.json()
        assert manual_socket_result["printer"]["name"] == "Manual_Socket_Smoke"
        assert manual_socket_result["printer"]["uri"] == "socket://192.168.1.51:9100"
        assert manual_socket_result["printer"]["driver"] == "everywhere"

        # 已移除 mock 打印模式：真实测试页需要可用的 CUPS 队列，无法在无 CUPS 的冒烟环境断言假打印结果。

        original_list_system_printers = printer_service.list_system_printers
        try:
            printer_service.list_system_printers = lambda: {
                "Smoke_System_Printer": {
                    "uri": "ipp://192.168.1.60/ipp/print",
                    "driver": "everywhere",
                    "location": "smoke lab",
                    "description": "Smoke system printer",
                    "status": "idle",
                    "is_default": False,
                }
            }
            import_system_printer = client.post(
                "/api/admin/printers/import",
                headers=admin_headers,
                json={
                    "name": "Smoke_System_Printer",
                    "uri": "ipp://192.168.1.60/ipp/print",
                    "driver": "everywhere",
                    "location": "smoke lab",
                    "description": "Smoke system printer",
                    "is_default": False,
                    "is_enabled": True,
                    "installed": True,
                },
            )
            assert import_system_printer.status_code == 200, import_system_printer.text
            delete_system_printer = client.delete("/api/admin/printers/Smoke_System_Printer", headers=admin_headers)
            assert delete_system_printer.status_code == 200, delete_system_printer.text
            printers_after_delete = client.get("/api/admin/printers", headers=admin_headers)
            assert printers_after_delete.status_code == 200
            assert all(item["name"] != "Smoke_System_Printer" for item in printers_after_delete.json())
            reimport_system_printer = client.post(
                "/api/admin/printers/import",
                headers=admin_headers,
                json={
                    "name": "Smoke_System_Printer",
                    "uri": "ipp://192.168.1.60/ipp/print",
                    "driver": "everywhere",
                    "location": "smoke lab",
                    "description": "Smoke system printer",
                    "is_default": False,
                    "is_enabled": True,
                    "installed": True,
                },
            )
            assert reimport_system_printer.status_code == 200, reimport_system_printer.text
            printers_after_reimport = client.get("/api/admin/printers", headers=admin_headers)
            assert printers_after_reimport.status_code == 200
            assert any(item["name"] == "Smoke_System_Printer" for item in printers_after_reimport.json())
        finally:
            printer_service.list_system_printers = original_list_system_printers

        save_payment_settings = client.put(
            "/api/admin/payment-settings",
            headers=admin_headers,
            json={
                "epay_gateway": "https://pay.example.com",
                "epay_pid": "1001",
                "epay_key": "",
                "public_base_url": "http://testserver",
                "frontend_base_url": "http://frontend.test",
            },
        )
        assert save_payment_settings.status_code == 200, save_payment_settings.text
        payment_settings = client.get("/api/admin/payment-settings", headers=admin_headers)
        assert payment_settings.status_code == 200
        assert payment_settings.json()["epay_gateway"] == "https://pay.example.com/submit.php"
        assert payment_settings.json()["frontend_base_url"] == "http://frontend.test"

        with connect() as db:
            db.execute(
                """
                INSERT INTO files (id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, page_coverages, is_safe, status)
                VALUES (?, ?, ?, ?, 3, 0.01, 21.0, ?, 1, 'ready')
                """,
                (
                    "coverage-tier-file",
                    "coverage-tier-file.pdf",
                    "/tmp/coverage-tier-file/original.pdf",
                    "/tmp/coverage-tier-file/original.pdf",
                    "[3, 20, 40]",
                ),
            )
            db.execute(
                """
                INSERT INTO files (id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, is_safe, status)
                VALUES (?, ?, ?, ?, 2, 0.01, 20.0, 1, 'ready')
                """,
                (
                    "coverage-legacy-file",
                    "coverage-legacy-file.pdf",
                    "/tmp/coverage-legacy-file/original.pdf",
                    "/tmp/coverage-legacy-file/original.pdf",
                ),
            )
            db.execute(
                """
                INSERT INTO files (id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, is_safe, status)
                VALUES (?, ?, ?, ?, 20, 0.01, 5.0, 1, 'ready')
                """,
                (
                    "discount-file",
                    "discount-file.pdf",
                    "/tmp/discount-file/original.pdf",
                    "/tmp/discount-file/original.pdf",
                ),
            )
            db.execute(
                """
                INSERT INTO files (id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, is_safe, status)
                VALUES (?, ?, ?, ?, 1, 0.01, 5.0, 1, 'ready')
                """,
                (
                    "single-page-file",
                    "single-page-file.pdf",
                    "/tmp/single-page-file/original.pdf",
                    "/tmp/single-page-file/original.pdf",
                ),
            )
            db.execute(
                """
                INSERT INTO files (id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, is_safe, status)
                VALUES (?, ?, ?, ?, 1, 0.01, 5.0, 1, 'ready')
                """,
                (
                    "single-page-file-b",
                    "single-page-file-b.pdf",
                    "/tmp/single-page-file-b/original.pdf",
                    "/tmp/single-page-file-b/original.pdf",
                ),
            )
            db.commit()

        bulk_discount_price = client.post(
            "/api/price",
            json={"file_ids": ["discount-file"], "copies": 1, "double_sided": True},
        )
        assert bulk_discount_price.status_code == 200, bulk_discount_price.text
        assert bulk_discount_price.json()["amount"] == 2.85
        assert bulk_discount_price.json()["base_amount"] == 3.0
        assert bulk_discount_price.json()["discount_amount"] == 0.15
        assert bulk_discount_price.json()["sheet_count"] == 10
        assert bulk_discount_price.json()["applied_discount"]["type"] == "bulk"

        # 单页文档禁止双面打印：下单接口应拒绝，且给出明确提示信息。
        single_page_duplex_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["single-page-file"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": True,
                    "contact_name": "单页用户",
                    "contact_phone": "13700137000",
                },
                "payment_method": "alipay",
            },
        )
        assert single_page_duplex_order.status_code == 400, single_page_duplex_order.text
        assert "双面打印" in single_page_duplex_order.json()["detail"]
        # 单页文档的单面打印仍可正常下单。
        single_page_single_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["single-page-file"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": False,
                    "contact_name": "单页用户",
                    "contact_phone": "13700137000",
                },
                "payment_method": "alipay",
            },
        )
        assert single_page_single_order.status_code == 200, single_page_single_order.text
        # 多页文档的双面打印不受影响，可正常下单。
        multi_page_duplex_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["discount-file"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": True,
                    "contact_name": "多页用户",
                    "contact_phone": "13700137000",
                },
                "payment_method": "alipay",
            },
        )
        assert multi_page_duplex_order.status_code == 200, multi_page_duplex_order.text
        # 两份单页文档不再允许合并到同一张纸的正反面：全局双面时应被拒绝。
        two_single_page_duplex_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["single-page-file", "single-page-file-b"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": True,
                    "contact_name": "合并用户",
                    "contact_phone": "13700137000",
                },
                "payment_method": "alipay",
            },
        )
        assert two_single_page_duplex_order.status_code == 400, two_single_page_duplex_order.text
        assert "双面打印" in two_single_page_duplex_order.json()["detail"]
        # 按份双面：多页文档启用双面、单页文档保持单面，应正常下单，并逐份落库。
        per_file_duplex_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["discount-file", "single-page-file"],
                "print_settings": {
                    "copies": 1,
                    "file_settings": [
                        {"file_id": "discount-file", "double_sided": True},
                        {"file_id": "single-page-file", "double_sided": False},
                    ],
                    "contact_name": "按份用户",
                    "contact_phone": "13700137000",
                },
                "payment_method": "alipay",
            },
        )
        assert per_file_duplex_order.status_code == 200, per_file_duplex_order.text
        per_file_order_id = per_file_duplex_order.json()["order_id"]
        per_file_detail = client.get(
            f"/api/admin/orders/{per_file_order_id}/detail",
            headers=admin_headers,
        )
        assert per_file_detail.status_code == 200, per_file_detail.text
        per_file_files = {item["id"]: item for item in per_file_detail.json()["files"]}
        assert per_file_files["discount-file"]["is_double_sided"] is True
        assert per_file_files["single-page-file"]["is_double_sided"] is False
        # 按份双面：给单页文档单独开启双面应被拒绝。
        per_file_single_duplex_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["discount-file", "single-page-file"],
                "print_settings": {
                    "copies": 1,
                    "file_settings": [
                        {"file_id": "discount-file", "double_sided": False},
                        {"file_id": "single-page-file", "double_sided": True},
                    ],
                    "contact_name": "按份用户",
                    "contact_phone": "13700137000",
                },
                "payment_method": "alipay",
            },
        )
        assert per_file_single_duplex_order.status_code == 400, per_file_single_duplex_order.text
        assert "双面打印" in per_file_single_duplex_order.json()["detail"]
        # 按份价格接口：discount-file 双面 + single-page-file 单面。
        per_file_price = client.post(
            "/api/price",
            json={
                "file_ids": ["discount-file", "single-page-file"],
                "copies": 1,
                "file_settings": [
                    {"file_id": "discount-file", "double_sided": True},
                    {"file_id": "single-page-file", "double_sided": False},
                ],
            },
        )
        assert per_file_price.status_code == 200, per_file_price.text
        # discount-file 双面 ceil(20/2)=10 张，single-page-file 单面 1 张，合计 11 张。
        assert per_file_price.json()["sheet_count"] == 11
        # base = 10*0.3 + 1*0.5 = 3.5
        assert per_file_price.json()["base_amount"] == 3.5
        # 清理上述验证性订单，避免影响后续限时特价的已用张数统计。
        for duplex_check_order in (single_page_single_order, multi_page_duplex_order, per_file_duplex_order):
            cleanup_duplex_order = client.delete(
                f"/api/admin/orders/{duplex_check_order.json()['order_id']}/unpaid",
                headers=admin_headers,
            )
            assert cleanup_duplex_order.status_code == 200, cleanup_duplex_order.text
        disable_bulk_discount = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"bulk_discount_enabled": False},
        )
        assert disable_bulk_discount.status_code == 200, disable_bulk_discount.text
        bulk_discount_off_price = client.post(
            "/api/price",
            json={"file_ids": ["discount-file"], "copies": 1, "double_sided": True},
        )
        assert bulk_discount_off_price.status_code == 200, bulk_discount_off_price.text
        assert bulk_discount_off_price.json()["amount"] == 3.0
        assert bulk_discount_off_price.json()["discount_amount"] == 0
        assert bulk_discount_off_price.json()["applied_discount"] is None
        bulk_discount_off_promotions = client.get("/api/promotions")
        assert bulk_discount_off_promotions.status_code == 200, bulk_discount_off_promotions.text
        assert bulk_discount_off_promotions.json()["bulk_discount"]["enabled"] is False
        assert bulk_discount_off_promotions.json()["bulk_discount"]["rules"] == []
        enable_bulk_discount = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"bulk_discount_enabled": True},
        )
        assert enable_bulk_discount.status_code == 200, enable_bulk_discount.text

        limited_offer_settings = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={
                "daily_limited_offer_enabled": True,
                "daily_limited_offer_start_time": "00:00",
                "daily_limited_offer_end_time": "23:59",
                "daily_limited_offer_sheet_quota": 100,
                "daily_limited_offer_discount": 0.50,
            },
        )
        assert limited_offer_settings.status_code == 200, limited_offer_settings.text
        limited_offer_promotions = client.get("/api/promotions")
        assert limited_offer_promotions.status_code == 200, limited_offer_promotions.text
        limited_offer_promo = limited_offer_promotions.json()["daily_limited_offer"]
        assert limited_offer_promo["label"] == "今日限时特价50折"
        assert limited_offer_promo["start_time"] == "00:00"
        assert limited_offer_promo["end_time"] == "23:59"
        assert limited_offer_promo["quota"] == 100
        assert limited_offer_promo["used_sheets"] == 0
        assert limited_offer_promo["remaining_sheets"] == 100
        limited_offer_price = client.post(
            "/api/price",
            json={"file_ids": ["discount-file"], "copies": 1, "double_sided": False},
        )
        assert limited_offer_price.status_code == 200, limited_offer_price.text
        assert limited_offer_price.json()["amount"] == 5.0
        assert limited_offer_price.json()["base_amount"] == 10.0
        assert limited_offer_price.json()["sheet_count"] == 20
        assert limited_offer_price.json()["applied_discount"]["type"] == "daily_limited"
        limited_offer_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["discount-file"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": False,
                    "contact_name": "优惠用户",
                    "contact_phone": "13700137000",
                },
                "payment_method": "alipay",
            },
        )
        assert limited_offer_order.status_code == 200, limited_offer_order.text
        assert limited_offer_order.json()["amount"] == limited_offer_price.json()["amount"]
        assert limited_offer_order.json()["discount_amount"] == 5.0
        limited_offer_used_promotions = client.get("/api/promotions")
        assert limited_offer_used_promotions.status_code == 200, limited_offer_used_promotions.text
        assert limited_offer_used_promotions.json()["daily_limited_offer"]["used_sheets"] == 20
        assert limited_offer_used_promotions.json()["daily_limited_offer"]["remaining_sheets"] == 80
        limited_offer_quota_settings = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"daily_limited_offer_sheet_quota": 25},
        )
        assert limited_offer_quota_settings.status_code == 200, limited_offer_quota_settings.text
        quota_exceeded_price = client.post(
            "/api/price",
            json={"file_ids": ["discount-file"], "copies": 1, "double_sided": False},
        )
        assert quota_exceeded_price.status_code == 200, quota_exceeded_price.text
        assert quota_exceeded_price.json()["amount"] == 9.5
        assert quota_exceeded_price.json()["applied_discount"]["type"] == "bulk"
        cleanup_limited_offer_order = client.delete(
            f"/api/admin/orders/{limited_offer_order.json()['order_id']}/unpaid",
            headers=admin_headers,
        )
        assert cleanup_limited_offer_order.status_code == 200, cleanup_limited_offer_order.text
        # 每日限时特价的“完全免费”开关：命中额度时限时特价直接把金额打到 0，
        # 订单免支付并直接派发打印，不走易支付网关。
        free_offer_settings = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={
                "daily_limited_offer_enabled": True,
                "daily_limited_offer_start_time": "00:00",
                "daily_limited_offer_end_time": "23:59",
                "daily_limited_offer_sheet_quota": 100,
                "daily_limited_offer_free": True,
            },
        )
        assert free_offer_settings.status_code == 200, free_offer_settings.text
        free_offer_promo = client.get("/api/promotions").json()["daily_limited_offer"]
        assert free_offer_promo["free"] is True
        assert free_offer_promo["label"] == "今日限时免费"
        assert free_offer_promo["discount"] == 0
        free_offer_price = client.post(
            "/api/price",
            json={"file_ids": ["discount-file"], "copies": 1, "double_sided": False},
        )
        assert free_offer_price.status_code == 200, free_offer_price.text
        assert free_offer_price.json()["amount"] == 0
        assert free_offer_price.json()["base_amount"] == 10.0
        assert free_offer_price.json()["discount_amount"] == 10.0
        assert free_offer_price.json()["applied_discount"]["type"] == "daily_limited"
        assert free_offer_price.json()["applied_discount"]["free"] is True
        free_offer_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["discount-file"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": False,
                    "contact_name": "免费用户",
                    "contact_phone": "13700137000",
                },
                "payment_method": "alipay",
            },
        )
        assert free_offer_order.status_code == 200, free_offer_order.text
        assert free_offer_order.json()["amount"] == 0
        assert free_offer_order.json()["free_order"] is True
        assert free_offer_order.json()["qr_code_url"] is None
        free_offer_order_row = client.get(f"/api/orders/{free_offer_order.json()['order_id']}")
        assert free_offer_order_row.status_code == 200, free_offer_order_row.text
        assert free_offer_order_row.json()["status"] in {"paid", "printing", "completed"}
        assert free_offer_order_row.json()["paid_at"]
        cleanup_free_offer_order = client.delete(
            f"/api/admin/orders/{free_offer_order.json()['order_id']}",
            headers=admin_headers,
        )
        assert cleanup_free_offer_order.status_code == 200, cleanup_free_offer_order.text
        reset_free_offer = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"daily_limited_offer_free": False},
        )
        assert reset_free_offer.status_code == 200, reset_free_offer.text
        disable_limited_offer = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"daily_limited_offer_enabled": False},
        )
        assert disable_limited_offer.status_code == 200, disable_limited_offer.text

        # 回归：后台「覆盖率阈值/文件大小限制/最大页数」必须立即生效。
        # 修复前 safety_result()/save_upload()/page_count() 只读环境变量 Settings，
        # 后台把覆盖率阈值改成 30 后上传判断仍按旧值（默认 40），即「后台修改无效」。
        limit_settings = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"safety_coverage_limit": 30, "max_pages": 3, "max_file_size_mb": 7},
        )
        assert limit_settings.status_code == 200, limit_settings.text
        saved_limits = client.get("/api/admin/settings", headers=admin_headers)
        assert saved_limits.status_code == 200, saved_limits.text
        assert float(saved_limits.json()["safety_coverage_limit"]) == 30.0
        # 「打印模式」配置已整体移除：旧库即便残留该键也会在 init_db 时清理，接口不再回显。
        assert "print_mode" not in saved_limits.json(), saved_limits.json()
        # 公开上传限制接口必须与后台设置一致（首页文案用它渲染，避免写死 50MB）。
        public_limits = client.get("/api/limits")
        assert public_limits.status_code == 200, public_limits.text
        assert public_limits.json() == {"max_file_size_mb": 7, "max_pages": 3}, public_limits.json()
        from app.config import get_settings as get_app_settings
        from app.services.files import effective_max_file_size_mb, effective_max_pages
        from app.services.safety import safety_coverage_limit, safety_result

        with connect() as limit_db:
            # 服务层必须读数据库设置，而不是环境变量默认值。
            assert safety_coverage_limit(limit_db) == 30.0
            assert effective_max_pages(limit_db) == 3
            assert effective_max_file_size_mb(limit_db) == 7
            # 25% < 30% 判安全；31% > 30% 判不安全，且提示使用最新阈值。
            assert safety_result(25.0, limit_db) == (True, None)
            unsafe_ok, unsafe_warning = safety_result(31.0, limit_db)
            assert unsafe_ok is False
            assert "超过 30% 限制" in unsafe_warning
            # 数据库缺键或值非法时回退环境变量默认值，且不抛异常（兼容旧库/脏数据）。
            limit_db.execute("DELETE FROM settings WHERE key = 'safety_coverage_limit'")
            limit_db.execute("UPDATE settings SET value = '' WHERE key = 'max_pages'")
            limit_db.commit()
            env_settings = get_app_settings()
            assert safety_coverage_limit(limit_db) == float(env_settings.safety_coverage_limit)
            assert effective_max_pages(limit_db) == int(env_settings.max_pages)
        restore_limits = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"safety_coverage_limit": 40, "max_pages": 100, "max_file_size_mb": 50},
        )
        assert restore_limits.status_code == 200, restore_limits.text

        coverage_settings = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={
                "pricing_mode": "coverage_tiered",
                "coverage_single_base_price": 0.10,
                "coverage_duplex_base_price": 0.08,
            },
        )
        assert coverage_settings.status_code == 200, coverage_settings.text
        coverage_single = client.post(
            "/api/price",
            json={"file_ids": ["coverage-tier-file"], "copies": 1, "double_sided": False},
        )
        assert coverage_single.status_code == 200, coverage_single.text
        assert coverage_single.json()["pricing_mode"] == "coverage_tiered"
        assert coverage_single.json()["amount"] == 0.93
        coverage_duplex = client.post(
            "/api/price",
            json={"file_ids": ["coverage-tier-file"], "copies": 1, "double_sided": True},
        )
        assert coverage_duplex.status_code == 200, coverage_duplex.text
        assert coverage_duplex.json()["amount"] == 0.74
        coverage_copies = client.post(
            "/api/price",
            json={"file_ids": ["coverage-tier-file"], "copies": 2, "double_sided": False},
        )
        assert coverage_copies.status_code == 200, coverage_copies.text
        assert coverage_copies.json()["amount"] == 1.85
        legacy_coverage = client.post(
            "/api/price",
            json={"file_ids": ["coverage-legacy-file"], "copies": 1, "double_sided": False},
        )
        assert legacy_coverage.status_code == 200, legacy_coverage.text
        assert legacy_coverage.json()["amount"] == 0.65
        coverage_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["coverage-tier-file"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": False,
                    "contact_name": "覆盖率用户",
                    "contact_phone": "13800138000",
                },
                "payment_method": "alipay",
            },
        )
        assert coverage_order.status_code == 200, coverage_order.text
        assert coverage_order.json()["amount"] == coverage_single.json()["amount"]
        assert coverage_order.json()["order_id"].isdigit()
        restore_standard_settings = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"pricing_mode": "standard"},
        )
        assert restore_standard_settings.status_code == 200, restore_standard_settings.text

        with connect() as db:
            for file_id in (
                "smoke-file-alipay",
                "smoke-file-wxpay",
                "smoke-file-epay",
                "smoke-file-free",
                "smoke-file-balance",
                "smoke-file-unpaid-delete",
                "smoke-file-bulk-unpaid-1",
                "smoke-file-bulk-unpaid-2",
                "smoke-file-return-print",
                "smoke-file-recover-print",
                "smoke-file-profile-contact",
            ):
                db.execute(
                    """
                    INSERT INTO files (id, original_name, stored_path, pdf_path, page_count, file_size, black_coverage, is_safe, status)
                    VALUES (?, ?, ?, ?, 1, 0.01, 3.0, 1, 'ready')
                    """,
                    (file_id, f"{file_id}.pdf", f"/tmp/{file_id}/original.pdf", f"/tmp/{file_id}/original.pdf"),
                )
            db.commit()

        # mock 打印模式已移除；订单派发链路会调用真实 print_pdf，而冒烟环境没有可用的 CUPS 服务。
        # 为了让下单/支付/打印派发流程可确定性验证，这里把 orders 路由使用的 print_pdf 打桩为固定成功返回。
        original_dispatch_print_pdf = orders_router.print_pdf
        orders_router.print_pdf = lambda *args, **kwargs: ("cups-smoke-job", None)

        def create_print_order(payment_method: str, file_id: str, headers: dict[str, str] | None = None) -> dict:
            response = client.post(
                "/api/payment/create",
                headers=headers or {},
                json={
                    "file_ids": [file_id],
                    "print_settings": {
                        "copies": 1,
                        "double_sided": False,
                        "contact_name": "烟测用户",
                        "contact_phone": "13900139000",
                    },
                    "payment_method": payment_method,
                },
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["amount"] == 0.5
            assert data["order_id"].isdigit()
            return data

        invalid_phone_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["smoke-file-alipay"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": False,
                    "contact_name": "烟测用户",
                    "contact_phone": "12345",
                },
                "payment_method": "alipay",
            },
        )
        assert invalid_phone_order.status_code == 422

        profile_contact_order = client.post(
            "/api/payment/create",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "file_ids": ["smoke-file-profile-contact"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": False,
                },
                "payment_method": "alipay",
            },
        )
        assert profile_contact_order.status_code == 200, profile_contact_order.text
        profile_contact_order_row = client.get(f"/api/orders/{profile_contact_order.json()['order_id']}")
        assert profile_contact_order_row.status_code == 200
        assert profile_contact_order_row.json()["contact_name"] == "烟测绑定用户"
        assert profile_contact_order_row.json()["contact_phone"] == "13600136000"

        alipay_order = create_print_order("alipay", "smoke-file-alipay")
        assert alipay_order["qr_code_url"] == f"/api/payment/submit/{alipay_order['order_id']}"
        alipay_order_row = client.get(f"/api/orders/{alipay_order['order_id']}")
        assert alipay_order_row.status_code == 200
        assert alipay_order_row.json()["payment_method"] == "alipay"
        assert alipay_order_row.json()["contact_name"] == "烟测用户"
        assert alipay_order_row.json()["contact_phone"] == "13900139000"

        admin_orders = client.get("/api/admin/orders", headers=admin_headers)
        assert admin_orders.status_code == 200
        admin_alipay_order = next(item for item in admin_orders.json() if item["id"] == alipay_order["order_id"])
        assert admin_alipay_order["payment_status"] == "pending"
        assert "payment_paid_at" in admin_alipay_order
        assert "epay_trade_no" in admin_alipay_order

        admin_alipay_detail = client.get(f"/api/admin/orders/{alipay_order['order_id']}/detail", headers=admin_headers)
        assert admin_alipay_detail.status_code == 200
        assert admin_alipay_detail.json()["order"]["payment_status"] == "pending"
        assert admin_alipay_detail.json()["order"]["contact_name"] == "烟测用户"
        assert admin_alipay_detail.json()["order"]["contact_phone"] == "13900139000"

        wxpay_order = create_print_order("wxpay", "smoke-file-wxpay")
        assert wxpay_order["qr_code_url"] == f"/api/payment/submit/{wxpay_order['order_id']}"
        wxpay_order_row = client.get(f"/api/orders/{wxpay_order['order_id']}")
        assert wxpay_order_row.status_code == 200
        assert wxpay_order_row.json()["payment_method"] == "wxpay"

        legacy_epay_order = create_print_order("epay", "smoke-file-epay")
        assert legacy_epay_order["qr_code_url"] == f"/api/payment/submit/{legacy_epay_order['order_id']}"
        legacy_epay_order_row = client.get(f"/api/orders/{legacy_epay_order['order_id']}")
        assert legacy_epay_order_row.status_code == 200
        assert legacy_epay_order_row.json()["payment_method"] == "alipay"

        # 0 元订单不应跳转易支付网关，应直接免支付成功并派发打印
        free_price_setting = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"single_price": 0},
        )
        assert free_price_setting.status_code == 200, free_price_setting.text
        free_order = client.post(
            "/api/payment/create",
            json={
                "file_ids": ["smoke-file-free"],
                "print_settings": {
                    "copies": 1,
                    "double_sided": False,
                    "contact_name": "烟测用户",
                    "contact_phone": "13900139000",
                },
                "payment_method": "alipay",
            },
        )
        assert free_order.status_code == 200, free_order.text
        free_order_data = free_order.json()
        assert free_order_data["amount"] == 0
        assert free_order_data["free_order"] is True
        assert free_order_data["qr_code_url"] is None
        free_order_row = client.get(f"/api/orders/{free_order_data['order_id']}")
        assert free_order_row.status_code == 200
        assert free_order_row.json()["status"] in {"paid", "printing", "completed"}
        assert free_order_row.json()["paid_at"]
        restore_single_price = client.put(
            "/api/admin/settings",
            headers=admin_headers,
            json={"single_price": 0.5},
        )
        assert restore_single_price.status_code == 200, restore_single_price.text

        set_balance = client.put(f"/api/admin/users/{user_id}/balance", headers=admin_headers, json={"balance": 10})
        assert set_balance.status_code == 200, set_balance.text

        client.cookies.clear()
        unauthenticated_recharge = client.post("/api/user/recharge", json={"amount": 5, "payment_method": "alipay"})
        assert unauthenticated_recharge.status_code == 401
        invalid_small_recharge = client.post(
            "/api/user/recharge",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 0.99, "payment_method": "alipay"},
        )
        assert invalid_small_recharge.status_code == 422
        invalid_large_recharge = client.post(
            "/api/user/recharge",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 2000.01, "payment_method": "alipay"},
        )
        assert invalid_large_recharge.status_code == 422
        over_balance_limit = client.put(f"/api/admin/users/{user_id}/balance", headers=admin_headers, json={"balance": 99999.5})
        assert over_balance_limit.status_code == 200, over_balance_limit.text
        over_limit_recharge = client.post(
            "/api/user/recharge",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 1, "payment_method": "alipay"},
        )
        assert over_limit_recharge.status_code == 400
        restore_balance = client.put(f"/api/admin/users/{user_id}/balance", headers=admin_headers, json={"balance": 10})
        assert restore_balance.status_code == 200, restore_balance.text

        recharge_order = client.post(
            "/api/user/recharge",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount": 25, "payment_method": "alipay"},
        )
        assert recharge_order.status_code == 200, recharge_order.text
        recharge_data = recharge_order.json()
        assert recharge_data["amount"] == 25
        assert recharge_data["payment_method"] == "alipay"
        assert recharge_data["qr_code_url"] == f"/api/payment/submit/{recharge_data['order_id']}"
        recharge_row = client.get(f"/api/orders/{recharge_data['order_id']}")
        assert recharge_row.status_code == 200
        assert recharge_row.json()["order_type"] == "recharge"
        assert recharge_row.json()["status"] == "pending"
        assert recharge_row.json()["print_job_id"] is None
        with connect() as db:
            recharge_items = db.execute("SELECT COUNT(*) AS count FROM order_items WHERE order_id = ?", (recharge_data["order_id"],)).fetchone()
            assert recharge_items["count"] == 0

        mismatch_recharge_payload = build_success_notify_payload(
            recharge_data["order_id"],
            26,
            "云打印余额充值",
            "alipay",
            trade_no="SMOKE_RECHARGE_MISMATCH",
        )
        mismatch_recharge_notify = client.post("/api/payment/notify", data=mismatch_recharge_payload)
        assert mismatch_recharge_notify.status_code == 400
        after_mismatch_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert after_mismatch_me.status_code == 200
        assert after_mismatch_me.json()["balance"] == 10

        recharge_payload = build_success_notify_payload(
            recharge_data["order_id"],
            recharge_data["amount"],
            "云打印余额充值",
            "alipay",
            trade_no="SMOKE_RECHARGE_SUCCESS",
        )
        recharge_notify = client.post("/api/payment/notify", data=recharge_payload)
        assert recharge_notify.status_code == 200
        paid_recharge_row = client.get(f"/api/orders/{recharge_data['order_id']}")
        assert paid_recharge_row.status_code == 200
        assert paid_recharge_row.json()["status"] == "paid"
        assert paid_recharge_row.json()["print_job_id"] is None
        assert paid_recharge_row.json()["balance_applied_at"] is not None
        paid_recharge_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert paid_recharge_me.status_code == 200
        assert paid_recharge_me.json()["balance"] == 35
        with connect() as db:
            paid_recharge_payment = db.execute("SELECT status FROM payments WHERE order_id = ?", (recharge_data["order_id"],)).fetchone()
            assert paid_recharge_payment["status"] == "paid"

        # 订单列表分页：默认每页 10 条，返回 items/total/has_more/total_spent。
        orders_headers = {"Authorization": f"Bearer {token}"}
        with connect() as db:
            expected_total = db.execute("SELECT COUNT(*) AS c FROM orders WHERE user_id = ?", (user_id,)).fetchone()["c"]
            expected_spent = db.execute(
                "SELECT COALESCE(SUM(total_amount), 0) AS s FROM orders WHERE user_id = ? AND order_type = 'print'",
                (user_id,),
            ).fetchone()["s"]
        orders_page = client.get("/api/user/orders", headers=orders_headers)
        assert orders_page.status_code == 200, orders_page.text
        orders_body = orders_page.json()
        assert isinstance(orders_body, dict) and "items" in orders_body
        assert orders_body["total"] == expected_total
        assert round(orders_body["total_spent"], 2) == round(float(expected_spent or 0), 2)
        assert len(orders_body["items"]) == min(10, expected_total)
        assert orders_body["has_more"] == (expected_total > 10)
        # 分页参数：limit=1 时应还有更多，且第二页 offset=1 不与第一页重复。
        first_one = client.get("/api/user/orders", headers=orders_headers, params={"limit": 1, "offset": 0})
        assert first_one.status_code == 200
        first_one_body = first_one.json()
        assert len(first_one_body["items"]) == min(1, expected_total)
        if expected_total > 1:
            assert first_one_body["has_more"] is True
            second_one = client.get("/api/user/orders", headers=orders_headers, params={"limit": 1, "offset": 1})
            assert second_one.status_code == 200
            assert second_one.json()["items"][0]["id"] != first_one_body["items"][0]["id"]
        # 越界参数应被拒绝（limit>50 或负 offset）。
        assert client.get("/api/user/orders", headers=orders_headers, params={"limit": 51}).status_code == 422
        assert client.get("/api/user/orders", headers=orders_headers, params={"offset": -1}).status_code == 422
        assert client.get("/api/user/orders", headers=orders_headers, params={"limit": 0}).status_code == 422

        duplicate_recharge_notify = client.get("/api/payment/notify", params=recharge_payload)
        assert duplicate_recharge_notify.status_code == 200
        duplicate_recharge_return = client.get(
            f"/api/payment/return/{recharge_data['order_id']}",
            params=recharge_payload,
            follow_redirects=False,
        )
        assert duplicate_recharge_return.status_code == 303
        assert duplicate_recharge_return.headers["location"] == f"http://frontend.test/user/dashboard?recharge_order={recharge_data['order_id']}"
        duplicate_recharge_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert duplicate_recharge_me.status_code == 200
        assert duplicate_recharge_me.json()["balance"] == 35

        balance_order = create_print_order("balance", "smoke-file-balance", {"Authorization": f"Bearer {token}"})
        assert balance_order["balance_deducted"] is True
        balance_order_row = client.get(f"/api/orders/{balance_order['order_id']}")
        assert balance_order_row.status_code == 200
        assert balance_order_row.json()["payment_method"] == "balance"
        assert balance_order_row.json()["status"] == "printing"

        # 排队计算：余额支付订单已进入 printing 状态，应出现在打印队列中。
        create_queue = balance_order["queue"]
        assert create_queue["in_queue"] is True
        assert create_queue["position"] >= 1
        assert create_queue["total"] >= 1
        assert create_queue["printing"] >= 1

        order_queue = balance_order_row.json()["queue"]
        assert order_queue["in_queue"] is True
        assert order_queue["position"] == create_queue["position"]

        order_queue_endpoint = client.get(f"/api/orders/{balance_order['order_id']}/queue")
        assert order_queue_endpoint.status_code == 200
        assert order_queue_endpoint.json()["in_queue"] is True

        # 后台排队看板：应能看到正在打印的订单。
        admin_queue = client.get("/api/admin/print-queue", headers=admin_headers)
        assert admin_queue.status_code == 200, admin_queue.text
        admin_queue_data = admin_queue.json()
        assert admin_queue_data["total"] >= 1
        assert admin_queue_data["printing_count"] >= 1
        assert any(item["id"] == balance_order["order_id"] for item in admin_queue_data["items"])

        # 后台概览应带上正在打印与排队中的统计。
        dashboard_after_balance = client.get("/api/admin/dashboard", headers=admin_headers)
        assert dashboard_after_balance.status_code == 200
        dashboard_totals = dashboard_after_balance.json()["totals"]
        assert dashboard_totals["printing_count"] >= 1
        assert dashboard_totals["queue_count"] >= 1

        # 管理员主动刷新打印状态：不依赖前台刷新即可确认队列状态。
        refresh_status = client.post("/api/admin/orders/refresh-print-status", headers=admin_headers)
        assert refresh_status.status_code == 200, refresh_status.text
        refresh_data = refresh_status.json()
        assert refresh_data["success"] is True
        assert "updated" in refresh_data
        assert refresh_data["queue"]["total"] >= 1

        paid_unpaid_delete = client.delete(f"/api/admin/orders/{balance_order['order_id']}/unpaid", headers=admin_headers)
        assert paid_unpaid_delete.status_code == 422
        assert client.get(f"/api/orders/{balance_order['order_id']}").status_code == 200

        unpaid_delete_order = create_print_order("alipay", "smoke-file-unpaid-delete")
        unpaid_delete = client.delete(f"/api/admin/orders/{unpaid_delete_order['order_id']}/unpaid", headers=admin_headers)
        assert unpaid_delete.status_code == 200, unpaid_delete.text
        assert unpaid_delete.json()["success"] is True
        assert client.get(f"/api/orders/{unpaid_delete_order['order_id']}").status_code == 404
        with connect() as db:
            deleted_payment = db.execute("SELECT id FROM payments WHERE order_id = ?", (unpaid_delete_order["order_id"],)).fetchone()
            deleted_item = db.execute("SELECT id FROM order_items WHERE order_id = ?", (unpaid_delete_order["order_id"],)).fetchone()
            deleted_file = db.execute("SELECT id FROM files WHERE id = 'smoke-file-unpaid-delete'").fetchone()
            assert deleted_payment is None
            assert deleted_item is None
            assert deleted_file is None

        bulk_unpaid_order_1 = create_print_order("alipay", "smoke-file-bulk-unpaid-1")
        bulk_unpaid_order_2 = create_print_order("wxpay", "smoke-file-bulk-unpaid-2")
        expected_bulk_deleted = {
            alipay_order["order_id"],
            wxpay_order["order_id"],
            legacy_epay_order["order_id"],
            coverage_order.json()["order_id"],
            profile_contact_order.json()["order_id"],
            bulk_unpaid_order_1["order_id"],
            bulk_unpaid_order_2["order_id"],
        }
        bulk_unpaid_delete = client.delete("/api/admin/orders/unpaid/bulk", headers=admin_headers)
        assert bulk_unpaid_delete.status_code == 200, bulk_unpaid_delete.text
        bulk_unpaid_data = bulk_unpaid_delete.json()
        assert bulk_unpaid_data["success"] is True
        assert bulk_unpaid_data["deleted"] == len(expected_bulk_deleted)
        assert set(bulk_unpaid_data["deleted_order_ids"]) == expected_bulk_deleted
        for order_id in expected_bulk_deleted:
            assert client.get(f"/api/orders/{order_id}").status_code == 404
        assert client.get(f"/api/orders/{balance_order['order_id']}").status_code == 200

        return_print_order = create_print_order("alipay", "smoke-file-return-print")
        return_payload = build_success_notify_payload(
            return_print_order["order_id"],
            return_print_order["amount"],
            "云打印订单",
            "alipay",
            trade_no="SMOKE_RETURN",
        )
        return_print = client.get(
            f"/api/payment/return/{return_print_order['order_id']}",
            params=return_payload,
            follow_redirects=False,
        )
        assert return_print.status_code == 303
        assert return_print.headers["location"] == f"http://frontend.test/payment/{return_print_order['order_id']}"
        return_print_row = client.get(f"/api/orders/{return_print_order['order_id']}")
        assert return_print_row.status_code == 200
        assert return_print_row.json()["status"] == "printing"
        # mock 打印模式已移除；此处 print_job_id 来自打桩的 print_pdf 固定返回值。
        assert return_print_row.json()["print_job_id"] == "cups-smoke-job"

        recover_print_order = create_print_order("alipay", "smoke-file-recover-print")
        with connect() as db:
            paid_at = "2026-01-01T00:00:00"
            db.execute(
                """
                UPDATE orders
                SET status = 'paid', paid_at = ?, print_job_id = NULL, print_error = NULL, printed_at = NULL
                WHERE id = ?
                """,
                (paid_at, recover_print_order["order_id"]),
            )
            db.execute(
                "UPDATE payments SET status = 'paid', paid_at = ? WHERE order_id = ?",
                (paid_at, recover_print_order["order_id"]),
            )
            db.commit()
        recover_payload = build_success_notify_payload(
            recover_print_order["order_id"],
            recover_print_order["amount"],
            "云打印订单",
            "alipay",
            trade_no="SMOKE_RECOVER",
        )
        recover_notify = client.post("/api/payment/notify", data=recover_payload)
        assert recover_notify.status_code == 200
        recover_print_row = client.get(f"/api/orders/{recover_print_order['order_id']}")
        assert recover_print_row.status_code == 200
        assert recover_print_row.json()["status"] == "printing"
        # mock 打印模式已移除；此处 print_job_id 来自打桩的 print_pdf。
        assert recover_print_row.json()["print_job_id"] == "cups-smoke-job"

        orders_router.print_pdf = original_dispatch_print_pdf

        test_payment = client.post(
            "/api/admin/payment-test",
            headers=admin_headers,
            json={"payment_method": "alipay", "amount": 0.01},
        )
        assert test_payment.status_code == 200, test_payment.text
        test_payment_data = test_payment.json()
        params = test_payment_data["params"]
        assert test_payment_data["payment_url"] == f"/api/payment/submit/{test_payment_data['order_id']}"
        assert params["type"] == "alipay"
        assert params["sign_type"] == "MD5"
        assert params["sign"] == sign_params(params, "smoke-epay-key")
        assert params["notify_url"] == "http://testserver/api/payment/notify"
        assert params["return_url"] == f"http://testserver/api/payment/return/{test_payment_data['order_id']}"
        assert test_payment_data["status"] == "pending"
        assert test_payment_data["payment_status"] == "pending"

        test_payment_status = client.get(
            f"/api/admin/payment-test/{test_payment_data['order_id']}",
            headers=admin_headers,
        )
        assert test_payment_status.status_code == 200
        assert test_payment_status.json()["status"] == "pending"

        regular_order_simulate = client.post(
            f"/api/admin/payment-test/{alipay_order['order_id']}/simulate-success",
            headers=admin_headers,
        )
        assert regular_order_simulate.status_code == 400

        submit = client.get(f"/api/payment/submit/{test_payment_data['order_id']}")
        assert submit.status_code == 200
        assert "正在跳转支付" in submit.text
        assert "继续支付" in submit.text
        assert test_payment_data["order_id"] in submit.text
        assert 'method="post"' in submit.text
        assert 'action="https://pay.example.com/submit.php"' in submit.text
        assert 'name="sign_type" value="MD5"' in submit.text

        payment_return = client.get(f"/api/payment/return/{test_payment_data['order_id']}", follow_redirects=False)
        assert payment_return.status_code == 303
        assert payment_return.headers["location"] == f"http://frontend.test/payment/{test_payment_data['order_id']}"

        mismatch_payment = client.post(
            "/api/admin/payment-test",
            headers=admin_headers,
            json={"payment_method": "wxpay", "amount": 0.01},
        )
        assert mismatch_payment.status_code == 200
        mismatch_payload = dict(mismatch_payment.json()["params"])
        mismatch_payload.update({"trade_no": "SMOKE_MISMATCH", "trade_status": "TRADE_SUCCESS", "money": "0.02"})
        mismatch_payload["sign"] = sign_params(mismatch_payload, "smoke-epay-key")
        mismatch_notify = client.get("/api/payment/notify", params=mismatch_payload)
        assert mismatch_notify.status_code == 400

        simulated_payment = client.post(
            f"/api/admin/payment-test/{mismatch_payment.json()['order_id']}/simulate-success",
            headers=admin_headers,
        )
        assert simulated_payment.status_code == 200, simulated_payment.text
        simulated_payment_data = simulated_payment.json()
        assert simulated_payment_data["status"] == "paid"
        assert simulated_payment_data["payment_status"] == "paid"
        assert simulated_payment_data["epay_trade_no"].startswith("SIM")
        assert simulated_payment_data["params"]["sign"] == sign_params(simulated_payment_data["params"], "smoke-epay-key")

        simulated_order = client.get(f"/api/orders/{mismatch_payment.json()['order_id']}")
        assert simulated_order.status_code == 200
        assert simulated_order.json()["status"] == "paid"
        assert simulated_order.json()["print_job_id"] is None

        bad_signature_payload = dict(params)
        bad_signature_payload.update({"trade_no": "SMOKE_BAD_SIGN", "trade_status": "TRADE_SUCCESS", "sign": "bad-sign"})
        bad_signature_notify = client.get("/api/payment/notify", params=bad_signature_payload)
        assert bad_signature_notify.status_code == 400

        notify_payload = dict(params)
        notify_payload.update({"trade_no": "SMOKE_SUCCESS", "trade_status": "TRADE_SUCCESS"})
        notify_payload["sign"] = sign_params(notify_payload, "smoke-epay-key")
        notify = client.post("/api/payment/notify", data=notify_payload)
        assert notify.status_code == 200
        assert notify.text == "success"

        paid_order = client.get(f"/api/orders/{test_payment_data['order_id']}")
        assert paid_order.status_code == 200
        paid_order_data = paid_order.json()
        assert paid_order_data["status"] == "paid"
        assert paid_order_data["print_job_id"] is None
        assert paid_order_data["printed_at"] is None

        backup_policy = client.put(
            "/api/admin/backups/policy",
            headers=admin_headers,
            json={"enabled": True, "frequency": "weekly", "time": "02:30", "weekday": 1, "retention_count": 3},
        )
        assert backup_policy.status_code == 200, backup_policy.text
        assert backup_policy.json()["enabled"] is True
        assert backup_policy.json()["frequency"] == "weekly"
        backups_before = client.get("/api/admin/backups", headers=admin_headers)
        assert backups_before.status_code == 200, backups_before.text
        assert backups_before.json()["policy"]["retention_count"] == 3

        create_backup = client.post("/api/admin/backups", headers=admin_headers, json={"archive_format": "zip"})
        assert create_backup.status_code == 200, create_backup.text
        backup_data = create_backup.json()
        assert backup_data["filename"].startswith("backup_")
        assert backup_data["filename"].endswith(".zip")
        assert backup_data["data_version"] == "cloud-print-backup-v1"
        assert backup_data["content"]["database"] is True
        backup_download = client.get(f"/api/admin/backups/{backup_data['filename']}/download", headers=admin_headers)
        assert backup_download.status_code == 200, backup_download.text
        backup_bytes = backup_download.content
        assert len(backup_bytes) > 100
        with tempfile.NamedTemporaryFile(suffix=".zip") as backup_file:
            backup_file.write(backup_bytes)
            backup_file.flush()
            with open(backup_file.name, "rb") as upload:
                inspect_backup = client.post(
                    "/api/admin/backups/inspect",
                    headers=admin_headers,
                    files={"file": (backup_data["filename"], upload, "application/zip")},
                )
            assert inspect_backup.status_code == 200, inspect_backup.text
            assert inspect_backup.json()["data_version"] == "cloud-print-backup-v1"
            with open(backup_file.name, "rb") as upload:
                public_restore_inspect = client.post(
                    "/api/setup/restore/inspect",
                    files={"file": (backup_data["filename"], upload, "application/zip")},
                )
            assert public_restore_inspect.status_code == 403, public_restore_inspect.text
            with connect() as db:
                db.execute("UPDATE users SET balance = 1 WHERE id = ?", (user_id,))
                db.commit()
            changed_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert changed_me.status_code == 200
            assert changed_me.json()["balance"] == 1
            with open(backup_file.name, "rb") as upload:
                restore_backup = client.post(
                    "/api/admin/backups/restore",
                    headers=admin_headers,
                    files={"file": (backup_data["filename"], upload, "application/zip")},
                )
            assert restore_backup.status_code == 200, restore_backup.text
            restored_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert restored_me.status_code == 200
            assert restored_me.json()["balance"] == 34.5
        delete_backup = client.delete(f"/api/admin/backups/{backup_data['filename']}", headers=admin_headers)
        assert delete_backup.status_code == 200, delete_backup.text

    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(b"not a pdf")
        handle.flush()
        try:
            validate_file_signature(Path(handle.name), ".pdf")
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("invalid PDF signature should be rejected")

    # OLE 公式（MathType/公式3.0）预览图探测：有预览图=可打印(无风险)，无预览图=高风险。
    def _make_docx(entries: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        with zipfile.ZipFile(tmp.name, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return Path(tmp.name)

    with_preview = _make_docx(
        {
            "word/document.xml": b"<w:document/>",
            "word/embeddings/oleObject1.bin": b"\x00" * 16,
            "word/media/image1.wmf": b"\xd7\xcd\xc6\x9a",  # 任意 WMF 占位内容
        }
    )
    risk_ok = inspect_ole_formula_risk(with_preview)
    assert risk_ok["ole_objects"] == 1 and risk_ok["preview_images"] == 1 and risk_ok["at_risk"] is False
    with_preview.unlink(missing_ok=True)

    no_preview = _make_docx(
        {
            "word/document.xml": b"<w:document/>",
            "word/embeddings/oleObject1.bin": b"\x00" * 16,
        }
    )
    risk_bad = inspect_ole_formula_risk(no_preview)
    assert risk_bad["ole_objects"] == 1 and risk_bad["preview_images"] == 0 and risk_bad["at_risk"] is True
    no_preview.unlink(missing_ok=True)

    # 拍平图像软遮罩(SMask)：LibreOffice 转 PDF 会给公式/透明图加 SMask，CUPS 光栅化
    # 支持差会整块丢弃，导致「预览正常、打印后化学式消失」。flatten 应把带 SMask 的
    # 图像合成到白底、去遮罩，普通 PDF 不改动。此处合成一个带 SMask 的最小 PDF 验证。
    def _make_pdf_with_smask() -> Path:
        from PyPDF2 import PdfWriter
        from PyPDF2.generic import (
            ArrayObject,
            DecodedStreamObject,
            DictionaryObject,
            FloatObject,
            NameObject,
            NumberObject,
        )

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        page = writer.pages[0]

        # 半透明的软遮罩：128 灰阶 alpha，触发 /SMask 分支。
        # 用未压缩原始像素流（不设 /Filter），确保 get_data() 能原样读回。
        smask = DecodedStreamObject()
        smask.set_data(bytes([128]))
        smask.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        })
        smask_ref = writer._add_object(smask)

        image = DecodedStreamObject()
        image.set_data(bytes([10, 20, 30]))  # 1x1 RGB 深色像素
        image.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
            NameObject("/SMask"): smask_ref,
        })
        image_ref = writer._add_object(image)

        xobjects = DictionaryObject({NameObject("/Im0"): image_ref})
        resources = DictionaryObject({NameObject("/XObject"): xobjects})
        page[NameObject("/Resources")] = resources

        content = DecodedStreamObject()
        content.set_data(b"q 100 0 0 100 50 50 cm /Im0 Do Q")
        page[NameObject("/Contents")] = writer._add_object(content)

        out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        with open(out.name, "wb") as fh:
            writer.write(fh)
        return Path(out.name)

    smask_pdf = _make_pdf_with_smask()
    try:
        raw_before = smask_pdf.read_bytes()
        assert b"/SMask" in raw_before, "构造的测试 PDF 应含 /SMask"
        changed = flatten_pdf_smask(smask_pdf)
        assert changed is True, "带 SMask 的 PDF 应被拍平改写"
        assert b"/SMask" not in smask_pdf.read_bytes(), "拍平后不应再残留 /SMask"
        # 已拍平的 PDF 再次处理应返回 False（不做无谓改写）
        assert flatten_pdf_smask(smask_pdf) is False, "无 SMask 的 PDF 不应被改写"
    finally:
        smask_pdf.unlink(missing_ok=True)

    # 打印前整页光栅化：真实打印是把 PDF 提交给（通常远端的）CUPS，由那台机器的 RIP
    # 光栅化，老式公式/透明图元可能被整块丢弃，导致「预览正常、上传打印后化学式消失」。
    # rasterize_pdf_for_print 在提交打印前把每页转成不透明位图重组为纯图像 PDF，规避远端
    # RIP 的一切兼容性差异。此处用一个含彩色矩形的两页 PDF 验证：产出存在、页数一致、纯
    # 图像（无字体、无 SMask）；缺 pdftoppm 时安全降级返回 None，不做断言失败。
    def _make_two_page_pdf() -> Path:
        from PyPDF2 import PdfWriter
        from PyPDF2.generic import DecodedStreamObject, NameObject

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_blank_page(width=200, height=200)
        # 第一页画一个填充矩形，确保光栅化后有可见内容（不是全白页）。
        page = writer.pages[0]
        content = DecodedStreamObject()
        content.set_data(b"0 0 0 rg 20 20 160 160 re f")
        page[NameObject("/Contents")] = writer._add_object(content)
        out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        with open(out.name, "wb") as fh:
            writer.write(fh)
        return Path(out.name)

    src_pdf = _make_two_page_pdf()
    raster_pdf = None
    try:
        raster_pdf = rasterize_pdf_for_print(src_pdf, dpi=72)
        if raster_pdf is not None:
            from PyPDF2 import PdfReader

            # 有 poppler：校验产出为纯图像 PDF 且页数一致。
            assert raster_pdf.exists(), "光栅化应产出打印用 PDF"
            raster_bytes = raster_pdf.read_bytes()
            assert b"/SMask" not in raster_bytes, "光栅化后不应残留 /SMask"
            assert b"/Font" not in raster_bytes, "纯图像 PDF 不应含字体"
            reader = PdfReader(str(raster_pdf))
            assert len(reader.pages) == 2, "光栅化后页数必须与原 PDF 一致"
    finally:
        src_pdf.unlink(missing_ok=True)
        if raster_pdf is not None:
            raster_pdf.unlink(missing_ok=True)

    # 加深偏灰内容：老式 OLE/WMF 公式光栅化后笔画常是中灰，打印会「颜色很淡」。
    # _darken_faint_content 用分段 LUT 把中灰压黑、保护白底。此处直接验证 LUT 行为：
    # 中灰(如 120)必须变黑；纯黑保持黑；接近白(如 250)保持不变，避免整页发灰。
    from app.services.pdf_postprocess import _darken_faint_content
    from PIL import Image

    probe = Image.new("RGB", (3, 1), (0, 0, 0))
    probe.putpixel((0, 0), (0, 0, 0))       # 纯黑（正文）
    probe.putpixel((1, 0), (120, 120, 120))  # 中灰（公式笔画）
    probe.putpixel((2, 0), (250, 250, 250))  # 接近白（纸张背景）
    darkened = _darken_faint_content(probe)
    assert darkened.getpixel((0, 0)) == (0, 0, 0), "纯黑应保持纯黑"
    assert darkened.getpixel((1, 0)) == (0, 0, 0), "中灰公式笔画应被压到纯黑"
    assert darkened.getpixel((2, 0)) == (250, 250, 250), "接近白的背景应保持不变，避免整页发灰"

    # —— 唯一配置文件 config/config.json：生成、热加载、环境变量优先级 ——
    # 第一次部署时 config 目录里什么都没有，ensure_config_file() 必须生成一份完整、
    # 可直接编辑的 JSON（含随机 app_secret），且不再依赖任何 .env 文件。
    bootstrap_root = tempfile.mkdtemp(prefix="cloud-print-config-")
    bootstrap_file = Path(bootstrap_root) / "config.json"
    assert ensure_config_file(bootstrap_file) == bootstrap_file
    raw_config = json.loads(bootstrap_file.read_text(encoding="utf-8"))
    assert raw_config["database_path"] == "cloud_print.db", "生成的默认值应是基于 config 目录的相对路径"
    assert len(raw_config["app_secret"]) == 64, "生成时必须写入随机 app_secret，不能用 change-me 占位值"
    assert raw_config["reset_admin_password"] is False
    assert "print_mode" not in raw_config, "已移除的打印模式配置不应再出现在配置文件中"
    # 已存在的配置文件绝不能被覆盖（用户的编辑必须保留）。
    raw_config["cups_server"] = "10.0.0.9:631"
    bootstrap_file.write_text(json.dumps(raw_config, ensure_ascii=False), encoding="utf-8")
    ensure_config_file(bootstrap_file)
    assert json.loads(bootstrap_file.read_text(encoding="utf-8"))["cups_server"] == "10.0.0.9:631"

    original_config_env = os.environ.get("CONFIG_CONFIG_FILE")
    try:
        os.environ["CONFIG_CONFIG_FILE"] = str(bootstrap_file)
        boot_settings = reload_settings()
        assert boot_settings.config_file == bootstrap_file
        assert str(boot_settings.database_path) == str(Path(bootstrap_root) / "cloud_print.db"), boot_settings.database_path
        assert str(boot_settings.upload_dir) == str(Path(bootstrap_root) / "uploads"), boot_settings.upload_dir
        # 改完文件不需要重启：get_settings() 依据 mtime/大小自动重载。
        raw_config["rate_limit_requests"] = 999
        bootstrap_file.write_text(json.dumps(raw_config, ensure_ascii=False, indent=2), encoding="utf-8")
        assert get_settings().rate_limit_requests == 999, "修改 config.json 后 get_settings() 必须自动重载"
        # 进程环境变量仍然是最高优先级（测试与特殊部署依赖这一点）。
        env_db = str(Path(bootstrap_root) / "from-env.db")
        os.environ["DATABASE_PATH"] = env_db
        assert str(reload_settings().database_path) == env_db, "环境变量必须优先于 config.json"
        del os.environ["DATABASE_PATH"]
    finally:
        if original_config_env is None:
            os.environ.pop("CONFIG_CONFIG_FILE", None)
        else:
            os.environ["CONFIG_CONFIG_FILE"] = original_config_env
        restored = reload_settings()
        assert restored.config_file == _CONFIG_PATH, restored.config_file
        assert str(restored.database_path) == str(Path(_tmpdir.name) / "cloud_print.db"), restored.database_path

    # —— 忘记管理员密码：config.json 里置 reset_admin_password=true，重启后重置一次并自动写回 false ——
    reset_root = tempfile.mkdtemp(prefix="cloud-print-reset-")
    reset_file = Path(reset_root) / "config.json"
    reset_file.write_text(
        json.dumps(
            {
                "database_path": str(Path(reset_root) / "reset.db"),
                "admin_username": "resetadmin",
                "admin_password": "temp-password-1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    original_config_env = os.environ.get("CONFIG_CONFIG_FILE")
    try:
        os.environ["CONFIG_CONFIG_FILE"] = str(reset_file)
        reload_settings()
        init_db()
        with connect() as reset_db:
            first = reset_db.execute("SELECT password_hash FROM users WHERE username = 'resetadmin'").fetchone()
        assert first is not None, "init_db 必须按 config.json 里的管理员账号建号"
        raw_reset = json.loads(reset_file.read_text(encoding="utf-8"))
        raw_reset["admin_password"] = "temp-password-2"
        raw_reset["reset_admin_password"] = True
        reset_file.write_text(json.dumps(raw_reset, ensure_ascii=False, indent=2), encoding="utf-8")
        reload_settings()
        init_db()
        with connect() as reset_db:
            second = reset_db.execute("SELECT password_hash FROM users WHERE username = 'resetadmin'").fetchone()
        assert second["password_hash"] != first["password_hash"], "reset_admin_password=true 时必须重置管理员密码"
        assert json.loads(reset_file.read_text(encoding="utf-8"))["reset_admin_password"] is False, (
            "重置成功后必须把开关写回 false，避免每次启动覆盖后台改过的密码"
        )
        # 再启动一次不再重置：后台改过的密码必须保留。
        reload_settings()
        init_db()
        with connect() as reset_db:
            third = reset_db.execute("SELECT password_hash FROM users WHERE username = 'resetadmin'").fetchone()
        assert third["password_hash"] == second["password_hash"], "开关写回 false 后不得再次重置"
    finally:
        if original_config_env is None:
            os.environ.pop("CONFIG_CONFIG_FILE", None)
        else:
            os.environ["CONFIG_CONFIG_FILE"] = original_config_env
        reload_settings()

    print("smoke tests passed")


if __name__ == "__main__":
    main()
