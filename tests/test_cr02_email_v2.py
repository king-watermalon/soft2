"""CR-02：模拟邮件通知的变更测试（对应教师材料 CR2-01 ~ CR2-05）。

关注四件事：
1. 站内消息与模拟邮件**同时**留痕；
2. 通过、审核批准、拒绝三类结果都产生对应邮件；
3. 投递失败只影响通知，不回滚报名，且错误可查；
4. 同一业务事件重复投递不产生第二封。
"""

from __future__ import annotations

import pytest

from app.db import get_db
from app.events import EventType, RegistrationEvent
from app.models import RegistrationStatus
from app.repositories import (
    ActivityRepository,
    MessageRepository,
    OutboxRepository,
    RegistrationRepository,
    StudentRepository,
)
from ext_v2.email_v2 import MockEmailSender
from ext_v2.services_v2 import GradeAwareRegistrationService

from ext_support_v2 import make_activity, make_ext_app, set_grades


@pytest.fixture
def ext_app(tmp_path):
    return make_ext_app(tmp_path)


@pytest.fixture
def ctx(ext_app):
    with ext_app.app_context():
        conn = get_db()
        set_grades(conn, {"s1": 1, "s2": 3, "s3": 2, "s4": 4})
        yield conn


@pytest.fixture
def service(ctx):
    return GradeAwareRegistrationService(ctx)


def _mails(ctx, student_id: str = None):
    sql = "SELECT * FROM email_delivery"
    params: tuple = ()
    if student_id:
        sql += " WHERE student_id = ?"
        params = (student_id,)
    sql += " ORDER BY delivery_id"
    return ctx.execute(sql, params).fetchall()


# ---------------------------------------------------------------- CR2-01


def test_cr2_01_direct_registration_writes_both_channels(ctx, service):
    """CR2-01：直接报名通过 → 站内消息与模拟邮件均有记录。"""
    activity_id = make_activity(ctx, capacity=5, grade_limit=None)

    result = service.register("s1", activity_id)
    assert result.ok

    messages = MessageRepository(ctx).list_by_student("s1")
    assert len(messages) == 1
    assert "报名成功" in messages[0].content

    mails = _mails(ctx, "s1")
    assert len(mails) == 1
    assert mails[0]["status"] == "SENT"
    assert mails[0]["address"] == "s1@campus.edu.cn"


def test_cr2_01_email_records_all_required_fields(ctx, service):
    """材料要求记录"收件人、主题、内容、状态与时间"，逐列核对。"""
    activity_id = make_activity(ctx, capacity=5, grade_limit=None, title="摄影讲座")
    assert service.register("s2", activity_id).ok

    mail = _mails(ctx, "s2")[0]
    assert mail["address"] == "s2@campus.edu.cn"          # 收件人
    assert "摄影讲座" in mail["subject"]                   # 主题
    assert "李四" in mail["body"] and "摄影讲座" in mail["body"]  # 内容
    assert mail["status"] == "SENT"                        # 状态
    assert mail["attempted_at"]                            # 时间
    assert mail["event_id"]                                # 可追溯到业务事件


# ---------------------------------------------------------------- CR2-02


def test_cr2_02_approve_sends_approval_mail(ctx, service):
    """CR2-02：审核批准 → 站内与邮件都记录"已通过"。"""
    activity_id = make_activity(ctx, capacity=5, policy="REVIEW", grade_limit=None)
    pending = service.register("s3", activity_id)
    assert pending.data.status is RegistrationStatus.PENDING

    assert service.approve(pending.data.registration_id).ok

    mails = _mails(ctx, "s3")
    assert [m["status"] for m in mails] == ["SENT"]
    assert "已通过" in mails[0]["subject"]

    messages = MessageRepository(ctx).list_by_student("s3")
    assert any("报名成功" in m.content for m in messages)


