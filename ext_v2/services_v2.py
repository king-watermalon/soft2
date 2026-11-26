"""CR-01 / CR-02 的服务层扩展 v2：用子类叠加，父类核心流程一行不改。

为什么是子类，而不是装饰器或猴子补丁
------------------------------------
``helpers.registration_service()`` 内部是 ``RegistrationService(get_db())``，
既没有依赖注入参数，也没有可注册的工厂。想在不改它的前提下换实现，
只有三条路：

1. **运行时猴子补丁**（改 ``helpers.registration_service`` 或类的方法）。
   技术上可行，但会污染全局模块状态，测试之间互相干扰，且"什么时候被
   打过补丁"完全不可见 —— 不采用。
2. **装饰器包装**（``LoggingRegistrationService(delegate)``）。
   调用方拿到的仍是 ``RegistrationService`` 的鸭子类型，可行；但装饰器
   必须转发全部方法，父类新增方法时会静默失效，且无法复用父类的内部
   状态（``self.students`` 等）。
3. **子类**（本实现）。``register()`` 只增加一个前置判定再 ``super()``：
   父类的"公共不变量 → 策略决策 → 事务 → 事件"顺序、异常处理、错误码
   全部继承，不会漂移。子类同时天然继承父类的属性，扩展方法可以复用。

于是扩展只发生在**组合根**：``bootstrap_v2.install()`` 注册的
``before_request`` 把子类实例预先放进 ``flask.g``，
``helpers.registration_service()`` 的 ``if "registration_service" not in g``
判断会直接命中缓存并返回它。这条缝隙是原代码里的既有写法（请求级缓存），
不是我们凿出来的。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Callable, Optional

from app.events import EventPublisher
from app.models import Result
from app.policies import PolicyFactory
from app.services import ActivityService, RegistrationService

from .bus_v2 import build_extended_bus
from .email_v2 import MockEmailSender
from .grade_v2 import (
    ErrorCodeExt,
    GradeLimitError,
    GradeRule,
    GradeRuleRepository,
)


class GradeAwareRegistrationService(RegistrationService):
    """在 ``register()`` 前叠加年级准入规则。

    行为等价性
    ----------
    * 活动与学生都存在、活动未设年级限定 → 与父类**完全一致**（直接透传）。
    * 活动设了年级限定 → 先判年级；通过后仍走父类完整流程，名额、开始
      时间、重复报名等公共约束照旧生效（它们写在父类里，没有旁路）。
    * 学生或活动不存在 → 交给父类报 ``STUDENT_NOT_FOUND`` /
      ``ACTIVITY_NOT_FOUND``，错误码语义不变。

    提示优先级
    ----------
    年级判定放在公共约束之前：年级限定是"这个活动面向谁"的资格问题，
    不满足时给"年级不符"比给"名额已满"更准确、更可行动。这是本轮唯一的
    可感知行为差异，已记入变更影响分析（``docs/06-CR01-CR02-变更影响分析-v2.md``）。
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        publisher: Optional[EventPublisher] = None,
        clock: Callable[[], datetime] = datetime.now,
        policy_factory: Optional[PolicyFactory] = None,
        rules: Optional[GradeRuleRepository] = None,
        sender: Optional[MockEmailSender] = None,
    ) -> None:
        self.rules = rules or GradeRuleRepository(conn)
        self.mail_sender = sender or MockEmailSender(conn, clock=clock)
        publisher = publisher or build_extended_bus(
            conn, clock=clock, sender=self.mail_sender
        )
        super().__init__(
            conn, publisher=publisher, clock=clock, policy_factory=policy_factory
        )

    # ---------- 用例：报名 ----------

    def register(self, student_id: str, activity_id: int) -> Result:
        blocked = self.check_grade_eligibility(student_id, activity_id)
        if blocked is not None:
            return blocked
        return super().register(student_id, activity_id)

    # ---------- 扩展查询（视图与管理页使用） ----------

    def check_grade_eligibility(
        self, student_id: str, activity_id: int
    ) -> Optional[Result]:
        """返回 ``None`` 表示可以继续；返回 ``Result`` 表示应直接拒绝。"""
        activity = self.activities.get(activity_id)
        if activity is None:
            return None  # 交给父类报"活动不存在"
        if self.students.get(student_id) is None:
            return None  # 交给父类报"学生不存在"

        rule = self.rules.of_activity(activity_id)
        if rule is None:
            return None

        grade = self.rules.grade_of_student(student_id)
        if rule.allows(grade):
            return None

        code = (
            ErrorCodeExt.GRADE_NOT_REGISTERED
            if grade is None
            else ErrorCodeExt.GRADE_NOT_ELIGIBLE
        )
        return Result.failure(code, rule.rejection_message(grade))

    def eligibility_of(self, student_id: str, activity_id: int) -> Optional[GradeRule]:
        """给页面渲染用：返回该活动的年级规则（无则 ``None``）。"""
        return self.rules.of_activity(activity_id)


