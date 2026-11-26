"""领域事件与观察者机制。

约束（指导书 3.3 任务 C）：
1. 报名业务与通知写入通过事件解耦，RegistrationService 不认识任何监听器；
2. 事件在**事务提交之后**发布，通知失败不会让已合法提交的报名回滚；
3. 失败必须留痕（notify_outbox），且重复投递不产生重复通知（event_id 幂等）。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable
from uuid import uuid4

from .models import Activity, Registration, Student
from .repositories import MessageRepository, OutboxRepository

logger = logging.getLogger("campus.event")


class EventType(str, Enum):
    REGISTRATION_SUBMITTED = "REGISTRATION_SUBMITTED"
    REGISTRATION_APPROVED = "REGISTRATION_APPROVED"
    REGISTRATION_REJECTED = "REGISTRATION_REJECTED"
    REGISTRATION_CANCELLED = "REGISTRATION_CANCELLED"


@dataclass(frozen=True)
class RegistrationEvent:
    """报名相关领域事件。event_id 是通知幂等的业务键。"""

    event_id: str
    type: EventType
    registration: Registration
    activity: Activity
    student: Student

    @classmethod
    def create(
        cls,
        event_type: EventType,
        registration: Registration,
        activity: Activity,
        student: Student,
    ) -> "RegistrationEvent":
        return cls(
            event_id=uuid4().hex,
            type=event_type,
            registration=registration,
            activity=activity,
            student=student,
        )


class EventListener(ABC):
    """观察者接口。"""

    name: str = "listener"

    @abstractmethod
    def handle(self, event: RegistrationEvent) -> None:
        """处理事件。抛异常表示本次投递失败。"""


class EventPublisher(ABC):
    """被观察者接口：订阅 + 发布。"""

    @abstractmethod
    def subscribe(self, event_type: EventType, listener: EventListener) -> None: ...

    @abstractmethod
    def publish(self, event: RegistrationEvent) -> None: ...


class SimpleEventBus(EventPublisher):
    """同步事件总线：隔离每个监听器的失败，并写入投递流水。"""

    def __init__(
        self,
        outbox: OutboxRepository,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._listeners: dict[EventType, list[EventListener]] = {}
        self._outbox = outbox
        self._clock = clock

    def subscribe(self, event_type: EventType, listener: EventListener) -> None:
        self._listeners.setdefault(event_type, []).append(listener)

    def publish(self, event: RegistrationEvent) -> None:
        for listener in self._listeners.get(event.type, []):
            try:
                listener.handle(event)
            except Exception as exc:  # 单个通知失败不影响其它监听器与主事务
                logger.warning(
                    "listener %s failed on %s: %s", listener.name, event.event_id, exc
                )
                self._outbox.record(
                    event.event_id, listener.name, "FAILED", str(exc), self._clock()
                )
            else:
                self._outbox.record(
                    event.event_id, listener.name, "SENT", None, self._clock()
                )


class InAppNotificationListener(EventListener):
    """站内消息监听器：把事件转成 message 表的一行。"""

    name = "in_app"

    TEMPLATES = {
        EventType.REGISTRATION_SUBMITTED: "你已提交《{title}》的报名申请，正在等待管理员审核。",
        EventType.REGISTRATION_APPROVED: "报名成功：《{title}》的报名已通过。",
        EventType.REGISTRATION_REJECTED: "很遗憾：《{title}》的报名未通过审核。",
        EventType.REGISTRATION_CANCELLED: "你已取消《{title}》的报名。",
    }

    def __init__(
        self,
        messages: MessageRepository,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._messages = messages
        self._clock = clock

    def handle(self, event: RegistrationEvent) -> None:
        content = self.TEMPLATES[event.type].format(title=event.activity.title)
        self._messages.add(
            event_id=event.event_id,
            student_id=event.student.student_id,
            activity_id=event.activity.activity_id,
            content=content,
            now=self._clock(),
        )
        self._messages.conn.commit()


class AuditLogListener(EventListener):
    """审计监听器：只写日志，用于演示"一个事件多个观察者"。"""

    name = "audit"

    def __init__(self, sink: logging.Logger | None = None) -> None:
        self._log = sink or logging.getLogger("campus.audit")

    def handle(self, event: RegistrationEvent) -> None:
        self._log.info(
            "reg=%s activity=%s student=%s status=%s",
            event.registration.registration_id,
            event.activity.activity_id,
            event.student.student_id,
            event.registration.status.value,
        )


class EmailNotificationListener(EventListener):
    """CR-02 新增：邮件通知渠道。

    只新增一个观察者，报名业务代码一行未改（OCP）。真正的投递由后台任务
    消费 email_outbox 完成，这里只落库。
    """

    name = "email"

    SUBJECTS = {
        EventType.REGISTRATION_SUBMITTED: "报名申请已提交",
        EventType.REGISTRATION_APPROVED: "报名结果：已通过",
        EventType.REGISTRATION_REJECTED: "报名结果：未通过",
        EventType.REGISTRATION_CANCELLED: "报名已取消",
    }

    def __init__(self, conn, clock: Callable[[], datetime] = datetime.now) -> None:
        self._conn = conn
        self._clock = clock

    def handle(self, event: RegistrationEvent) -> None:
        address = f"{event.student.student_id}@campus.edu.cn"
        subject = self.SUBJECTS[event.type]
        body = InAppNotificationListener.TEMPLATES[event.type].format(
            title=event.activity.title
        )
        self._conn.execute(
            """INSERT OR IGNORE INTO email_outbox
               (event_id, student_id, address, subject, body, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.student.student_id,
                address,
                subject,
                body,
                self._clock().isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()


def build_event_bus(
    conn,
    clock: Callable[[], datetime] = datetime.now,
    with_audit: bool = True,
) -> SimpleEventBus:
    """装配事件总线：订阅关系集中在一处，便于替换与扩展。"""
    bus = SimpleEventBus(OutboxRepository(conn), clock=clock)
    notification = InAppNotificationListener(MessageRepository(conn), clock=clock)
    email = EmailNotificationListener(conn, clock=clock)
    for event_type in EventType:
        bus.subscribe(event_type, notification)
        bus.subscribe(event_type, email)
    if with_audit:
        audit = AuditLogListener()
        for event_type in EventType:
            bus.subscribe(event_type, audit)
    return bus
