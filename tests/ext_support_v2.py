"""变更测试的公共构造工具 v2。

只放普通函数，不放 pytest fixture：fixture 必须在 ``conftest.py`` 或测试
模块内定义才能被收集，而 ``conftest.py`` 是恢复原文件、不作改动的。
各测试文件用三行 fixture 包一层即可，重复成本可接受。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db import get_db
from app.models import Role, Student
from app.repositories import StudentRepository
from ext_v2.factory_v2 import create_ext_app
from ext_v2.services_v2 import GradeAwareActivityService

#: 与 ``tests/conftest.py`` 对齐的测试账号。
ACCOUNTS = (
    ("admin", "李老师", Role.ADMIN),
    ("s1", "张三", Role.STUDENT),
    ("s2", "李四", Role.STUDENT),
    ("s3", "王五", Role.STUDENT),
    ("s4", "赵六", Role.STUDENT),
)


def future(days: int = 3) -> datetime:
    return (datetime.now() + timedelta(days=days)).replace(microsecond=0)


def past(days: int = 1) -> datetime:
    return (datetime.now() - timedelta(days=days)).replace(microsecond=0)


def make_ext_app(tmp_path):
    """创建带扩展装配的测试应用，并播种测试账号。"""
    app = create_ext_app(
        {
            "DATABASE": str(tmp_path / "ext_test.sqlite3"),
            "TESTING": True,
            "SECRET_KEY": "test-secret",
        }
    )
    with app.app_context():
        conn = get_db()
        repo = StudentRepository(conn)
        for student_id, name, role in ACCOUNTS:
            repo.create(Student(student_id, name, role), "123456")
        conn.commit()
    return app


def set_grades(conn, mapping: dict[str, int]) -> None:
    """批量登记年级。"""
    for student_id, grade in mapping.items():
        conn.execute(
            "UPDATE student SET grade = ? WHERE student_id = ?", (grade, student_id)
        )
    conn.commit()


def make_activity(
    conn,
    *,
    title: str = "年级限定活动",
    capacity: int = 3,
    policy: str = "DIRECT",
    grade_limit="2,3",
    start_at=None,
):
    """创建一个（可带年级限定的）活动，返回 activity_id。"""
    result = GradeAwareActivityService(conn).create_limited(
        title=title,
        category="测试",
        start_at=start_at or future(3),
        location="教学楼 101",
        capacity=capacity,
        policy_type=policy,
        grade_limit=grade_limit,
    )
    assert result.ok, result.message
    return result.data
