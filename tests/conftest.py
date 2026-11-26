from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import create_app
from app.db import get_db
from app.models import PolicyType, Role, Student
from app.repositories import (
    ActivityRepository,
    MessageRepository,
    OutboxRepository,
    RegistrationRepository,
    StudentRepository,
)
from app.services import ActivityService, RegistrationService


def future(days: int = 3) -> datetime:
    return (datetime.now() + timedelta(days=days)).replace(microsecond=0)


def past(days: int = 1) -> datetime:
    return (datetime.now() - timedelta(days=days)).replace(microsecond=0)


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "DATABASE": str(tmp_path / "test.sqlite3"),
            "TESTING": True,
            "SECRET_KEY": "test-secret",
        }
    )
    with application.app_context():
        conn = get_db()
        repo = StudentRepository(conn)
        repo.create(Student("admin", "李老师", Role.ADMIN), "admin123")
        for student_id, name in (("s1", "张三"), ("s2", "李四"), ("s3", "王五"), ("s4", "赵六")):
            repo.create(Student(student_id, name), "123456")
        conn.commit()
    return application


@pytest.fixture
def ctx(app):
    with app.app_context():
        conn = get_db()
        yield SimpleNamespace(
            conn=conn,
            students=StudentRepository(conn),
            activities=ActivityRepository(conn),
            registrations=RegistrationRepository(conn),
            messages=MessageRepository(conn),
            outbox=OutboxRepository(conn),
            activity_service=ActivityService(conn),
            service=RegistrationService(conn),
        )


@pytest.fixture
def add_activity(ctx):
    def _add(
        title: str = "测试活动",
        capacity: int = 2,
        policy: PolicyType | str = PolicyType.DIRECT,
        start_at=None,
        category: str = "测试",
    ):
        result = ctx.activity_service.create(
            title=title,
            category=category,
            start_at=start_at or future(3),
            location="教学楼 101",
            capacity=capacity,
            policy_type=policy,
        )
        assert result.ok, result.message
        return ctx.activities.get(result.data)

    return _add


@pytest.fixture
def clock():
    """时间工具：避免在测试里重复写 timedelta 计算。"""
    return SimpleNamespace(future=future, past=past)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(client):
    def _login(student_id: str = "s1", password: str = "123456"):
        return client.post(
            "/login",
            data={"student_id": student_id, "password": password},
            follow_redirects=True,
        )

    return _login
