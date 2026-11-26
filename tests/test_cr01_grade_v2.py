"""CR-01：年级限定报名的变更测试（对应教师材料 CR1-01 ~ CR1-05）。

覆盖两个层面：
1. **变更项本身**——大二/大三通过，大一/大四拒绝并给出原因；
2. **不变量不被绕过**——名额、开始时间、重复报名等公共约束照旧生效，
   未设年级限定的活动行为与变更前完全一致。
"""

from __future__ import annotations

import pytest

from app.db import get_db
from app.models import RegistrationStatus
from ext_v2.grade_v2 import ErrorCodeExt, GradeLimitError, GradeRule, parse_grade_limit
from ext_v2.services_v2 import GradeAwareRegistrationService

from ext_support_v2 import make_activity, make_ext_app, past, set_grades


@pytest.fixture
def ext_app(tmp_path):
    return make_ext_app(tmp_path)


@pytest.fixture
def ctx(ext_app):
    with ext_app.app_context():
        conn = get_db()
        # s1 大一、s2 大三、s3 大二、s4 大四，覆盖 1—4 全部年级
        set_grades(conn, {"s1": 1, "s2": 3, "s3": 2, "s4": 4})
        yield conn


@pytest.fixture
def service(ctx):
    return GradeAwareRegistrationService(ctx)


# ---------------------------------------------------------------- CR1-01 / 02


def test_cr1_01_sophomore_passes_grade_limited_activity(ctx, service):
    """CR1-01：大二学生报名年级限定（2,3）活动 → 通过。"""
    activity_id = make_activity(ctx, grade_limit="2,3")

    result = service.register("s3", activity_id)

    assert result.ok, result.message
    assert result.data.status is RegistrationStatus.APPROVED


def test_cr1_02_junior_passes_grade_limited_activity(ctx, service):
    """CR1-02：大三学生报名年级限定（2,3）活动 → 通过。"""
    activity_id = make_activity(ctx, grade_limit="2,3")

    result = service.register("s2", activity_id)

    assert result.ok, result.message
    assert result.data.status is RegistrationStatus.APPROVED


# ---------------------------------------------------------------- CR1-03 / 04


def test_cr1_03_freshman_rejected_with_reason(ctx, service):
    """CR1-03：大一学生报名 → 拒绝，且提示里说明限定的年级。"""
    activity_id = make_activity(ctx, grade_limit="2,3")

    result = service.register("s1", activity_id)

    assert not result.ok
    assert result.code == ErrorCodeExt.GRADE_NOT_ELIGIBLE
    assert "仅限" in result.message
    assert "二年级" in result.message and "三年级" in result.message
    assert "一年级" in result.message  # 明确指出当前年级

    # 关键：被拒绝时不得留下任何报名记录
    rows = ctx.execute(
        "SELECT * FROM registration WHERE student_id = 's1'"
    ).fetchall()
    assert rows == []


def test_cr1_04_senior_rejected_with_reason(ctx, service):
    """CR1-04：大四学生报名 → 拒绝；大一只剩单个年级限定时同样拒绝。"""
    activity_id = make_activity(ctx, grade_limit="2,3")

    result = service.register("s4", activity_id)

    assert not result.ok
    assert result.code == ErrorCodeExt.GRADE_NOT_ELIGIBLE
    assert "四年级" in result.message

    # 限定只含大三时，大二也不通过（限定是白名单，不是"≥某年级"）
    only_junior = make_activity(ctx, title="仅大三", grade_limit="3")
    assert not service.register("s3", only_junior).ok
    assert service.register("s2", only_junior).ok


# ---------------------------------------------------------------- 公共约束不被绕过


def test_grade_limit_still_respects_capacity(ctx, service):
    """年级符合但名额已满 → 依然按名额拒绝。"""
    activity_id = make_activity(ctx, capacity=2, grade_limit="2,3")
    assert service.register("s2", activity_id).ok
    assert service.register("s3", activity_id).ok

    # s5 同为三年级，但名额已满
    ctx.execute(
        "INSERT INTO student (student_id, name, role, password, grade) "
        "VALUES ('s5', '孙七', 'STUDENT', '123456', 3)"
    )
    ctx.commit()

    result = service.register("s5", activity_id)
    assert not result.ok
    assert result.code == "CAPACITY_FULL"


