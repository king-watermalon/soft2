"""Web 层冒烟测试：路由、权限、登录态与页面渲染。"""

from app.models import RegistrationStatus


def test_index_page_renders(client, ctx, add_activity):
    add_activity(title="校园歌手大赛", capacity=3)

    response = client.get("/")

    assert response.status_code == 200
    assert "校园歌手大赛" in response.get_data(as_text=True)


def test_search_filters_by_title(client, ctx, add_activity):
    add_activity(title="歌手大赛")
    add_activity(title="编程马拉松")

    body = client.get("/?q=歌手").get_data(as_text=True)

    assert "歌手大赛" in body
    assert "编程马拉松" not in body


def test_login_with_wrong_password_returns_401(client):
    response = client.post("/login", data={"student_id": "s1", "password": "wrong"})

    assert response.status_code == 401
    assert "账号或密码错误" in response.get_data(as_text=True)


def test_login_then_register(client, ctx, add_activity):
    activity = add_activity(capacity=3)
    assert client.post(
        "/login", data={"student_id": "s1", "password": "123456"}
    ).status_code == 302

    response = client.post(
        f"/activity/{activity.activity_id}/register", follow_redirects=True
    )

    assert response.status_code == 200
    registration = ctx.registrations.find_active(activity.activity_id, "s1")
    assert registration is not None
    assert registration.status is RegistrationStatus.APPROVED


def test_anonymous_register_redirects_to_login(client, ctx, add_activity):
    activity = add_activity()

    response = client.post(f"/activity/{activity.activity_id}/register")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_student_cannot_open_admin_page(client, ctx):
    client.post("/login", data={"student_id": "s1", "password": "123456"})

    assert client.get("/admin/").status_code == 403


def test_admin_can_approve_through_web(client, ctx, add_activity):
    activity = add_activity(policy="REVIEW", capacity=3)
    ctx.service.register("s1", activity.activity_id)
    registration = ctx.registrations.find_active(activity.activity_id, "s1")

    client.post("/login", data={"student_id": "admin", "password": "admin123"})
    response = client.post(
        f"/admin/registration/{registration.registration_id}/approve",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert (
        ctx.registrations.get(registration.registration_id).status
        is RegistrationStatus.APPROVED
    )


def test_messages_page_marks_messages_read(client, ctx, add_activity):
    activity = add_activity()
    ctx.service.register("s1", activity.activity_id)
    client.post("/login", data={"student_id": "s1", "password": "123456"})

    body = client.get("/messages").get_data(as_text=True)

    assert "报名成功" in body
    assert ctx.messages.count_unread("s1") == 0


def test_open_redirect_is_blocked(client):
    response = client.post(
        "/login",
        data={
            "student_id": "s1",
            "password": "123456",
            "next": "https://evil.example.com/steal",
        },
    )

    assert response.status_code == 302
    assert "evil.example.com" not in response.headers["Location"]


def test_activity_detail_returns_404(client, ctx):
    assert client.get("/activity/9999").status_code == 404


def test_admin_create_activity_through_form(client, ctx):
    from datetime import datetime, timedelta

    from app.models import PolicyType

    client.post("/login", data={"student_id": "admin", "password": "admin123"})
    start_at = (datetime.now() + timedelta(days=4)).replace(microsecond=0)

    response = client.post(
        "/admin/activity/new",
        data={
            "title": "表单创建的活动",
            "category": "文艺",
            "start_at": start_at.strftime("%Y-%m-%dT%H:%M"),
            "location": "礼堂",
            "capacity": "12",
            "policy_type": PolicyType.REVIEW.value,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "表单创建的活动" in response.get_data(as_text=True)
