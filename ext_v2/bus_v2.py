"""扩展版事件总线装配 v2。

为什么不直接调 ``build_event_bus()``
------------------------------------
``app.events.build_event_bus()`` 是原有装配函数，它固定挂三个监听器：
``in_app``、``email``（上一轮留下的 email_outbox 入队）、``audit``。

本轮要接入"可观测的模拟投递"，若在它的结果上再 ``subscribe`` 一个邮件
监听器，同一个业务事件会产生**两份邮件记录**（队列一份、投递一份），
违背 CR2-04 关于"不应重复生成多份相同通知"的精神，也让"邮件到底发了几封"
无法回答。

因此这里**新增一条装配路径**，而不是修改 ``build_event_bus``：

* 复用原有 ``SimpleEventBus``（异常隔离 + ``notify_outbox`` 留痕）
* 复用原有 ``InAppNotificationListener``（站内消息照旧）
* 复用原有 ``AuditLogListener``（审计日志照旧）
* 用 ``MockEmailNotificationListener`` 取代旧的 email 入队监听器

即：站内与审计是"原有能力继续运行"，邮件是"一条渠道，从入队升级为可观测
投递"。原 ``build_event_bus`` 与其测试（断言 ``in_app``/``email``/``audit``
三条流水）保持原样，不受影响——那些测试构造的是原版服务，走的是原装配。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Callable, Optional

from app.events import (
    AuditLogListener,
    EventType,
    InAppNotificationListener,
    SimpleEventBus,
)
from app.repositories import MessageRepository, OutboxRepository

from .email_v2 import EMAIL_EVENT_TYPES, MockEmailNotificationListener, MockEmailSender


def build_extended_bus(
    conn: sqlite3.Connection,
    clock: Callable[[], datetime] = datetime.now,
    sender: Optional[MockEmailSender] = None,
    with_audit: bool = True,
) -> SimpleEventBus:
    """装配扩展总线：站内 + 审计 + 模拟邮件。"""
    bus = SimpleEventBus(OutboxRepository(conn), clock=clock)

    in_app = InAppNotificationListener(MessageRepository(conn), clock=clock)
    for event_type in EventType:
        bus.subscribe(event_type, in_app)

    mail_sender = sender or MockEmailSender(conn, clock=clock)
    mail = MockEmailNotificationListener(mail_sender, clock=clock)
    for event_type in EMAIL_EVENT_TYPES:
        bus.subscribe(event_type, mail)

    if with_audit:
        audit = AuditLogListener()
        for event_type in EventType:
            bus.subscribe(event_type, audit)

    return bus
