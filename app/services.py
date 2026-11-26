"""业务服务层：集中校验"不变量"，并编排策略与事件。

分层口径：
- 不变量（名额、重复报名、状态迁移、开始时间）= RegistrationService
- 变化点（这一笔申请置为何种状态）= RegistrationPolicy
- 副作用（站内消息）= EventListener
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime
from typing import Callable, Optional

from .events import (
    EventPublisher,
    EventType,
    RegistrationEvent,
    build_event_bus,
)
from .models import (
    Activity,
    ActivityStatistics,
    ActivityStatus,
    ErrorCode,
    PolicyType,
    Registration,
    RegistrationStatus,
    Result,
)
from .policies import PolicyFactory
from .repositories import (
    ActivityRepository,
    MessageRepository,
    RegistrationRepository,
    StudentRepository,
)


def parse_datetime(value) -> Optional[datetime]:
    """接受 datetime 或 'YYYY-MM-DDTHH:MM' / 'YYYY-MM-DD HH:MM' 字符串。"""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class RegistrationService:
    """报名与审批的用例实现（P2-F03 ~ P2-F08）。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        publisher: EventPublisher | None = None,
        clock: Callable[[], datetime] = datetime.now,
        policy_factory: PolicyFactory | None = None,
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.students = StudentRepository(conn)
        self.activities = ActivityRepository(conn)
        self.registrations = RegistrationRepository(conn)
        self.messages = MessageRepository(conn)
        self.policies = policy_factory or PolicyFactory()
        self.publisher = publisher or build_event_bus(conn, clock=clock)

    # ---------- 报名 ----------

    def register(self, student_id: str, activity_id: int) -> Result:
        student = self.students.get(student_id)
        if student is None:
            return Result.failure(ErrorCode.STUDENT_NOT_FOUND, "学生不存在")

        activity = self.activities.get(activity_id)
        if activity is None:
            return Result.failure(ErrorCode.ACTIVITY_NOT_FOUND, "活动不存在")

        if activity.status is ActivityStatus.CLOSED:
            return Result.failure(ErrorCode.ACTIVITY_CLOSED, "活动已关闭，无法报名")

        now = self.clock()
        if activity.start_at <= now:
            return Result.failure(ErrorCode.ACTIVITY_STARTED, "活动已开始，无法报名")

        # 公共规则 1：同一活动不得有两条有效报名（PENDING/APPROVED）
        if self.registrations.find_active(activity_id, student_id) is not None:
            return Result.failure(
                ErrorCode.DUPLICATE_ACTIVE, "你已报名该活动，请勿重复提交"
            )

        # 公共规则 2：名额只按"已通过"计算；满员后不再接受新申请
        approved = self.registrations.count_by_status(
            activity_id, RegistrationStatus.APPROVED
        )
        if approved >= activity.capacity:
            return Result.failure(
                ErrorCode.CAPACITY_FULL,
                f"名额已满（{approved}/{activity.capacity}）",
            )

        # 变化点：交给策略决定初始状态
        policy = self.policies.create(activity.policy_type)
        decision = policy.decide(activity, student, approved)

        try:
            registration = self.registrations.insert(
                activity_id=activity_id,
                student_id=student_id,
                status=decision.status,
                now=now,
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            # 数据库层兜底：并发下两条有效报名只可能成功一条
            self.conn.rollback()
            return Result.failure(
                ErrorCode.DUPLICATE_ACTIVE, "你已报名该活动，请勿重复提交"
            )

        self._publish(registration, activity, student)
        return Result.success(decision.reason, data=registration)

    # ---------- 审批 ----------

    def approve(self, registration_id: int) -> Result:
        registration = self.registrations.get(registration_id)
        if registration is None:
            return Result.failure(ErrorCode.REGISTRATION_NOT_FOUND, "报名记录不存在")

        if registration.status is not RegistrationStatus.PENDING:
            return Result.failure(
                ErrorCode.INVALID_STATE,
                f"只有待审核的报名可以批准（当前状态：{registration.status.label}）",
            )

        activity = self.activities.get(registration.activity_id)
        approved = self.registrations.count_by_status(
            activity.activity_id, RegistrationStatus.APPROVED
        )
        # 批准时再次检查名额（用例 C8）
        if approved >= activity.capacity:
            return Result.failure(
                ErrorCode.CAPACITY_FULL,
                f"名额已满（{approved}/{activity.capacity}），无法批准",
            )

        self.registrations.update_status(
            registration_id, RegistrationStatus.APPROVED, self.clock()
        )
        self.conn.commit()
        registration = self.registrations.get(registration_id)
        self._publish(registration, activity, self.students.get(registration.student_id))
        return Result.success("已批准该报名", data=registration)

    def reject(self, registration_id: int) -> Result:
        registration = self.registrations.get(registration_id)
        if registration is None:
            return Result.failure(ErrorCode.REGISTRATION_NOT_FOUND, "报名记录不存在")

        if registration.status is not RegistrationStatus.PENDING:
            return Result.failure(
                ErrorCode.INVALID_STATE,
                f"只有待审核的报名可以拒绝（当前状态：{registration.status.label}）",
            )

        activity = self.activities.get(registration.activity_id)
        self.registrations.update_status(
            registration_id, RegistrationStatus.REJECTED, self.clock()
        )
        self.conn.commit()
        registration = self.registrations.get(registration_id)
        self._publish(registration, activity, self.students.get(registration.student_id))
        return Result.success("已拒绝该报名", data=registration)

    # ---------- 取消 ----------

    def cancel(self, registration_id: int, student_id: str) -> Result:
        registration = self.registrations.get(registration_id)
        if registration is None:
            return Result.failure(ErrorCode.REGISTRATION_NOT_FOUND, "报名记录不存在")

        if registration.student_id != student_id:
            return Result.failure(ErrorCode.FORBIDDEN, "不能取消他人的报名")

        if not registration.status.is_active:
            return Result.failure(
                ErrorCode.INVALID_STATE,
                f"该报名当前状态为{registration.status.label}，无法取消",
            )

        activity = self.activities.get(registration.activity_id)
        self.registrations.update_status(
            registration_id, RegistrationStatus.CANCELLED, self.clock()
        )
        self.conn.commit()
        registration = self.registrations.get(registration_id)
        self._publish(registration, activity, self.students.get(registration.student_id))
        return Result.success("已取消报名", data=registration)

    # ---------- 抽签（CR-01） ----------

    def draw_lottery(self, activity_id: int, rng: random.Random | None = None) -> Result:
        """对抽签型活动执行一次抽签：名额内随机录取，其余置为已拒绝。"""
        activity = self.activities.get(activity_id)
        if activity is None:
            return Result.failure(ErrorCode.ACTIVITY_NOT_FOUND, "活动不存在")
        if activity.policy_type is not PolicyType.LOTTERY:
            return Result.failure(
                ErrorCode.INVALID_STATE, "只有抽签型活动可以执行抽签"
            )

        pendings = self.registrations.list_by_activity(
            activity_id, RegistrationStatus.PENDING
        )
        if not pendings:
            return Result.failure(ErrorCode.INVALID_STATE, "当前没有待抽签的报名")

        approved = self.registrations.count_by_status(
            activity_id, RegistrationStatus.APPROVED
        )
        seats = max(activity.capacity - approved, 0)
        picker = rng or random.Random()
        winners = picker.sample(pendings, min(seats, len(pendings)))
        winner_ids = {item.registration_id for item in winners}

        now = self.clock()
        for registration in pendings:
            status = (
                RegistrationStatus.APPROVED
                if registration.registration_id in winner_ids
                else RegistrationStatus.REJECTED
            )
            self.registrations.update_status(registration.registration_id, status, now)
        self.conn.commit()

        for registration in pendings:
            refreshed = self.registrations.get(registration.registration_id)
            self._publish(
                refreshed, activity, self.students.get(registration.student_id)
            )

        return Result.success(
            f"抽签完成：{len(winners)} 人录取，{len(pendings) - len(winners)} 人未录取",
            data={"approved": len(winners), "rejected": len(pendings) - len(winners)},
        )

    # ---------- 查询 ----------

    def statistics(self, activity_id: int) -> Optional[ActivityStatistics]:
        activity = self.activities.get(activity_id)
        if activity is None:
            return None
        return self.registrations.statistics(activity_id, activity.capacity)

    def pending_of(self, activity_id: int) -> list[Registration]:
        return self.registrations.list_by_activity(
            activity_id, RegistrationStatus.PENDING
        )

    # ---------- 内部 ----------

    def _publish(self, registration: Registration, activity: Activity, student) -> None:
        """事务提交之后再发布事件：通知失败不回滚已生效的报名。"""
        if registration is None or activity is None or student is None:
            return
        event_type = {
            RegistrationStatus.APPROVED: EventType.REGISTRATION_APPROVED,
            RegistrationStatus.PENDING: EventType.REGISTRATION_SUBMITTED,
            RegistrationStatus.REJECTED: EventType.REGISTRATION_REJECTED,
            RegistrationStatus.CANCELLED: EventType.REGISTRATION_CANCELLED,
        }[registration.status]
        self.publisher.publish(
            RegistrationEvent.create(event_type, registration, activity, student)
        )


class ActivityService:
    """活动管理（P2-F01）：管理员 CRUD 与参数校验。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.activities = ActivityRepository(conn)

    def create(
        self,
        title: str,
        category: str,
        start_at,
        location: str,
        capacity,
        policy_type,
    ) -> Result:
        data, error = self._validate(title, start_at, capacity, policy_type)
        if error:
            return error
        activity_id = self.activities.create(
            title=data["title"],
            category=(category or "").strip(),
            start_at=data["start_at"],
            location=(location or "").strip(),
            capacity=data["capacity"],
            policy_type=data["policy_type"],
            created_at=self.clock(),
        )
        self.conn.commit()
        return Result.success("活动已创建", data=activity_id)

    def update(
        self,
        activity_id: int,
        title: str,
        category: str,
        start_at,
        location: str,
        capacity,
        policy_type,
    ) -> Result:
        if self.activities.get(activity_id) is None:
            return Result.failure(ErrorCode.ACTIVITY_NOT_FOUND, "活动不存在")
        data, error = self._validate(title, start_at, capacity, policy_type)
        if error:
            return error
        self.activities.update(
            activity_id=activity_id,
            title=data["title"],
            category=(category or "").strip(),
            start_at=data["start_at"],
            location=(location or "").strip(),
            capacity=data["capacity"],
            policy_type=data["policy_type"],
        )
        self.conn.commit()
        return Result.success("活动已更新")

    def delete(self, activity_id: int) -> Result:
        if self.activities.get(activity_id) is None:
            return Result.failure(ErrorCode.ACTIVITY_NOT_FOUND, "活动不存在")
        # 设计取舍：已有报名时拒绝删除，避免连带丢失报名与通知历史
        if self.activities.registration_count(activity_id) > 0:
            return Result.failure(
                ErrorCode.ACTIVITY_HAS_REGISTRATIONS,
                "该活动已有报名记录，不能删除；请改为关闭活动",
            )
        self.activities.delete(activity_id)
        self.conn.commit()
        return Result.success("活动已删除")

    def close(self, activity_id: int) -> Result:
        if self.activities.get(activity_id) is None:
            return Result.failure(ErrorCode.ACTIVITY_NOT_FOUND, "活动不存在")
        self.activities.set_status(activity_id, ActivityStatus.CLOSED)
        self.conn.commit()
        return Result.success("活动已关闭，当前不能再报名")

    @staticmethod
    def _validate(title, start_at, capacity, policy_type) -> tuple[dict, Result | None]:
        title = (title or "").strip()
        if not title:
            return {}, Result.failure(ErrorCode.VALIDATION_ERROR, "活动名称不能为空")

        parsed_start = parse_datetime(start_at)
        if parsed_start is None:
            return {}, Result.failure(
                ErrorCode.VALIDATION_ERROR, "开始时间格式不正确"
            )

        try:
            capacity_int = int(capacity)
        except (TypeError, ValueError):
            return {}, Result.failure(ErrorCode.VALIDATION_ERROR, "人数上限必须是整数")
        if capacity_int <= 0:
            return {}, Result.failure(ErrorCode.VALIDATION_ERROR, "人数上限必须大于 0")

        try:
            policy = (
                policy_type
                if isinstance(policy_type, PolicyType)
                else PolicyType(str(policy_type))
            )
        except ValueError:
            return {}, Result.failure(ErrorCode.VALIDATION_ERROR, "报名方式不合法")

        return (
            {
                "title": title,
                "start_at": parsed_start,
                "capacity": capacity_int,
                "policy_type": policy,
            },
            None,
        )