def test_cr2_02_reject_sends_rejection_mail(ctx, service):
    """CR2-02：审核拒绝 → 站内与邮件都记录"未通过"。"""
    activity_id = make_activity(ctx, capacity=5, policy="REVIEW", grade_limit=None)
    pending = service.register("s4", activity_id)

    assert service.reject(pending.data.registration_id).ok

    mails = _mails(ctx, "s4")
    assert [m["status"] for m in mails] == ["SENT"]
    assert "未通过" in mails[0]["subject"]

    messages = MessageRepository(ctx).list_by_student("s4")
    assert any("未通过" in m.content for m in messages)


def test_cr2_02_cancel_does_not_send_mail(ctx, service):
    """边界：取消不在材料要求的"通过/拒绝"范围内，不应发邮件。"""
    activity_id = make_activity(ctx, capacity=5, grade_limit=None)
    registration = service.register("s1", activity_id).data

    assert service.cancel(registration.registration_id, "s1").ok

    # 只有报名通过那一封，取消不追加
    assert len(_mails(ctx, "s1")) == 1


# ---------------------------------------------------------------- CR2-03


def test_cr2_03_mail_failure_keeps_registration_and_logs_error(ctx):
    """CR2-03：模拟邮件失败 → 报名状态正确、错误在投递流水与通知流水都留痕。"""
    sender = MockEmailSender(ctx, fail_predicate=lambda address: True)
    service = GradeAwareRegistrationService(ctx, sender=sender)
    activity_id = make_activity(ctx, capacity=5, grade_limit=None)

    result = service.register("s1", activity_id)

    # 报名本身必须成功且已落库
    assert result.ok, result.message
    assert result.data.status is RegistrationStatus.APPROVED
    assert RegistrationRepository(ctx).get(result.data.registration_id) is not None

    # 站内消息不受影响
    assert len(MessageRepository(ctx).list_by_student("s1")) == 1

    # 投递流水记录了失败与原因
    mails = _mails(ctx, "s1")
    assert len(mails) == 1
    assert mails[0]["status"] == "FAILED"
    assert "不可达" in (mails[0]["error"] or "")

    # 通知总线也留了痕，且 listener 名可定位
    failed = OutboxRepository(ctx).failed()
    mock_rows = [row for row in failed if row["listener"] == "mock_email"]
    assert len(mock_rows) == 1
    assert "不可达" in mock_rows[0]["error"]


# ---------------------------------------------------------------- CR2-04


def test_cr2_04_repeated_business_action_does_not_duplicate_mail(ctx, service):
    """CR2-04：学生重复提交同一报名 → 第二次被业务规则拦住，邮件仍只有一封。"""
    activity_id = make_activity(ctx, capacity=5, grade_limit=None)

    assert service.register("s1", activity_id).ok
    second = service.register("s1", activity_id)

    assert not second.ok
    assert second.code == "DUPLICATE_ACTIVE"
    assert len(_mails(ctx, "s1")) == 1


def test_cr2_04_same_event_published_twice_sends_once(ctx, service):
    """CR2-04：同一事件被重复投递 → 邮件不重复生成。"""
    activity_id = make_activity(ctx, capacity=5, grade_limit=None)
    registration = service.register("s2", activity_id).data

    event = RegistrationEvent.create(
        EventType.REGISTRATION_APPROVED,
        registration,
        ActivityRepository(ctx).get(activity_id),
        StudentRepository(ctx).get("s2"),
    )
    service.publisher.publish(event)
    service.publisher.publish(event)

    mails = service.mail_sender.by_event(event.event_id)
    assert len(mails) == 1
    assert mails[0]["status"] == "SENT"


# ---------------------------------------------------------------- CR2-05 辅助


def test_extended_bus_keeps_channel_set_stable(ctx, service):
    """扩展装配应稳定为"站内 + 模拟邮件 + 审计"三个订阅者，不重复发信。"""
    activity_id = make_activity(ctx, capacity=5, grade_limit=None)
    assert service.register("s3", activity_id).ok

    listeners = {
        row["listener"]
        for row in ctx.execute("SELECT listener FROM notify_outbox").fetchall()
    }
    assert listeners == {"in_app", "mock_email", "audit"}
