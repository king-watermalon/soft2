"""通知解耦：失败留痕、不影响主事务、重复投递幂等（P2-F07）。"""

from datetime import datetime, timedelta

from app.db import get_db
from app.events import EventListener, EventType, RegistrationEvent, build_event_bus
from app.models import RegistrationStatus
from app.repositories import (
    ActivityRepository,
    MessageRepository,
    OutboxRepository,
    RegistrationRepository,
    StudentRepository,
)
from app.services import ActivityService, RegistrationService


class BoomListener(EventListener):
    """模拟"邮件/短信服务不可用"的监听器。"""

    name = "boom"

    def handle(self, event: RegistrationEvent) -> None:
        raise RuntimeError("邮件服务不可用")


def _new_activity(conn) -> int:
    return ActivityService(conn).create(
        title="讲座",
        category="测试",
        start_at=(datetime.now() + timedelta(days=3)).replace(microsecond=0),
        location="报告厅",
        capacity=5,
        policy_type="DIRECT",
    ).data


def test_notification_failure_does_not_rollback_registration(app):
    with app.app_context():
        conn = get_db()
        activity_id = _new_activity(conn)

        bus = build_event_bus(conn)
        for event_type in EventType:
            bus.subscribe(event_type, BoomListener())

        result = RegistrationService(conn, publisher=bus).register("s1", activity_id)

        assert result.ok
        assert result.data.status is RegistrationStatus.APPROVED
        assert RegistrationRepository(conn).get(result.data.registration_id) is not None

        # 站内消息由另一个监听器正常写入
        assert len(MessageRepository(conn).list_by_student("s1")) == 1

        failed = OutboxRepository(conn).failed()
        assert len(failed) == 1
        assert failed[0]["listener"] == "boom"
        assert "邮件服务不可用" in failed[0]["error"]


def test_successful_delivery_is_recorded_in_outbox(app):
    with app.app_context():
        conn = get_db()
        activity_id = _new_activity(conn)

        assert RegistrationService(conn).register("s1", activity_id).ok

        rows = conn.execute("SELECT * FROM notify_outbox").fetchall()
        assert {row["listener"] for row in rows} == {"in_app", "email", "audit"}
        assert all(row["status"] == "SENT" for row in rows)


def test_publishing_same_event_twice_does_not_duplicate_message(app):
    with app.app_context():
        conn = get_db()
        activity_id = _new_activity(conn)
        registration = RegistrationService(conn).register("s1", activity_id).data
        assert len(MessageRepository(conn).list_by_student("s1")) == 1

        activity = ActivityRepository(conn).get(activity_id)
        student = StudentRepository(conn).get("s1")
        event = RegistrationEvent.create(
            EventType.REGISTRATION_APPROVED, registration, activity, student
        )

        bus = build_event_bus(conn)
        bus.publish(event)
        bus.publish(event)

        # 同一个 event_id 只产生一条站内消息
        assert len(MessageRepository(conn).list_by_student("s1")) == 2

        rows = OutboxRepository(conn).list_by_event(event.event_id)
        assert len(rows) == 3  # in_app + email + audit 各一条流水
        in_app = next(row for row in rows if row["listener"] == "in_app")
        assert in_app["status"] == "SENT"
        assert in_app["retry_count"] == 1
