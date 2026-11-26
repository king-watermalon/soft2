"""CR-01 抽签策略 / CR-02 邮件通知渠道的新增用例。"""

import random

from app.models import ErrorCode, PolicyType, RegistrationStatus


def _apply(ctx, activity, *student_ids):
    for sid in student_ids:
        result = ctx.service.register(sid, activity.activity_id)
        assert result.ok, result.message


def test_lottery_registration_enters_pending(ctx, add_activity):
    activity = add_activity(capacity=2, policy="LOTTERY")

    result = ctx.service.register("s1", activity.activity_id)

    assert result.ok
    assert result.data.status is RegistrationStatus.PENDING
    assert "抽签" in result.message


def test_lottery_draw_respects_capacity(ctx, add_activity):
    """容量 2、5 人报名 → 抽签后恰好 2 人通过，其余拒绝。"""
    activity = add_activity(capacity=2, policy="LOTTERY")
    _apply(ctx, activity, "s1", "s2", "s3", "s4")

    result = ctx.service.draw_lottery(activity.activity_id, rng=random.Random(42))

    assert result.ok
    stats = ctx.service.statistics(activity.activity_id)
    assert stats.approved == 2
    assert stats.rejected == 2
    assert stats.pending == 0


def test_lottery_draw_is_reproducible_with_same_seed(ctx, add_activity):
    activity = add_activity(capacity=1, policy="LOTTERY")
    _apply(ctx, activity, "s1", "s2", "s3")

    ctx.service.draw_lottery(activity.activity_id, rng=random.Random(7))
    winners = sorted(
        r.student_id
        for r in ctx.registrations.list_by_activity(
            activity.activity_id, RegistrationStatus.APPROVED
        )
    )

    assert len(winners) == 1


def test_lottery_draw_generates_notifications_for_every_participant(ctx, add_activity):
    activity = add_activity(capacity=1, policy="LOTTERY")
    _apply(ctx, activity, "s1", "s2")

    ctx.service.draw_lottery(activity.activity_id, rng=random.Random(1))

    for sid in ("s1", "s2"):
        assert len(ctx.messages.list_by_student(sid)) == 2  # 报名受理 + 抽签结果


def test_draw_on_non_lottery_activity_is_refused(ctx, add_activity):
    activity = add_activity(capacity=3, policy="REVIEW")
    _apply(ctx, activity, "s1")

    result = ctx.service.draw_lottery(activity.activity_id)

    assert not result.ok
    assert result.code == ErrorCode.INVALID_STATE


def test_draw_without_pending_is_refused(ctx, add_activity):
    activity = add_activity(capacity=3, policy="LOTTERY")

    result = ctx.service.draw_lottery(activity.activity_id)

    assert not result.ok
    assert result.code == ErrorCode.INVALID_STATE


def test_lottery_activity_can_be_created(ctx, add_activity):
    activity = add_activity(policy="LOTTERY")
    assert activity.policy_type is PolicyType.LOTTERY
    assert activity.policy_type.label == "抽签录取"


def test_email_channel_writes_outbox(ctx, add_activity):
    """CR-02：邮件渠道是一个新的观察者，未修改任何报名代码。"""
    activity = add_activity(capacity=3)
    _apply(ctx, activity, "s1")

    rows = ctx.conn.execute("SELECT * FROM email_outbox").fetchall()
    assert len(rows) == 1
    assert rows[0]["address"] == "s1@campus.edu.cn"
    assert "已通过" in rows[0]["subject"] or "报名" in rows[0]["subject"]
    assert activity.title in rows[0]["body"]


def test_email_channel_is_idempotent(ctx, add_activity):
    activity = add_activity(capacity=3)
    _apply(ctx, activity, "s1")

    from app.events import EventType, RegistrationEvent, build_event_bus
    from app.repositories import ActivityRepository, StudentRepository

    registration = ctx.registrations.list_by_student("s1")[0]
    event = RegistrationEvent.create(
        EventType.REGISTRATION_APPROVED,
        registration,
        ctx.activities.get(activity.activity_id),
        ctx.students.get("s1"),
    )
    bus = build_event_bus(ctx.conn)
    bus.publish(event)
    bus.publish(event)

    count = ctx.conn.execute(
        "SELECT COUNT(*) AS c FROM email_outbox WHERE event_id = ?", (event.event_id,)
    ).fetchone()["c"]
    assert count == 1
