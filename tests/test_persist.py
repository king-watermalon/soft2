"""持久化与数据一致性（C10）。"""

import sqlite3
from datetime import datetime

import pytest

from app import create_app
from app.db import get_db
from app.models import RegistrationStatus
from app.repositories import (
    ActivityRepository,
    MessageRepository,
    RegistrationRepository,
)


def test_data_survives_application_restart(app, ctx, add_activity):
    """C10：重启服务后活动、报名、通知仍然一致。"""
    activity = add_activity(capacity=5)
    assert ctx.service.register("s1", activity.activity_id).ok

    database = app.config["DATABASE"]
    restarted = create_app({"DATABASE": database, "TESTING": True})

    with restarted.app_context():
        conn = get_db()
        assert ActivityRepository(conn).get(activity.activity_id).title == activity.title

        registrations = RegistrationRepository(conn).list_by_student("s1")
        assert len(registrations) == 1
        assert registrations[0].status is RegistrationStatus.APPROVED

        assert len(MessageRepository(conn).list_by_student("s1")) == 1


def test_unique_index_blocks_second_active_registration(ctx, add_activity):
    """数据库兜底：并发下也不可能出现两条有效报名。"""
    activity = add_activity(capacity=5)
    ctx.registrations.insert(
        activity.activity_id, "s1", RegistrationStatus.APPROVED, datetime.now()
    )
    ctx.conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        ctx.registrations.insert(
            activity.activity_id, "s1", RegistrationStatus.PENDING, datetime.now()
        )
    ctx.conn.rollback()


def test_cancelled_row_does_not_block_new_application(ctx, add_activity):
    """部分唯一索引只约束 PENDING/APPROVED，CANCELLED 历史记录不冲突。"""
    activity = add_activity(capacity=5)
    first = ctx.registrations.insert(
        activity.activity_id, "s1", RegistrationStatus.CANCELLED, datetime.now()
    )
    ctx.conn.commit()

    second = ctx.service.register("s1", activity.activity_id)

    assert second.ok
    assert second.data.registration_id != first.registration_id


def test_foreign_key_rejects_unknown_activity(ctx):
    with pytest.raises(sqlite3.IntegrityError):
        ctx.registrations.insert(9999, "s1", RegistrationStatus.APPROVED, datetime.now())
    ctx.conn.rollback()
