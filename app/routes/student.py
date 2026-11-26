"""学生端视图：浏览活动、报名、取消、查看我的报名与站内消息。"""

from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..db import get_db
from ..repositories import ActivityRepository, MessageRepository, RegistrationRepository
from .helpers import current_student, login_required, registration_service

bp = Blueprint("student", __name__)


def _cards(activities):
    """活动列表视图模型：活动 + 统计 + 我的有效报名。"""
    service = registration_service()
    me = current_student()
    repository = RegistrationRepository(get_db())
    cards = []
    for activity in activities:
        cards.append(
            {
                "activity": activity,
                "stats": service.statistics(activity.activity_id),
                "mine": repository.find_active(activity.activity_id, me.student_id)
                if me
                else None,
            }
        )
    return cards


@bp.route("/")
def index():
    keyword = (request.args.get("q") or "").strip()
    activities = ActivityRepository(get_db()).list_all(keyword)
    return render_template(
        "index.html", cards=_cards(activities), keyword=keyword, now=datetime.now()
    )


@bp.route("/activity/<int:activity_id>")
def detail(activity_id: int):
    activity = ActivityRepository(get_db()).get(activity_id)
    if activity is None:
        return render_template("404.html", message="活动不存在"), 404

    me = current_student()
    history = []
    active = None
    if me is not None:
        history = [
            registration
            for registration in RegistrationRepository(get_db()).list_by_student(me.student_id)
            if registration.activity_id == activity_id
        ]
        active = next((r for r in history if r.status.is_active), None)

    return render_template(
        "activity.html",
        activity=activity,
        stats=registration_service().statistics(activity_id),
        history=history,
        active=active,
        now=datetime.now(),
    )


@bp.route("/activity/<int:activity_id>/register", methods=["POST"])
@login_required
def register(activity_id: int):
    result = registration_service().register(current_student().student_id, activity_id)
    flash(result.message, "success" if result.ok else "error")
    return redirect(url_for("student.detail", activity_id=activity_id))


@bp.route("/registration/<int:registration_id>/cancel", methods=["POST"])
@login_required
def cancel(registration_id: int):
    result = registration_service().cancel(registration_id, current_student().student_id)
    flash(result.message, "success" if result.ok else "error")
    return redirect(url_for("student.my_registrations"))


@bp.route("/my")
@login_required
def my_registrations():
    me = current_student()
    repository = RegistrationRepository(get_db())
    activity_repository = ActivityRepository(get_db())
    rows = []
    for registration in repository.list_by_student(me.student_id):
        rows.append(
            {
                "registration": registration,
                "activity": activity_repository.get(registration.activity_id),
            }
        )
    return render_template("my.html", rows=rows)


@bp.route("/messages")
@login_required
def messages():
    me = current_student()
    repository = MessageRepository(get_db())
    items = repository.list_by_student(me.student_id)
    repository.mark_all_read(me.student_id)
    get_db().commit()
    return render_template("messages.html", items=items)
