"""登录与登出。演示账号见 seed.py，不做注册与复杂权限体系（附录 B.1）。"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..db import get_db
from ..repositories import StudentRepository

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str | None:
    """只允许站内相对跳转，避免开放重定向。"""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    student_id = ""
    if request.method == "POST":
        student_id = (request.form.get("student_id") or "").strip()
        password = request.form.get("password") or ""
        student = StudentRepository(get_db()).authenticate(student_id, password)
        if student is None:
            flash("账号或密码错误", "error")
            return render_template("login.html", student_id=student_id), 401
        session.clear()
        session["student_id"] = student.student_id
        flash(f"欢迎回来，{student.name}", "success")
        return redirect(
            _safe_next(request.form.get("next"))
            or (url_for("admin.index") if student.is_admin else url_for("student.index"))
        )
    return render_template("login.html", student_id=student_id, next=request.args.get("next", ""))


@bp.route("/logout")
def logout():
    session.clear()
    flash("已退出登录", "info")
    return redirect(url_for("student.index"))
