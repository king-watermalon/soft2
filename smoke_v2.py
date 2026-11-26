"""HTTP 冒烟检查 v2：验证扩展在真实请求链路里生效（而不只是在服务层）。

用法：``python smoke_v2.py``（需先跑 ``python seed_ext_v2.py``）

检查四件事：
1. 扩展蓝图 ``/ext/admin`` 可访问，页面渲染正常；
2. 学生端仍走原有视图，但拿到的是扩展服务（年级限定生效）；
3. 被年级规则拒绝时，页面给出可读原因，且未产生报名记录；
4. 未设年级限定的活动行为不变。

这几步只有在 ``before_request`` 注入真的生效时才会通过——若注入失效，
第 3 步会变成"报名成功"，脚本会立刻报错。
"""

from __future__ import annotations

import sqlite3
import sys

from app_v2 import app

LIMITED_TITLE = "职业规划专场"


def _login(client, student_id: str, password: str):
    return client.post(
        "/login",
        data={"student_id": student_id, "password": password},
        follow_redirects=True,
    )


def _find_limited_activity(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT activity_id FROM activity WHERE title LIKE ? ORDER BY activity_id DESC",
        (f"%{LIMITED_TITLE}%",),
    ).fetchone()
    if row is None:
        sys.exit("未找到年级限定活动，请先运行 python seed_ext_v2.py")
    return int(row["activity_id"])


def main() -> None:
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    limited_id = _find_limited_activity(conn)

    client = app.test_client()
    failures: list[str] = []

    # 1) 管理页
    _login(client, "admin", "admin123")
    page = client.get("/ext/admin")
    if page.status_code != 200:
        failures.append(f"/ext/admin 返回 {page.status_code}")
    html = page.get_data(as_text=True)
    for keyword in ("变更扩展管理", "年级限定", "模拟邮件投递记录"):
        if keyword not in html:
            failures.append(f"管理页缺少区块：{keyword}")

    # 2) 大一学生报名年级限定活动 → 应被拒
    client = app.test_client()
    _login(client, "student1", "123456")
    before = conn.execute(
        "SELECT COUNT(*) AS c FROM registration WHERE student_id='student1' AND activity_id=?",
        (limited_id,),
    ).fetchone()["c"]
    response = client.post(
        f"/activity/{limited_id}/register", follow_redirects=True
    ).get_data(as_text=True)
    after = conn.execute(
        "SELECT COUNT(*) AS c FROM registration WHERE student_id='student1' AND activity_id=?",
        (limited_id,),
    ).fetchone()["c"]

    if before != after:
        failures.append("年级不符的学生仍被写入了报名记录")
    if "仅限" not in response:
        failures.append("页面未显示年级限定的拒绝原因")

    # 3) 未设年级限定的活动：各年级都应能报名（用大一学生验证）
    open_row = conn.execute(
        """SELECT activity_id FROM activity
           WHERE (grade_limit IS NULL OR TRIM(grade_limit) = '')
           ORDER BY activity_id LIMIT 1"""
    ).fetchone()
    if open_row is None:
        failures.append("没有找到不限年级的活动，无法验证等价性")
    else:
        client = app.test_client()
        _login(client, "student1", "123456")
        resp = client.post(
            f"/activity/{int(open_row['activity_id'])}/register", follow_redirects=True
        ).get_data(as_text=True)
        # 该活动可能已满/已开始，只要不是年级拒绝即可
        if "仅限" in resp:
            failures.append("不限年级的活动误触发年级规则")

    conn.close()

    if failures:
        print("SMOKE FAILED:")
        for item in failures:
            print("  -", item)
        sys.exit(1)

    print("SMOKE OK：扩展蓝图、年级拒绝、等价性三项均通过")
    print(f"  年级限定活动 activity_id={limited_id}")


if __name__ == "__main__":
    main()
