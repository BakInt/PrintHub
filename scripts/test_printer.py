#!/usr/bin/env python3
"""Send a CUPS test page and record manual confirmation."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, env=env)


def test_pdf_bytes() -> bytes:
    content = b"BT /F1 18 Tf 72 760 Td (Cloud Print test page) Tj 0 -30 Td (Docker CUPS check.) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return bytes(pdf)


def extract_job_id(output: str) -> str:
    match = re.search(r"request id is\s+(\S+)", output)
    return match.group(1) if match else output.strip()


def normalize_confirmation(value: str) -> tuple[str, bool]:
    normalized = value.strip().lower()
    if normalized in {"是", "成功", "yes", "y", "ok"}:
        return "success", True
    if normalized in {"部分成功", "部分", "partial", "partly"}:
        return "partial_success", True
    if normalized in {"否", "失败", "未成功", "no", "n", "fail", "failed"}:
        return "failed", False
    return "unknown", False


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test page through CUPS and ask for manual confirmation.")
    parser.add_argument("printer", help="CUPS queue name")
    parser.add_argument("--copies", type=int, default=1)
    parser.add_argument("--result-log", default="storage/printer_test_results.jsonl")
    args = parser.parse_args()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(test_pdf_bytes())
        pdf_path = Path(handle.name)

    try:
        command = ["lp", "-d", args.printer, "-n", str(max(args.copies, 1)), str(pdf_path)]
        result = run(command)
        if result.returncode != 0:
            print(f"打印任务提交失败：{(result.stderr or result.stdout).strip()}")
            return result.returncode
        job_id = extract_job_id(result.stdout)
        print(f"测试页已发送到 {args.printer}，任务号：{job_id}")
        answer = input("样张是否打印成功？（是/否/部分成功）").strip()
        outcome, success = normalize_confirmation(answer)
        record = {
            "printer": args.printer,
            "job_id": job_id,
            "outcome": outcome,
            "success": success,
            "answer": answer,
            "created_at": datetime.now(UTC).isoformat(),
            "cups_server": os.environ.get("CUPS_SERVER", ""),
        }
        log_path = Path(args.result_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0 if outcome in {"success", "partial_success"} else 2
    finally:
        pdf_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
