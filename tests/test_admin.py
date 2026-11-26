"""活动管理：创建、参数校验、删除与关闭（P2-F01，用例 C1）。"""

import pytest

from app.models import ActivityStatus, ErrorCode, PolicyType


def test_create_direct_activity(ctx, add_activity):
    """C1：管理员创建直接报名活动，容量 2，创建后可供学生报名。"""
    activity = add_activity(title="校园歌手大赛", capacity=2, policy=PolicyType.DIRECT)

    assert activity.title == "校园歌手大赛"
    assert activity.capacity == 2
    assert activity.policy_type is PolicyType.DIRECT
    assert activity.status is ActivityStatus.OPEN


def test_create_review_activity(add_activity):
    activity = add_activity(title="编程马拉松", policy="REVIEW")
    assert activity.policy_type is PolicyType.REVIEW


def test_title_is_required(ctx, clock):
    result = ctx.activity_service.create("   ", "测试", clock.future(1), "", 2, "DIRECT")
    assert not result.ok
    assert result.code == ErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize("capacity", [0, -3, "abc", None])
def test_capacity_must_be_positive_integer(ctx, clock, capacity):
    result = ctx.activity_service.create(
        "活动", "测试", clock.future(1), "", capacity, "DIRECT"
    )
    assert not result.ok
    assert result.code == ErrorCode.VALIDATION_ERROR


def test_start_time_must_be_parsable(ctx):
    result = ctx.activity_service.create("活动", "", "下周三", "", 2, "DIRECT")
    assert not result.ok
    assert result.code == ErrorCode.VALIDATION_ERROR


def test_policy_type_must_be_supported(ctx, clock):
    result = ctx.activity_service.create("活动", "", clock.future(1), "", 2, "BIDDING")
    assert not result.ok
    assert result.code == ErrorCode.VALIDATION_ERROR


def test_delete_activity_without_registration(ctx, add_activity):
    activity = add_activity()
    result = ctx.activity_service.delete(activity.activity_id)
    assert result.ok
    assert ctx.activities.get(activity.activity_id) is None


def test_delete_activity_with_registrations_is_refused(ctx, add_activity):
    """设计取舍：已有报名时拒绝删除，保护报名与通知历史。"""
    activity = add_activity(capacity=3)
    ctx.service.register("s1", activity.activity_id)

    result = ctx.activity_service.delete(activity.activity_id)

    assert not result.ok
    assert result.code == ErrorCode.ACTIVITY_HAS_REGISTRATIONS
    assert ctx.activities.get(activity.activity_id) is not None


def test_close_activity_blocks_new_registration(ctx, add_activity):
    activity = add_activity(capacity=3)

    assert ctx.activity_service.close(activity.activity_id).ok
    result = ctx.service.register("s1", activity.activity_id)

    assert not result.ok
    assert result.code == ErrorCode.ACTIVITY_CLOSED


def test_update_activity_changes_capacity(ctx, add_activity):
    activity = add_activity(capacity=5)

    result = ctx.activity_service.update(
        activity_id=activity.activity_id,
        title="改过的名称",
        category="文艺",
        start_at=activity.start_at,
        location="新地点",
        capacity=8,
        policy_type="DIRECT",
    )

    assert result.ok
    refreshed = ctx.activities.get(activity.activity_id)
    assert refreshed.title == "改过的名称"
    assert refreshed.capacity == 8
