"""SQLite 连接管理与建表脚本。

设计要点：重复有效报名的最终防线放在数据库层（部分唯一索引），
应用层的查重只是"友好提示"，不是正确性保证。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS student (
    student_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'STUDENT' CHECK (role IN ('STUDENT', 'ADMIN')),
    password   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS activity (
    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    start_at    TEXT NOT NULL,
    location    TEXT NOT NULL DEFAULT '',
    capacity    INTEGER NOT NULL CHECK (capacity > 0),
    policy_type TEXT NOT NULL CHECK (policy_type IN ('DIRECT', 'REVIEW')),
    status      TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registration (
    registration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id     INTEGER NOT NULL REFERENCES activity(activity_id),
    student_id      TEXT NOT NULL REFERENCES student(student_id),
    status          TEXT NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_active_registration
    ON registration(activity_id, student_id)
    WHERE status IN ('PENDING', 'APPROVED');

CREATE INDEX IF NOT EXISTS ix_registration_activity ON registration(activity_id);
CREATE INDEX IF NOT EXISTS ix_registration_student ON registration(student_id);

CREATE TABLE IF NOT EXISTS message (
    message_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL,
    student_id  TEXT NOT NULL REFERENCES student(student_id),
    activity_id INTEGER,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    is_read     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (event_id, student_id)
);

CREATE TABLE IF NOT EXISTS notify_outbox (
    outbox_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL,
    listener    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('SENT', 'FAILED')),
    error       TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    UNIQUE (event_id, listener)
);
"""


def connect(database_path: str) -> sqlite3.Connection:
    """打开连接。:memory: 之外的路径会自动创建父目录。"""
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    """请求级连接，存放于 flask.g，请求结束自动关闭。"""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(exc: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
