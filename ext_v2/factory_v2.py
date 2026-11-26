"""扩展版应用工厂 v2。

单独成一文件，是为了让测试可以只导入工厂、不触发 ``app_v2`` 模块级的
应用实例创建（那会连接到默认数据库路径）。
"""

from __future__ import annotations

from flask import Flask

from app import create_app

from .bootstrap_v2 import install


def create_ext_app(config: dict | None = None) -> Flask:
    """创建并装配扩展版应用：原应用 + CR-01 / CR-02 扩展。"""
    app = create_app(config)
    install(app)
    return app
