"""扩展版演示数据 v2：在原有 ``seed.py`` 之上补齐年级信息与年级限定活动。

用法：``python seed_ext_v2.py``
注意：会先执行 ``seed.main()``，即**删除并重建** ``instance/campusevent.sqlite3``。

设计取舍
--------
不复制 ``seed.py`` 的数据定义，而是直接调用原 ``seed.main()``，再补扩展部分。
好处是：原有演示数据（含抽签活动与被占用的名额）一字不差地保留，
扩展只"追加"，与整个变更的增量思路一致；原 ``seed.py`` 也未做任何修改。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import seed
from app.db import connect
from ext_v2 import schema_v2
from ext_v2.email_v2 import MockEmailSender
from ext_v2.grade_v2 import GradeRuleRepository
from ext_v2.services_v2 import GradeAwareActivityService, GradeAwareRegistrationService

#: 演示用年级分布：大一 / 大三 / 大二，覆盖"符合"与"不符合"两类情形。
DEMO_GRADES = {
    "student1": 1,  # 大一 —— 应被年级限定活动拒绝
    "student2": 3,  # 大三 —— 应通过
    "student3": 2,  # 大二 —— 应通过
}


def main() -> None:
    seed.main()  # 原有演示数据 + 抽签数据

    conn = connect(seed.DB_PATH)  # 已带 row_factory 与外键开关

    changes = schema_v2.migrate(conn)
    print(f"[ext_v2] 迁移完成：{changes}")

    rules = GradeRuleRepository(conn)
    for student_id, grade in DEMO_GRADES.items():
        rules.set_grade_of_student(student_id, grade)
    conn.commit()
    print(f"[ext_v2] 已登记年级：{DEMO_GRADES}")

    # 新增一个"仅大二、大三可报名"的直接报名活动
    activity_service = GradeAwareActivityService(conn)
    created = activity_service.create_limited(
        title="职业规划专场（大二大三限定）",
        category="讲座",
        start_at=(datetime.now() + timedelta(days=5)).replace(microsecond=0),
        location="就业指导中心 201",
        capacity=3,
        policy_type="DIRECT",
        grade_limit="2,3",
    )
    print(f"[ext_v2] {created.message}（activity_id={created.data}）")
    limited_id = created.data

    # 扩展版服务：带年级准入 + 模拟邮件
    service = GradeAwareRegistrationService(conn)

    print("\n--- 年级准入演示 ---")
    for student_id in ("student1", "student3", "student2"):
        result = service.register(student_id, limited_id)
        grade = rules.grade_of_student(student_id)
        flag = "OK " if result.ok else "REJ"
        print(f"[{flag}] {student_id}（{grade} 年级）→ {result.message}")

    sender = MockEmailSender(conn)
    print("\n--- 模拟邮件投递记录 ---")
    for row in sender.recent(10):
        print(
            f"[{row['status']}] {row['address']} | {row['subject']} | {row['attempted_at']}"
        )
    print(f"统计：{sender.counts()}")

    conn.close()
    print(f"\n扩展演示数据已生成：{seed.DB_PATH}")
    print("启动扩展版：python app_v2.py → http://127.0.0.1:5000/ext/admin")


if __name__ == "__main__":
    main()
