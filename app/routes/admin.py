"""管理端视图：活动管理（P2-F01）、审批（P2-F05）、统计（P2-F08）。"""

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..db import get_db
from ..repositories import (
    ActivityRepository,
    RegistrationRepository,
    StudentRepository,
)
from .helpers import activity_service, admin_required, registration_service

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@admin_required
def index():
    activities = ActivityRepository(get_db()).list_all()
    service = registration_service()
    students = StudentRepository(get_db())

    rows = [
        {"activity": activity, "stats": service.statistics(activity.activity_id)}
        for activity in activities
    ]
    pending = [
        {
            "registration": registration,
            "activity": activity,
            "student": students.get(registration.student_id),
        }
        for activity in activities
        for registration in service.pending_of(activity.activity_id)
    ]
    return render_template("admin.html", rows=rows, pending=pending)


@bp.route("/activity/new", methods=["GET", "POST"])
@admin_required
def create_activity():
    if request.method == "POST":
        result = activity_service().create(
            title=request.form.get("title"),
            category=request.form.get("category"),
            start_at=request.form.get("start_at"),
            location=request.form.get("location"),
            capacity=request.form.get("capacity"),
            policy_type=request.form.get("policy_type"),
        )
        flash(result.message, "success" if result.ok else "error")
        if result.ok:
            return redirect(url_for("admin.index"))
        return render_template("admin_form.html", activity=None, form=request.form), 400
    return render_template("admin_form.html", activity=None, form={})


@bp.route("/activity/<int:activity_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_activity(activity_id: int):
    activity = ActivityRepository(get_db()).get(activity_id)
    if activity is None:
        return render_template("404.html", message="活动不存在"), 404

    if request.method == "POST":
        result = activity_service().update(
            activity_id=activity_id,
            title=request.form.get("title"),
            category=request.form.get("category"),
            start_at=request.form.get("start_at"),
            location=request.form.get("location"),
            capacity=request.form.get("capacity"),
            policy_type=request.form.get("policy_type"),
        )
        flash(result.message, "success" if result.ok else "error")
        if result.ok:
            return redirect(url_for("admin.detail", activity_id=activity_id))
        return (
            render_template("admin_form.html", activity=activity, form=request.form),
            400,
        )

    return render_template("admin_form.html", activity=activity, form={})


@bp.route("/activity/<int:activity_id>/delete", methods=["POST"])
@admin_required
def delete_activity(activity_id: int):
    result = activity_service().delete(activity_id)
    flash(result.message, "success" if result.ok else "error")
    return redirect(url_for("admin.index"))


@bp.route("/activity/<int:activity_id>/close", methods=["POST"])
@admin_required
def close_activity(activity_id: int):
    result = activity_service().close(activity_id)
    flash(result.message, "success" if result.ok else "error")
    return redirect(url_for("admin.detail", activity_id=activity_id))


@bp.route("/activity/<int:activity_id>/draw", methods=["POST"])
@admin_required
def draw_lottery(activity_id: int):
    result = registration_service().draw_lottery(activity_id)
    flash(result.message, "success" if result.ok else "error")
    return redirect(url_for("admin.detail", activity_id=activity_id))


@bp.route("/activity/<int:activity_id>")
@admin_required
def detail(activity_id: int):
    activity = ActivityRepository(get_db()).get(activity_id)
    if activity is None:
        return render_template("404.html", message="活动不存在"), 404

    repository = RegistrationRepository(get_db())
    students = StudentRepository(get_db())
    registrations = [
        {"registration": registration, "student": students.get(registration.student_id)}
        for registration in repository.list_by_activity(activity_id)
    ]
    return render_template(
        "admin_activity.html",
        activity=activity,
        stats=registration_service().statistics(activity_id),
        registrations=registrations,
    )


@bp.route("/registration/<int:registration_id>/approve", methods=["POST"])
@admin_required
def approve(registration_id: int):
    result = registration_service().approve(registration_id)
    flash(result.message, "success" if result.ok else "error")
    return redirect(url_for("admin.index"))


@bp.route("/registration/<int:registration_id>/reject", methods=["POST"])
@admin_required
def reject(registration_id: int):
    result = registration_service().reject(registration_id)
    flash(result.message, "success" if result.ok else "error")
    return redirect(url_for("admin.index"))
