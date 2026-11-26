"""领域模型：实体、值对象与枚举。

对应设计类图中的实体层，不含任何持久化或框架代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RegistrationStatus(str, Enum):
    """报名状态。状态迁移规则由 RegistrationService 集中校验。"""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

    @property
    def label(self) -> str:
        return {
            RegistrationStatus.PENDING: "待审核",
            RegistrationStatus.APPROVED: "已通过",
            RegistrationStatus.REJECTED: "已拒绝",
            RegistrationStatus.CANCELLED: "已取消",
        }[self]

    @property
    def is_active(self) -> bool:
        """有效报名：占用"唯一报名"约束的状态。"""
        return self in (RegistrationStatus.PENDING, RegistrationStatus.APPROVED)


class PolicyType(str, Enum):
    """报名策略类型，对应 activity.policy_type 字段。"""

    DIRECT = "DIRECT"
    REVIEW = "REVIEW"
    LOTTERY = "LOTTERY"

    @property
    def label(self) -> str:
        return {
            PolicyType.DIRECT: "直接报名",
            PolicyType.REVIEW: "管理员审核",
            PolicyType.LOTTERY: "抽签录取",
        }[self]


class ActivityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Role(str, Enum):
    STUDENT = "STUDENT"
    ADMIN = "ADMIN"


@dataclass
class Student:
    student_id: str
    name: str
    role: Role = Role.STUDENT

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


@dataclass
class Activity:
    activity_id: int
    title: str
    category: str
    start_at: datetime
    location: str
    capacity: int
    policy_type: PolicyType
    status: ActivityStatus = ActivityStatus.OPEN
    created_at: Optional[datetime] = None


@dataclass
class Registration:
    registration_id: int
    activity_id: int
    student_id: str
    status: RegistrationStatus
    created_at: datetime
    updated_at: datetime


@dataclass
class Message:
    message_id: int
    student_id: str
    activity_id: Optional[int]
    content: str
    created_at: datetime
    is_read: bool = False


@dataclass(frozen=True)
class ActivityStatistics:
    """按活动维度的报名统计（P2-F08）。"""

    activity_id: int
    capacity: int
    approved: int
    pending: int
    rejected: int
    cancelled: int

    @property
    def remaining(self) -> int:
        return max(self.capacity - self.approved, 0)

    @property
    def is_full(self) -> bool:
        return self.approved >= self.capacity


@dataclass(frozen=True)
class Result:
    """服务层统一返回值，避免用异常表达业务失败。"""

    ok: bool
    code: str = "OK"
    message: str = ""
    data: object = field(default=None, compare=False)

    @classmethod
    def success(cls, message: str = "", data: object = None) -> "Result":
        return cls(True, "OK", message, data)

    @classmethod
    def failure(cls, code: str, message: str) -> "Result":
        return cls(False, code, message)


class ErrorCode:
    """业务错误码。与 README 的错误处理表一一对应。"""

    OK = "OK"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    STUDENT_NOT_FOUND = "STUDENT_NOT_FOUND"
    ACTIVITY_NOT_FOUND = "ACTIVITY_NOT_FOUND"
    REGISTRATION_NOT_FOUND = "REGISTRATION_NOT_FOUND"
    ACTIVITY_STARTED = "ACTIVITY_STARTED"
    ACTIVITY_CLOSED = "ACTIVITY_CLOSED"
    ACTIVITY_HAS_REGISTRATIONS = "ACTIVITY_HAS_REGISTRATIONS"
    DUPLICATE_ACTIVE = "DUPLICATE_ACTIVE"
    CAPACITY_FULL = "CAPACITY_FULL"
    INVALID_STATE = "INVALID_STATE"
    FORBIDDEN = "FORBIDDEN"
