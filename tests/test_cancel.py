"""取消报名与统计联动（C9）。"""

from app.models import ErrorCode, RegistrationStatus


def test_cancel_pending_registration(ctx, add_activity):
    activity = add_activity(capacity=2, policy="REVIEW")
    registration = ctx.service.register("s1", activity.activity_id).data

    result = ctx.service.cancel(registration.registration_id, "s1")

    assert result.ok
    assert ctx.registrations.get(registration.registration_id).status is RegistrationStatus.CANCELLED
    assert ctx.service.statistics(activity.activity_id).pending == 0
    assert any("已取消" in m.content for m in ctx.messages.list_by_student("s1"))


def test_cancel_approved_registration_frees_slot(ctx, add_activity):
    """C9：取消已通过报名后统计同步变化，名额重新可用。"""
    activity = add_activity(capacity=1)
    registration = ctx.service.register("s1", activity.activity_id).data
    assert ctx.service.register("s2", activity.activity_id).code == ErrorCode.CAPACITY_FULL

    assert ctx.service.cancel(registration.registration_id, "s1").ok

    stats = ctx.service.statistics(activity.activity_id)
    assert stats.approved == 0
    assert stats.cancelled == 1
    assert stats.remaining == 1
    assert ctx.service.register("s2", activity.activity_id).ok


def test_cancel_rejected_registration_is_refused(ctx, add_activity):
    activity = add_activity(capacity=2, policy="REVIEW")
    registration = ctx.service.register("s1", activity.activity_id).data
    ctx.service.reject(registration.registration_id)

    result = ctx.service.cancel(registration.registration_id, "s1")

    assert not result.ok
    assert result.code == ErrorCode.INVALID_STATE


def test_cannot_cancel_other_students_registration(ctx, add_activity):
    activity = add_activity(capacity=2)
    registration = ctx.service.register("s1", activity.activity_id).data

    result = ctx.service.cancel(registration.registration_id, "s2")

    assert not result.ok
    assert result.code == ErrorCode.FORBIDDEN
    assert ctx.registrations.get(registration.registration_id).status is RegistrationStatus.APPROVED


def test_cancel_twice_is_refused(ctx, add_activity):
    activity = add_activity(capacity=2)
    registration = ctx.service.register("s1", activity.activity_id).data

    assert ctx.service.cancel(registration.registration_id, "s1").ok
    result = ctx.service.cancel(registration.registration_id, "s1")

    assert not result.ok
    assert result.code == ErrorCode.INVALID_STATE


def test_cancel_unknown_registration(ctx):
    result = ctx.service.cancel(9999, "s1")
    assert not result.ok
    assert result.code == ErrorCode.REGISTRATION_NOT_FOUND
