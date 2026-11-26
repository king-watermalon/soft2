"""扩展层数据库迁移 v2：只做"加列 / 加表"，不改动 ``app/db.py`` 的建表脚本。

三条迁移纪律
------------
1. **幂等**：重复执行不报错、不丢数据，可以安全地挂在每次启动上。
2. **只增不改**：不 ``DROP``、不重建表、不改既有列的类型与约束。
   —— ``activity.policy_type`` 上的 ``CHECK IN ('DIRECT','REVIEW','LOTTERY')``
   因此保持原样，这也是 CR-01 不新增策略类型、改用"可组合准入规则"的直接原因。
3. **与原有建表脚本正交**：``app.db.init_db()`` 独立运行时只建基础表，
   本模块随后补列；两者顺序无关，谁先跑都能收敛到同一结构。

新库与旧库都能用
----------------
* 新库：``init_db()`` 建出无 ``grade`` 列的 ``student``，本模块补上。
* 旧库：已经存有学生与报名数据，``ALTER TABLE ... ADD COLUMN`` 只追加
  可空列，历史行取 ``NULL``，不需要回填也不破坏外键。
"""

from __future__ import annotations

import sqlite3

#: CR-01：学生年级。1—4 对应大一到大四；NULL 表示"尚未登记"。
STUDENT_GRADE_COLUMN = ("grade", "INTEGER")

#: CR-01：活动年级限定，形如 ``"2,3"``；NULL/空串表示不限定年级。
ACTIVITY_GRADE_LIMIT_COLUMN = ("grade_limit", "TEXT")

#: CR-02：模拟邮件投递流水。
#:
#: 与既有 ``email_outbox`` 的分工：``email_outbox`` 是上一轮变更留下的
#: "待发队列"（只入队、无投递结果），本表记录的是**实际投递结果**
#: （成功/失败、错误原因、尝试时间），对应材料 CR-02 的"记录收件人、
#: 主题、内容、状态与时间"。
EMAIL_DELIVERY_DDL = """
CREATE TABLE IF NOT EXISTS email_delivery (
    delivery_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL,
    student_id   TEXT NOT NULL,
    address      TEXT NOT NULL,
    subject      TEXT NOT NULL,
    body         TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('SENT', 'FAILED')),
    error        TEXT,
    attempted_at TEXT NOT NULL,
    UNIQUE (event_id, address)
);

CREATE INDEX IF NOT EXISTS ix_email_delivery_student
    ON email_delivery(student_id);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def add_column(
    conn: sqlite3.Connection, table: str, column: str, ddl_type: str
) -> bool:
    """幂等地加一列。返回 ``True`` 表示本次真的加了。"""
    if column in _columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
    return True


def migrate(conn: sqlite3.Connection) -> dict[str, object]:
    """执行全部扩展迁移，返回本次实际发生的动作（便于日志与文档留证）。"""
    changes: dict[str, object] = {"columns_added": [], "tables_created": []}

    for table, (column, ddl_type) in (
        ("student", STUDENT_GRADE_COLUMN),
        ("activity", ACTIVITY_GRADE_LIMIT_COLUMN),
    ):
        if add_column(conn, table, column, ddl_type):
            changes["columns_added"].append(f"{table}.{column}")

    existed = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='email_delivery'"
    ).fetchone()
    conn.executescript(EMAIL_DELIVERY_DDL)
    if existed is None:
        changes["tables_created"].append("email_delivery")

    conn.commit()
    return changes


def is_migrated(conn: sqlite3.Connection) -> bool:
    """可选的自检：扩展需要的列与表是否齐备。"""
    return (
        STUDENT_GRADE_COLUMN[0] in _columns(conn, "student")
        and ACTIVITY_GRADE_LIMIT_COLUMN[0] in _columns(conn, "activity")
        and conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='email_delivery'"
        ).fetchone()
        is not None
    )
