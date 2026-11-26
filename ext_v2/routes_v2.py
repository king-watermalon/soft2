"""扩展管理页 v2：年级限定配置 + 邮件投递记录。

刻意做成**新增蓝图**而不是改 ``admin.html`` / ``routes/admin.py``：
原有管理台的表单只认三种报名方式（DIRECT / REVIEW / LOTTERY），
年级限定是与之正交的新维度，放进新页面比塞进既有表单更清晰，
也让"关闭修改"这条约束自然成立。
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.db import get_db
from app.repositories import (
    ActivityRepository,
    RegistrationRepository,
    StudentRepository,
)
from app.routes.helpers import admin_required

from .email_v2 import MockEmailSender
from .grade_v2 import GradeRuleRepository
from .services_v2 import GradeAwareActivityService

bp = Blueprint(
    "ext_v2_admin",
    __name__,
    url_prefix="/ext",
    template_folder="templates",
)


def _activity_rows(conn):
    activities = ActivityRepository(conn).list_all()
    rules = GradeRuleRepository(conn)
    registrations = RegistrationRepository(conn)
    rows = []
    for activity in activities:
        rows.append(
            {
                "activity": activity,
                "rule": rules.of_activity(activity.activity_id),
                "stats": registrations.statistics(
                    activity.activity_id, activity.capacity
                ),
            }
        )
    return rows


def _student_rows(conn):
    students = StudentRepository(conn).list_all()
    grades = GradeRuleRepository(conn).grades_of_students()
    return [{"student": s, "grade": grades.get(s.student_id)} for s in students]


@bp.route("/")
@admin_required
def index():
    return redirect(url_for("ext_v2_admin.dashboard"))


@bp.route("/admin")
@admin_required
def dashboard():
    conn = get_db()
    sender = MockEmailSender(conn)
    return render_template(
        "ext_admin-v2.html",
        rows=_activity_rows(conn),
        students=_student_rows(conn),
        mails=sender.recent(20),
        mail_counts=sender.counts(),
    )


@bp.route("/admin/activity/<int:activity_id>/grade", methods=["POST"])
@admin_required
def set_activity_grade(activity_id: int):
    raw = (request.form.get("grade_limit") or "").strip()
    outcome = GradeAwareActivityService(get_db()).set_grade_limit(activity_id, raw)
    flash(outcome.message, "success" if outcome.ok else "error")
    return redirect(url_for("ext_v2_admin.dashboard"))


@bp.route("/admin/student/<student_id>/grade", methods=["POST"])
@admin_required
def set_student_grade(student_id: str):
    raw = (request.form.get("grade") or "").strip()
    outcome = GradeAwareActivityService(get_db()).set_student_grade(
        student_id, raw if raw else None
    )
    flash(outcome.message, "success" if outcome.ok else "error")
    return redirect(url_for("ext_v2_admin.dashboard"))
