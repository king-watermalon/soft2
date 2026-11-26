"""CampusEvent 增量扩展层 v2（CR-01 年级限定报名 / CR-02 模拟邮件通知）。

本包的存在理由
--------------
实验二的初始版本（``app/``）已经通过验收并打上 ``baseline-v1`` 标签。
本轮变更的约束是"遵循开闭原则、增量修改、不修改原有代码"：

* **封闭修改**：``app/`` 下任何文件一行都不改，包括 ``wsgi.py``。
* **开放扩展**：新增本包与新的组合根 ``app_v2.py``，用继承、组合与
  事件订阅把新规则、新渠道挂到既有系统上。

文件命名约定
------------
本轮所有新增文件统一用 ``_v2``（代码）/ ``-v2``（文档、模板）后缀，
便于与初始版本区分、也便于按文件审阅变更范围。

两个例外，属框架硬约束，无法改名：

* ``ext_v2/__init__.py`` —— Python 包入口文件名固定；
* ``tests/conftest.py`` —— pytest 的 fixture 文件必须叫这个名字。
  该文件内容是**恢复初始版本被误删的原文件**，不属于本轮新增功能。

扩展点一览
----------
============================  ==========================================  ================================
需求                          原系统的扩展缝隙                            本包的落点
============================  ==========================================  ================================
CR-01 学生年级字段            ``student`` 表无 ``grade`` 列               ``schema_v2.migrate()`` 加列
CR-01 活动年级限定            ``activity`` 表无相关列                     ``schema_v2.migrate()`` 加列
CR-01 年级准入校验            ``RegistrationService.register``            ``services_v2.GradeAwareRegistrationService``
CR-01 年级限定活动管理        原管理页表单固定三种报名方式                 ``routes_v2`` 新增管理页
CR-02 模拟邮件投递            ``EventListener`` 观察者接口                ``email_v2.MockEmailNotificationListener``
CR-02 邮件投递留痕            原 ``email_outbox`` 只入队不投递             ``email_v2.MockEmailSender`` + ``email_delivery`` 表
CR-02 服务装配                ``helpers`` 用 ``g`` 做请求级缓存           ``bootstrap_v2`` 的 ``before_request`` 预置
============================  ==========================================  ================================

启动方式
--------
开发：``python app_v2.py``
部署：``gunicorn -w 1 --threads 4 app_v2:app``
（SQLite 单写者，worker 必须为 1，见 README 第 8 节。）
"""

from __future__ import annotations

__all__ = ["install", "create_ext_app"]

from .bootstrap_v2 import install
from .factory_v2 import create_ext_app
