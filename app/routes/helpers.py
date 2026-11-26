"""视图公共工具：登录态、权限装饰器、服务装配。"""

from __future__ import annotations

from functools import wraps
from typing import Optional

from flask import g, redirect, request, session, url_for

from ..db import get_db
from ..models import Student
from ..repositories import MessageRepository, StudentRepository
from ..services import ActivityService, RegistrationService

__all__ = [
    "current_student",
    "unread_count",
    "registration_service",
    "activity_service",
    "login_required",
    "admin_required",
]


def current_student() -> Optional[Student]:
    """每次按 session 重新取，避免在长生命周期上下文里读到过期的登录态。"""
    student_id = session.get("student_id")
    if not student_id:
        return None
    return StudentRepository(get_db()).get(student_id)


def unread_count() -> int:
    student = current_student()
    if student is None:
        return 0
    return MessageRepository(get_db()).count_unread(student.student_id)


def registration_service() -> RegistrationService:
    if "registration_service" not in g:
        g.registration_service = RegistrationService(get_db())
    return g.registration_service


def activity_service() -> ActivityService:
    if "activity_service" not in g:
        g.activity_service = ActivityService(get_db())
    return g.activity_service


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_student() is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        student = current_student()
        if student is None:
            return redirect(url_for("auth.login", next=request.path))
        if not student.is_admin:
            return "禁止访问：需要管理员权限", 403
        return view(*args, **kwargs)

    return wrapper
