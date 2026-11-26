"""应用工厂。

依赖装配集中在这里：视图只拿服务，服务只拿仓储与事件总线，
替换任何一层都不需要改视图。
"""

from __future__ import annotations

import os

from flask import Flask

from . import db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        DATABASE=os.environ.get("DATABASE_PATH")
        or os.path.join(BASE_DIR, "instance", "campusevent.sqlite3"),
    )
    if config:
        app.config.update(config)

    db.init_app(app)

    from .routes.admin import bp as admin_bp
    from .routes.auth import bp as auth_bp
    from .routes.student import bp as student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(admin_bp)

    @app.template_filter("dt")
    def _format_dt(value):
        return value.strftime("%Y-%m-%d %H:%M") if value else ""

    @app.context_processor
    def inject_globals():
        from .routes.helpers import current_student, unread_count

        return {"me": current_student(), "unread": unread_count()}

    with app.app_context():
        db.init_db(db.get_db())

    return app
