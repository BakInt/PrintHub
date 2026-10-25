"""cert 模块自持 schema：cert_templates / cert_docs 建表与内置数据播种。

幂等：`CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE`（按 code 唯一冲突忽略），
旧库升级自动补建；每次启动把内置模板的 name/layout_json/sort 从代码同步进库，
但**不覆盖**后台改过的 price/enabled（P0 代码是版式的唯一事实来源，价格与启停归后台）。

主程序挂接点：`database.init_db()` 里一行 `cert.ensure_schema(connection)`（隔离钩子）。
"""

import sqlite3

from .templates_seed import CERT_SETTINGS_DEFAULTS, template_seed_rows

CERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS cert_templates (
    id TEXT PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    layout_json TEXT NOT NULL,
    price REAL,
    enabled INTEGER DEFAULT 1,
    sort INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cert_docs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    template_code TEXT NOT NULL,
    pdf_file_id TEXT NOT NULL,
    page_count INTEGER DEFAULT 1,
    used_manual_crop INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (pdf_file_id) REFERENCES files(id)
);

CREATE INDEX IF NOT EXISTS idx_cert_docs_user ON cert_docs(user_id);
CREATE INDEX IF NOT EXISTS idx_cert_docs_file ON cert_docs(pdf_file_id);
CREATE INDEX IF NOT EXISTS idx_cert_docs_expires ON cert_docs(expires_at);
"""


def ensure_schema(db: sqlite3.Connection) -> None:
    """建表 + 播种内置模板与设置键。幂等，可重复执行。"""
    db.executescript(CERT_SCHEMA)
    seed_rows = template_seed_rows()
    for row in seed_rows:
        db.execute(
            "INSERT OR IGNORE INTO cert_templates (id, code, name, layout_json, enabled, sort) VALUES (?, ?, ?, ?, 1, ?)",
            (f"seed-{row['code']}", row["code"], row["name"], row["layout_json"], row["sort"]),
        )
        # 版式/名称/排序随代码发布同步；price/enabled 是后台运营数据，保持库里的值。
        db.execute(
            "UPDATE cert_templates SET name = ?, layout_json = ?, sort = ?, updated_at = CURRENT_TIMESTAMP WHERE code = ?",
            (row["name"], row["layout_json"], row["sort"], row["code"]),
        )
    # 内置模板随代码增删：已从种子里移除的内置模板一并下架删除（P0 没有后台自建模板，
    # 该清理只会命中被新版本废弃的内置项；历史生成件按 cert_docs 冗余 code 正常展示）。
    placeholders = ",".join("?" for _ in seed_rows)
    db.execute(
        f"DELETE FROM cert_templates WHERE code NOT IN ({placeholders})",
        [row["code"] for row in seed_rows],
    )
    for key, value in CERT_SETTINGS_DEFAULTS.items():
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