def test_grade_limit_still_respects_started_activity(ctx, service):
    """活动已开始 → 年级符合也不能报名。"""
    activity_id = make_activity(ctx, grade_limit="2,3", start_at=past(1))

    result = service.register("s2", activity_id)

    assert not result.ok
    assert result.code == "ACTIVITY_STARTED"


def test_grade_limit_still_blocks_duplicate_active_registration(ctx, service):
    """同一活动不得两条有效报名。"""
    activity_id = make_activity(ctx, grade_limit="2,3")
    assert service.register("s2", activity_id).ok

    result = service.register("s2", activity_id)
    assert not result.ok
    assert result.code == "DUPLICATE_ACTIVE"


# ---------------------------------------------------------------- 变更前后等价性


def test_activity_without_grade_limit_keeps_original_behavior(ctx, service):
    """未设年级限定的活动：四个年级都能直接报名，与变更前一致。"""
    activity_id = make_activity(ctx, capacity=10, grade_limit=None)

    for student_id in ("s1", "s2", "s3", "s4"):
        result = service.register(student_id, activity_id)
        assert result.ok, f"{student_id}: {result.message}"
        assert result.data.status is RegistrationStatus.APPROVED


def test_review_policy_combined_with_grade_limit(ctx, service):
    """年级限定与审核策略正交：符合年级进入待审核，不符合直接拒绝。"""
    activity_id = make_activity(ctx, policy="REVIEW", grade_limit="2,3")

    ok = service.register("s3", activity_id)
    assert ok.ok
    assert ok.data.status is RegistrationStatus.PENDING

    blocked = service.register("s1", activity_id)
    assert not blocked.ok
    assert blocked.code == ErrorCodeExt.GRADE_NOT_ELIGIBLE


def test_student_without_registered_grade_is_blocked(ctx, service):
    """年级未登记的学生不放行（fail-closed），并提示去补录。"""
    ctx.execute(
        "INSERT INTO student (student_id, name, role, password) "
        "VALUES ('s9', '未登记', 'STUDENT', '123456')"
    )
    ctx.commit()
    activity_id = make_activity(ctx, grade_limit="2,3")

    result = service.register("s9", activity_id)

    assert not result.ok
    assert result.code == ErrorCodeExt.GRADE_NOT_REGISTERED
    assert "尚未登记" in result.message


def test_unknown_student_and_activity_keep_original_error_codes(ctx, service):
    """扩展不得改变"学生/活动不存在"的语义。"""
    activity_id = make_activity(ctx, grade_limit="2,3")

    missing_student = service.register("nobody", activity_id)
    assert missing_student.code == "STUDENT_NOT_FOUND"

    missing_activity = service.register("s3", 99999)
    assert missing_activity.code == "ACTIVITY_NOT_FOUND"


# ---------------------------------------------------------------- 规则解析


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2,3", {2, 3}),
        ("2;3", {2, 3}),
        ("2、3", {2, 3}),
        ("2 3", {2, 3}),
        ("3,2,3", {2, 3}),  # 去重 + 规范化
        ("", None),
        (None, None),
        ("   ", None),
    ],
)
def test_parse_grade_limit_accepts_common_separators(raw, expected):
    parsed = parse_grade_limit(raw)
    assert (set(parsed) if parsed is not None else None) == expected


@pytest.mark.parametrize("raw", ["0", "5", "abc", "2,x"])
def test_parse_grade_limit_rejects_out_of_range(raw):
    with pytest.raises(GradeLimitError):
        parse_grade_limit(raw)


def test_grade_rule_label_is_human_readable():
    assert GradeRule.parse("2,3").label == "二年级、三年级"
    assert GradeRule.parse("3").label == "三年级"
