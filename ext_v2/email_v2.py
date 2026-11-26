"""CR-02：模拟邮件通知渠道。

与原有通知机制的关系
--------------------
原系统已有两样东西：

* ``events.SimpleEventBus`` —— 观察者总线，**已经**负责隔离监听器异常、
  把 ``SENT``/``FAILED`` 写进 ``notify_outbox``；
* ``events.EmailNotificationListener`` —— 上一轮变更留下的"邮件入队"，
  只往 ``email_outbox`` 插一行待发记录，**不投递、不记录投递结果**。

本模块补的是"投递"这一环：新增 ``MockEmailSender`` 做出可观测、可注入
故障的模拟投递，并由 ``MockEmailNotificationListener`` 以**新增订阅者**的
方式挂到总线上。原有的 ``EventListener`` 接口、``SimpleEventBus``、
``InAppNotificationListener`` 全部原样复用，一行未改。

四条硬性要求的落点
------------------
============================  ==================================================
材料要求                       实现
============================  ==================================================
站内通知继续运行               扩展总线仍订阅 ``InAppNotificationListener``
同时新增模拟邮件               ``MockEmailNotificationListener`` 订阅 APPROVED/REJECTED
记录收件人/主题/内容/状态/时间  ``email_delivery`` 表，逐列对应
邮件故障不得回滚已提交报名      ``_publish`` 在 ``commit()`` 之后调用；总线捕获异常
同一事件不重复发送两次          ``UNIQUE(event_id, address)`` + 投递前查重
============================  ==================================================
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Callable, Optional

from app.events import EventListener, EventType, RegistrationEvent

logger = logging.getLogger("campus.ext.email")


class MailDeliveryError(RuntimeError):
    """模拟投递失败。"""


#: 需要发邮件的业务事件。
#:
#: 材料表述为"报名通过、审核通过或拒绝的事件"：前两者在领域模型里都是
#: ``REGISTRATION_APPROVED``（直接报名写入即通过，审核报名由 ``approve()``
#: 置为通过），拒绝是 ``REGISTRATION_REJECTED``。取消与待提交不在要求内，
#: 因此不发邮件。
EMAIL_EVENT_TYPES = (
    EventType.REGISTRATION_APPROVED,
    EventType.REGISTRATION_REJECTED,
)

#: 邮件主题与正文模板。正文刻意与站内消息区分：邮件是"对外送达"，
#: 带上活动时间与地点更符合真实邮件语义。
EMAIL_TEMPLATES = {
    EventType.REGISTRATION_APPROVED: (
        "报名结果：已通过 - {title}",
        "你好，{name}：\n\n你报名的《{title}》已通过。\n时间：{start_at}\n地点：{location}\n\n"
        "请按时参加，如需取消请在系统中操作。",
    ),
    EventType.REGISTRATION_REJECTED: (
        "报名结果：未通过 - {title}",
        "你好，{name}：\n\n你报名的《{title}》未通过审核。\n\n如有疑问请联系活动管理员。",
    ),
}


def default_address(student_id: str) -> str:
    """学生邮箱按学号推导，演示环境不接真实邮件服务器。"""
    return f"{student_id}@campus.edu.cn"


class MockEmailSender:
    """模拟邮件发送器：不联网，只记录投递结果。

    幂等
    ----
    同一 ``event_id`` 对同一收件地址只投递一次。命中已有记录时直接返回
    历史状态，既不发第二封，也不新增第二行——对应 CR2-04"重复提交同一
    业务动作不应重复生成多份相同通知"。

    故障注入
    --------
    ``fail_predicate`` 收到收件地址，返回 ``True`` 表示本次投递失败。
    失败时先落一条 ``FAILED`` 记录（含错误原因），再把异常抛给调用方，
    由 ``SimpleEventBus`` 写入 ``notify_outbox`` —— 于是"错误有日志"
    在投递流水与通知流水两处都能查到。
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], datetime] = datetime.now,
        fail_predicate: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.conn = conn
        self._clock = clock
        self._fail_predicate = fail_predicate

    # ---------- 对外 ----------

    def send(
        self,
        *,
        event_id: str,
        student_id: str,
        address: str,
        subject: str,
        body: str,
    ) -> str:
        """投递一封模拟邮件，返回最终状态（``SENT`` / ``FAILED``）。"""
        previous = self.existing_status(event_id, address)
        if previous is not None:
            logger.debug("skip duplicated mail event=%s addr=%s", event_id, address)
            return previous

        try:
            self._deliver(address, subject, body)
        except Exception as exc:
            self._record(event_id, student_id, address, subject, body, "FAILED", str(exc))
            raise
        self._record(event_id, student_id, address, subject, body, "SENT", None)
        return "SENT"

    def existing_status(self, event_id: str, address: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT status FROM email_delivery WHERE event_id = ? AND address = ?",
            (event_id, address),
        ).fetchone()
        return None if row is None else row["status"]

    # ---------- 查询（供管理页与测试使用） ----------

    def recent(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM email_delivery ORDER BY delivery_id DESC LIMIT ?", (limit,)
        ).fetchall()

    def by_event(self, event_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM email_delivery WHERE event_id = ? ORDER BY delivery_id",
            (event_id,),
        ).fetchall()

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS c FROM email_delivery GROUP BY status"
        ).fetchall()
        return {row["status"]: int(row["c"]) for row in rows}

    # ---------- 内部 ----------

    def _deliver(self, address: str, subject: str, body: str) -> None:
        """真正的"发送"动作。演示环境里只做故障判定。"""
        if self._fail_predicate is not None and self._fail_predicate(address):
            raise MailDeliveryError(f"模拟邮件投递失败：{address} 不可达")
        logger.info("mail sent to=%s subject=%s", address, subject)

    def _record(
        self,
        event_id: str,
        student_id: str,
        address: str,
        subject: str,
        body: str,
        status: str,
        error: Optional[str],
    ) -> None:
        self.conn.execute(
            """INSERT INTO email_delivery
               (event_id, student_id, address, subject, body, status, error, attempted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_id, address) DO UPDATE SET
                   status = excluded.status,
                   error = excluded.error,
                   attempted_at = excluded.attempted_at""",
            (
                event_id,
                student_id,
                address,
                subject,
                body,
                status,
                error,
                self._clock().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()


class MockEmailNotificationListener(EventListener):
    """把报名结果事件转成模拟邮件。

    只做"事件 → 邮件"的翻译与投递调用，不碰业务状态、不提交报名事务，
    因此投递失败时（异常向上抛给总线）报名记录已经提交过了，
    对应材料"邮件发送故障必须记录错误，但不得错误回滚已成功提交的报名"。
    """

    name = "mock_email"

    def __init__(
        self,
        sender: MockEmailSender,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._sender = sender
        self._clock = clock

    def handle(self, event: RegistrationEvent) -> None:
        template = EMAIL_TEMPLATES.get(event.type)
        if template is None:  # 不在需求范围内的事件直接忽略
            return
        subject_tpl, body_tpl = template
        activity = event.activity
        fields = {
            "title": activity.title,
            "name": event.student.name,
            "start_at": activity.start_at.strftime("%Y-%m-%d %H:%M"),
            "location": activity.location or "（未填写）",
        }
        self._sender.send(
            event_id=event.event_id,
            student_id=event.student.student_id,
            address=default_address(event.student.student_id),
            subject=subject_tpl.format(**fields),
            body=body_tpl.format(**fields),
        )
