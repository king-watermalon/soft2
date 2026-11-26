"""审批用例：批准、拒绝、批准时名额复核（C6–C8）。"""

from app.models import ErrorCode, RegistrationStatus


def _apply(ctx, activity, student_id="s1"):
    result = ctx.service.register(student_id, activity.activity_id)
    assert result.ok
    return result.data


def test_approve_pending_registration(ctx, add_activity):
    """C6：管理员批准待审核报名，变为"已通过"并生成通知。"""
    activity = add_activity(capacity=3, policy="REVIEW")
    registration = _apply(ctx, activity)

    result = ctx.service.approve(registration.registration_id)

    assert result.ok
    assert ctx.registrations.get(registration.registration_id).status is RegistrationStatus.APPROVED
    contents = [m.content for m in ctx.messages.list_by_student("s1")]
    assert any("报名成功" in c for c in contents)
    assert ctx.service.statistics(activity.activity_id).approved == 1


def test_reject_pending_registration(ctx, add_activity):
    """C7：管理员拒绝待审核报名，变为"已拒绝"并生成通知。"""
    activity = add_activity(capacity=3, policy="REVIEW")
    registration = _apply(ctx, activity)

    result = ctx.service.reject(registration.registration_id)

    assert result.ok
    assert ctx.registrations.get(registration.registration_id).status is RegistrationStatus.REJECTED
    assert any("未通过" in m.content for m in ctx.messages.list_by_student("s1"))


def test_approve_fails_when_capacity_is_full(ctx, add_activity):
    """C8：批准时名额已满，批准失败且不超出上限。"""
    activity = add_activity(capacity=1, policy="REVIEW")
    first = _apply(ctx, activity, "s1")
    second = _apply(ctx, activity, "s2")
    third = _apply(ctx, activity, "s3")

    assert ctx.service.approve(first.registration_id).ok
    result = ctx.service.approve(second.registration_id)

    assert not result.ok
    assert result.code == ErrorCode.CAPACITY_FULL
    stats = ctx.service.statistics(activity.activity_id)
    assert stats.approved == 1
    assert stats.pending == 2
    assert ctx.registrations.get(second.registration_id).status is RegistrationStatus.PENDING
    assert ctx.registrations.get(third.registration_id).status is RegistrationStatus.PENDING


def test_approve_twice_is_refused(ctx, add_activity):
    activity = add_activity(capacity=3, policy="REVIEW")
    registration = _apply(ctx, activity)
    assert ctx.service.approve(registration.registration_id).ok

    result = ctx.service.approve(registration.registration_id)

    assert not result.ok
    assert result.code == ErrorCode.INVALID_STATE


def test_reject_after_approved_is_refused(ctx, add_activity):
    activity = add_activity(capacity=3, policy="REVIEW")
    registration = _apply(ctx, activity)
    assert ctx.service.approve(registration.registration_id).ok

    result = ctx.service.reject(registration.registration_id)

    assert not result.ok
    assert result.code == ErrorCode.INVALID_STATE


def test_approve_unknown_registration(ctx):
    result = ctx.service.approve(9999)
    assert not result.ok
    assert result.code == ErrorCode.REGISTRATION_NOT_FOUND


def test_pending_list_shows_only_pending(ctx, add_activity):
    activity = add_activity(capacity=5, policy="REVIEW")
    first = _apply(ctx, activity, "s1")
    _apply(ctx, activity, "s2")
    ctx.service.reject(first.registration_id)

    pendings = ctx.service.pending_of(activity.activity_id)

    assert len(pendings) == 1
    assert pendings[0].student_id == "s2"
