"""仓储层：所有 SQL 集中在这里，领域服务不直接写 SQL。

设计意图（信息专家原则）：谁知道数据，谁负责查询与持久化。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from .models import (
    Activity,
    ActivityStatistics,
    ActivityStatus,
    Message,
    PolicyType,
    Registration,
    RegistrationStatus,
    Role,
    Student,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


class StudentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, student_id: str) -> Optional[Student]:
        row = self.conn.execute(
            "SELECT * FROM student WHERE student_id = ?", (student_id,)
        ).fetchone()
        return self._to_model(row) if row else None

    def list_all(self) -> list[Student]:
        rows = self.conn.execute(
            "SELECT * FROM student ORDER BY student_id"
        ).fetchall()
        return [self._to_model(r) for r in rows]

    def authenticate(self, student_id: str, password: str) -> Optional[Student]:
        student = self.get(student_id)
        if student is None:
            return None
        row = self.conn.execute(
            "SELECT password FROM student WHERE student_id = ?", (student_id,)
        ).fetchone()
        return student if row and row["password"] == password else None

    def create(self, student: Student, password: str) -> None:
        self.conn.execute(
            "INSERT INTO student (student_id, name, role, password) VALUES (?, ?, ?, ?)",
            (student.student_id, student.name, student.role.value, password),
        )

    @staticmethod
    def _to_model(row: sqlite3.Row) -> Student:
        return Student(
            student_id=row["student_id"],
            name=row["name"],
            role=Role(row["role"]),
        )


class ActivityRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, activity_id: int) -> Optional[Activity]:
        row = self.conn.execute(
            "SELECT * FROM activity WHERE activity_id = ?", (activity_id,)
        ).fetchone()
        return self._to_model(row) if row else None

    def list_all(self, keyword: str = "") -> list[Activity]:
        sql = "SELECT * FROM activity"
        params: tuple = ()
        if keyword:
            sql += " WHERE title LIKE ?"
            params = (f"%{keyword}%",)
        sql += " ORDER BY start_at, activity_id"
        return [self._to_model(r) for r in self.conn.execute(sql, params).fetchall()]

    def create(
        self,
        title: str,
        category: str,
        start_at: datetime,
        location: str,
        capacity: int,
        policy_type: PolicyType,
        created_at: datetime,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO activity
               (title, category, start_at, location, capacity, policy_type, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)""",
            (
                title,
                category,
                _iso(start_at),
                location,
                capacity,
                policy_type.value,
                _iso(created_at),
            ),
        )
        return int(cur.lastrowid)

    def update(
        self,
        activity_id: int,
        title: str,
        category: str,
        start_at: datetime,
        location: str,
        capacity: int,
        policy_type: PolicyType,
    ) -> None:
        self.conn.execute(
            """UPDATE activity
               SET title = ?, category = ?, start_at = ?, location = ?,
                   capacity = ?, policy_type = ?
               WHERE activity_id = ?""",
            (
                title,
                category,
                _iso(start_at),
                location,
                capacity,
                policy_type.value,
                activity_id,
            ),
        )

    def delete(self, activity_id: int) -> None:
        self.conn.execute(
            "DELETE FROM activity WHERE activity_id = ?", (activity_id,)
        )

    def set_status(self, activity_id: int, status: ActivityStatus) -> None:
        self.conn.execute(
            "UPDATE activity SET status = ? WHERE activity_id = ?",
            (status.value, activity_id),
        )

    def registration_count(self, activity_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM registration WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        return int(row["c"])

    @staticmethod
    def _to_model(row: sqlite3.Row) -> Activity:
        return Activity(
            activity_id=row["activity_id"],
            title=row["title"],
            category=row["category"],
            start_at=_dt(row["start_at"]),
            location=row["location"],
            capacity=row["capacity"],
            policy_type=PolicyType(row["policy_type"]),
            status=ActivityStatus(row["status"]),
            created_at=_dt(row["created_at"]),
        )


class RegistrationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, registration_id: int) -> Optional[Registration]:
        row = self.conn.execute(
            "SELECT * FROM registration WHERE registration_id = ?",
            (registration_id,),
        ).fetchone()
        return self._to_model(row) if row else None

    def find_active(self, activity_id: int, student_id: str) -> Optional[Registration]:
        row = self.conn.execute(
            """SELECT * FROM registration
               WHERE activity_id = ? AND student_id = ?
                 AND status IN ('PENDING', 'APPROVED')""",
            (activity_id, student_id),
        ).fetchone()
        return self._to_model(row) if row else None

    def list_by_activity(
        self, activity_id: int, status: Optional[RegistrationStatus] = None
    ) -> list[Registration]:
        sql = "SELECT * FROM registration WHERE activity_id = ?"
        params: list = [activity_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY registration_id"
        return [
            self._to_model(r) for r in self.conn.execute(sql, tuple(params)).fetchall()
        ]

    def list_by_student(self, student_id: str) -> list[Registration]:
        rows = self.conn.execute(
            "SELECT * FROM registration WHERE student_id = ? ORDER BY registration_id DESC",
            (student_id,),
        ).fetchall()
        return [self._to_model(r) for r in rows]

    def count_by_status(self, activity_id: int, status: RegistrationStatus) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM registration WHERE activity_id = ? AND status = ?",
            (activity_id, status.value),
        ).fetchone()
        return int(row["c"])

    def insert(
        self,
        activity_id: int,
        student_id: str,
        status: RegistrationStatus,
        now: datetime,
    ) -> Registration:
        cur = self.conn.execute(
            """INSERT INTO registration (activity_id, student_id, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (activity_id, student_id, status.value, _iso(now), _iso(now)),
        )
        return Registration(
            registration_id=int(cur.lastrowid),
            activity_id=activity_id,
            student_id=student_id,
            status=status,
            created_at=now,
            updated_at=now,
        )

    def update_status(
        self, registration_id: int, status: RegistrationStatus, now: datetime
    ) -> None:
        self.conn.execute(
            "UPDATE registration SET status = ?, updated_at = ? WHERE registration_id = ?",
            (status.value, _iso(now), registration_id),
        )

    def statistics(self, activity_id: int, capacity: int) -> ActivityStatistics:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS c FROM registration WHERE activity_id = ? GROUP BY status",
            (activity_id,),
        ).fetchall()
        counts = {r["status"]: int(r["c"]) for r in rows}
        return ActivityStatistics(
            activity_id=activity_id,
            capacity=capacity,
            approved=counts.get("APPROVED", 0),
            pending=counts.get("PENDING", 0),
            rejected=counts.get("REJECTED", 0),
            cancelled=counts.get("CANCELLED", 0),
        )

    @staticmethod
    def _to_model(row: sqlite3.Row) -> Registration:
        return Registration(
            registration_id=row["registration_id"],
            activity_id=row["activity_id"],
            student_id=row["student_id"],
            status=RegistrationStatus(row["status"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )


class MessageRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(
        self,
        event_id: str,
        student_id: str,
        activity_id: Optional[int],
        content: str,
        now: datetime,
    ) -> None:
        """INSERT OR IGNORE + UNIQUE(event_id, student_id) 实现通知幂等。"""
        self.conn.execute(
            """INSERT OR IGNORE INTO message
               (event_id, student_id, activity_id, content, created_at, is_read)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (event_id, student_id, activity_id, content, _iso(now)),
        )

    def list_by_student(self, student_id: str, limit: int = 50) -> list[Message]:
        rows = self.conn.execute(
            "SELECT * FROM message WHERE student_id = ? ORDER BY message_id DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
        return [self._to_model(r) for r in rows]

    def count_unread(self, student_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM message WHERE student_id = ? AND is_read = 0",
            (student_id,),
        ).fetchone()
        return int(row["c"])

    def mark_all_read(self, student_id: str) -> None:
        self.conn.execute(
            "UPDATE message SET is_read = 1 WHERE student_id = ? AND is_read = 0",
            (student_id,),
        )

    @staticmethod
    def _to_model(row: sqlite3.Row) -> Message:
        return Message(
            message_id=row["message_id"],
            student_id=row["student_id"],
            activity_id=row["activity_id"],
            content=row["content"],
            created_at=_dt(row["created_at"]),
            is_read=bool(row["is_read"]),
        )


class OutboxRepository:
    """通知投递流水，用于"失败留痕"与幂等。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def record(
        self, event_id: str, listener: str, status: str, error: Optional[str], now: datetime
    ) -> None:
        self.conn.execute(
            """INSERT INTO notify_outbox (event_id, listener, status, error, retry_count, created_at)
               VALUES (?, ?, ?, ?, 0, ?)
               ON CONFLICT(event_id, listener) DO UPDATE SET
                   status = excluded.status,
                   error = excluded.error,
                   retry_count = retry_count + 1""",
            (event_id, listener, status, error, _iso(now)),
        )
        self.conn.commit()

    def list_by_event(self, event_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM notify_outbox WHERE event_id = ?", (event_id,)
        ).fetchall()

    def failed(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM notify_outbox WHERE status = 'FAILED' ORDER BY outbox_id"
        ).fetchall()
