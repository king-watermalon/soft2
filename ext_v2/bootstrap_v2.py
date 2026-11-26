"""扩展装配 v2：把一个"原样创建"的 Flask 应用接上变更能力。

装配顺序（每一步都用官方扩展点，不触碰原有代码）
------------------------------------------------
1. ``schema_v2.migrate()``：在应用上下文里补列建表，幂等。
2. ``app.register_blueprint()``：挂上扩展管理页。
3. ``app.before_request``：把**子类实例**预先放进 ``flask.g``。

第 3 步为什么能生效
-------------------
``app/routes/helpers.py`` 里写的是：

.. code-block:: python

    def registration_service() -> RegistrationService:
        if "registration_service" not in g:
            g.registration_service = RegistrationService(get_db())
        return g.registration_service

这是原作者的**请求级缓存**写法。我们不去改它，而是在请求进入视图之前
先把 ``g.registration_service`` 填好，缓存判断自然命中，视图拿到的就是
扩展版服务。整个过程没有猴子补丁，也不存在"谁在什么时候换了实现"的
隐式状态：替换点只有一个，就是本文件的 ``_inject_services``。

若某个部署不想启用扩展，直接换回 ``wsgi:app`` 即可，两套入口并存。
"""

from __future__ import annotations

import logging

from flask import Flask, g, request

from app import db

from . import schema_v2

logger = logging.getLogger("campus.ext_v2")

#: 用来标记扩展已装配，避免重复注册蓝图。
_EXT_KEY = "campusevent_ext_v2"


def _inject_services() -> None:
    """把扩展版服务放进请求上下文。

    只为需要的请求建立服务对象：静态文件不访问数据库，直接跳过，
    避免无意义地打开连接。
    """
    if request.endpoint == "static":
        return

    from .services_v2 import GradeAwareActivityService, GradeAwareRegistrationService

    conn = db.get_db()
    if "registration_service" not in g:
        g.registration_service = GradeAwareRegistrationService(conn)
    if "activity_service" not in g:
        g.activity_service = GradeAwareActivityService(conn)


def install(
    app: Flask, *, migrate_schema: bool = True, admin_page: bool = True
) -> Flask:
    """给应用装上 CR-01 / CR-02 扩展。可重复调用。"""
    state = app.extensions.setdefault(_EXT_KEY, {})
    if state.get("installed"):
        return app

    if migrate_schema:
        with app.app_context():
            changes = schema_v2.migrate(db.get_db())
        logger.info("ext_v2 schema migrated: %s", changes)
        state["migration"] = changes

    if admin_page:
        from .routes_v2 import bp

        app.register_blueprint(bp)
        state["blueprints"] = ["ext_v2_admin"]

    app.before_request(_inject_services)
    state["installed"] = True
    return app
