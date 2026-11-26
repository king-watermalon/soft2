"""演示数据初始化。

用法：python seed.py
注意：会删除并重建 instance/campusevent.sqlite3。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from app import create_app
from app.db import connect, get_db, init_db
from app.models import Role, Student
from app.repositories import StudentRepository
from app.services import ActivityService, RegistrationService

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 与 create_app 的 DATABASE_PATH 约定保持一致，便于部署时把库放到代码目录之外
DB_PATH = os.environ.get("DATABASE_PATH") or os.path.join(
    BASE_DIR, "instance", "campusevent.sqlite3"
)

ACCOUNTS = [
    ("admin", "辅导员李老师", Role.ADMIN, "admin123"),
    ("student1", "张三", Role.STUDENT, "123456"),
    ("student2", "李四", Role.STUDENT, "123456"),
    ("student3", "王五", Role.STUDENT, "123456"),
]


def reset_database() -> None:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = connect(DB_PATH)
    init_db(conn)
    conn.close()


def main() -> None:
    reset_database()
    app = create_app({"DATABASE": DB_PATH})

    with app.app_context():
        conn = get_db()
        students = StudentRepository(conn)
        for student_id, name, role, password in ACCOUNTS:
            students.create(Student(student_id=student_id, name=name, role=role), password)
        conn.commit()

        now = datetime.now()
        activities = ActivityService(conn)

        a1 = activities.create(
            "校园歌手大赛",
            "文艺",
            (now + timedelta(days=7)).replace(microsecond=0),
            "大学生活动中心",
            2,
            "DIRECT",
        ).data
        a2 = activities.create(
            "48 小时编程马拉松",
            "科技",
            (now + timedelta(days=14)).replace(microsecond=0),
            "信息楼 401",
            10,
            "REVIEW",
        ).data
        a3 = activities.create(
            "图书馆志愿整理",
            "志愿",
            (now + timedelta(days=3)).replace(microsecond=0),
            "图书馆三层",
            1,
            "REVIEW",
        ).data
        activities.create(
            "上学期回顾讲座",
            "讲座",
            (now - timedelta(days=7)).replace(microsecond=0),
            "报告厅",
            50,
            "DIRECT",
        )

        service = RegistrationService(conn)
        print(service.register("student1", a1).message)
        print(service.register("student2", a1).message)
        print(service.register("student3", a1).message)
        print(service.register("student3", a2).message)
        print(service.register("student1", a3).message)
        print(service.register("student2", a3).message)

    print(f"演示数据已生成：{DB_PATH}")
    print("演示账号：admin/admin123、student1/123456、student2/123456、student3/123456")


if __name__ == "__main__":
    main()
