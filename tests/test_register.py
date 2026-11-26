"""报名用例：直接报名、重复拦截、名额上限、审核型排队（C2–C5）。"""

from app.models import ErrorCode, RegistrationStatus


def test_direct_register_is_approved_immediately(ctx, add_activity):
    """C2：学生报名直接报名活动，立即变为"已通过"并收到通知。"""
    activity = add_activity(capacity=5)

    result = ctx.service.register("s1", activity.activity_id)

    assert result.ok
    assert result.data.status is RegistrationStatus.APPROVED
    messages = ctx.messages.list_by_student("s1")
    assert len(messages) == 1
    assert "报名成功" in messages[0].content
    assert messages[0].activity_id == activity.activity_id


def test_duplicate_active_registration_is_rejected(ctx, add_activity):
    """C3：再次提交同一活动的报名被拒绝（B.2 第 4 条）。"""
    activity = add_activity(capacity=5)
    assert ctx.service.register("s1", activity.activity_id).ok

    result = ctx.service.register("s1", activity.activity_id)

    assert not result.ok
    assert result.code == ErrorCode.DUPLICATE_ACTIVE
    assert len(ctx.registrations.list_by_student("s1")) == 1


def test_capacity_full_rejects_further_registration(ctx, add_activity):
    """C4：名额已满后其他学生报名失败。"""
    activity = add_activity(capacity=1)

    assert ctx.service.register("s1", activity.activity_id).ok
    result = ctx.service.register("s2", activity.activity_id)

    assert not result.ok
    assert result.code == ErrorCode.CAPACITY_FULL
    assert ctx.service.statistics(activity.activity_id).approved == 1


def test_review_registration_goes_pending_and_keeps_slot_free(ctx, add_activity):
    """C5：审核型活动申请后为"待审核"，暂不占用名额（B.2 第 3 条）。"""
    activity = add_activity(capacity=2, policy="REVIEW")

    result = ctx.service.register("s1", activity.activity_id)

    assert result.ok
    assert result.data.status is RegistrationStatus.PENDING
    stats = ctx.service.statistics(activity.activity_id)
    assert stats.approved == 0
    assert stats.pending == 1
    assert stats.remaining == 2
    assert "等待管理员审核" in ctx.messages.list_by_student("s1")[0].content


def test_pending_does_not_block_other_students(ctx, add_activity):
    activity = add_activity(capacity=2, policy="REVIEW")

    assert ctx.service.register("s1", activity.activity_id).ok
    assert ctx.service.register("s2", activity.activity_id).ok

    assert ctx.service.statistics(activity.activity_id).pending == 2


def test_register_after_activity_started_is_refused(ctx, add_activity, clock):
    activity = add_activity(start_at=clock.past(1))

    result = ctx.service.register("s1", activity.activity_id)

    assert not result.ok
    assert result.code == ErrorCode.ACTIVITY_STARTED


def test_register_unknown_student(ctx, add_activity):
    activity = add_activity()
    result = ctx.service.register("nobody", activity.activity_id)
    assert not result.ok
    assert result.code == ErrorCode.STUDENT_NOT_FOUND


def test_register_unknown_activity(ctx):
    result = ctx.service.register("s1", 9999)
    assert not result.ok
    assert result.code == ErrorCode.ACTIVITY_NOT_FOUND


def test_cancelled_registration_can_apply_again(ctx, add_activity):
    """B.2 第 4 条：已取消的记录保留历史，允许再次申请。"""
    activity = add_activity(capacity=2)
    first = ctx.service.register("s1", activity.activity_id).data

    assert ctx.service.cancel(first.registration_id, "s1").ok

    second = ctx.service.register("s1", activity.activity_id)

    assert second.ok
    assert second.data.registration_id != first.registration_id
    assert len(ctx.registrations.list_by_student("s1")) == 2


def test_rejected_registration_can_apply_again(ctx, add_activity):
    activity = add_activity(capacity=2, policy="REVIEW")
    first = ctx.service.register("s1", activity.activity_id).data
    assert ctx.service.reject(first.registration_id).ok

    second = ctx.service.register("s1", activity.activity_id)

    assert second.ok
    assert second.data.status is RegistrationStatus.PENDING