class GradeAwareActivityService(ActivityService):
    """活动管理的扩展：为既有活动设置/取消年级限定。

    刻意**不覆盖** ``create``：父类签名固定，覆盖会牵动所有调用方。
    改为新增 ``create_limited()``（复用父类 ``create`` 后再补写扩展列）
    与 ``set_grade_limit()``，父类方法原样可用。
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        super().__init__(conn, clock=clock)
        self.rules = GradeRuleRepository(conn)

    def create_limited(
        self,
        title: str,
        category: str,
        start_at,
        location: str,
        capacity,
        policy_type,
        grade_limit,
    ) -> Result:
        """创建活动并同时设置年级限定（``grade_limit`` 可为 ``None``）。"""
        try:
            rule = GradeRule.parse(grade_limit)
        except GradeLimitError as exc:
            return Result.failure(ErrorCodeExt.GRADE_LIMIT_INVALID, str(exc))

        created = super().create(
            title=title,
            category=category,
            start_at=start_at,
            location=location,
            capacity=capacity,
            policy_type=policy_type,
        )
        if not created.ok:
            return created
        if rule is not None:
            self.rules.set_for_activity(created.data, rule)
            self.conn.commit()
        return Result.success("活动已创建（含年级限定）", data=created.data)

    def set_grade_limit(self, activity_id: int, grade_limit) -> Result:
        if self.activities.get(activity_id) is None:
            return Result.failure("ACTIVITY_NOT_FOUND", "活动不存在")
        try:
            rule = GradeRule.parse(grade_limit)
        except GradeLimitError as exc:
            return Result.failure(ErrorCodeExt.GRADE_LIMIT_INVALID, str(exc))
        self.rules.set_for_activity(activity_id, rule)
        self.conn.commit()
        if rule is None:
            return Result.success("已取消年级限定，该活动恢复为不限年级")
        return Result.success(f"已更新年级限定：{rule.label}")

    def set_student_grade(self, student_id: str, grade) -> Result:
        if not self._student_exists(student_id):
            return Result.failure("STUDENT_NOT_FOUND", "学生不存在")
        try:
            value = None if grade in (None, "", "None") else int(grade)
            self.rules.set_grade_of_student(student_id, value)
        except GradeLimitError as exc:
            return Result.failure(ErrorCodeExt.GRADE_LIMIT_INVALID, str(exc))
        except (TypeError, ValueError):
            return Result.failure(ErrorCodeExt.GRADE_LIMIT_INVALID, "年级必须取 1—4")
        self.conn.commit()
        return Result.success("已更新年级" if value is not None else "已清除年级信息")

    def grade_limit_text(self, activity_id: int) -> str:
        raw = self.rules.raw_of_activity(activity_id)
        return "" if raw is None else raw

    # ---------- 内部 ----------

    def _student_exists(self, student_id: str) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM student WHERE student_id = ?", (student_id,)
        ).fetchone()
        return int(row["c"]) > 0
