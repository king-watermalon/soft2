"""报名策略：把"变化的报名规则"隔离成稳定抽象。

稳定点：RegistrationPolicy 接口只回答一件事——本次申请应该置为何种状态。
变化点：直接报名 / 审核报名 / （变更后）抽签报名。

注意：名额检查、重复报名检查等"不变量"不在策略里，见 RegistrationService。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from .models import Activity, PolicyType, RegistrationStatus, Student


@dataclass(frozen=True)
class PolicyDecision:
    """策略的返回值：只要状态与理由，不产生副作用、不写数据库。"""

    status: RegistrationStatus
    reason: str


class RegistrationPolicy(ABC):
    """报名策略接口。新增策略只需实现本接口并在工厂登记一行。"""

    policy_type: PolicyType

    @property
    def label(self) -> str:  # pragma: no cover - 供 UI 展示
        return self.policy_type.label

    @abstractmethod
    def decide(
        self, activity: Activity, student: Student, approved_count: int
    ) -> PolicyDecision:
        """决定本次申请的初始状态。approved_count 为当前"已通过"人数。"""


class DirectRegistrationPolicy(RegistrationPolicy):
    """直接报名：名额充足时立即通过。"""

    policy_type = PolicyType.DIRECT

    def decide(self, activity, student, approved_count) -> PolicyDecision:
        return PolicyDecision(RegistrationStatus.APPROVED, "符合条件，报名直接通过")


class ReviewRegistrationPolicy(RegistrationPolicy):
    """审核报名：先进入待审核，由管理员批准或拒绝。"""

    policy_type = PolicyType.REVIEW

    def decide(self, activity, student, approved_count) -> PolicyDecision:
        return PolicyDecision(RegistrationStatus.PENDING, "申请已提交，等待管理员审核")


class LotteryRegistrationPolicy(RegistrationPolicy):
    """CR-01 新增：抽签型活动。

    报名期间所有人进入待审核队列；报名截止后由管理员触发一次抽签，
    在名额内随机录取。策略本身只决定"初始状态"，
    录取逻辑在 RegistrationService.draw_lottery()。
    """

    policy_type = PolicyType.LOTTERY

    def decide(self, activity, student, approved_count) -> PolicyDecision:
        return PolicyDecision(
            RegistrationStatus.PENDING, "已进入抽签池，录取结果由抽签决定"
        )


class PolicyFactory:
    """按 activity.policy_type 取策略实例。

    扩展点：新策略 = 新增一个类 + 在构造时多传一个实例。
    RegistrationService 不需要任何修改（OCP）。
    """

    def __init__(self, policies: Iterable[RegistrationPolicy] | None = None) -> None:
        self._registry: dict[PolicyType, RegistrationPolicy] = {}
        defaults = (
            DirectRegistrationPolicy(),
            ReviewRegistrationPolicy(),
            LotteryRegistrationPolicy(),
        )
        for policy in policies if policies is not None else defaults:
            self.register(policy)

    def register(self, policy: RegistrationPolicy) -> None:
        self._registry[policy.policy_type] = policy

    def create(self, policy_type: PolicyType) -> RegistrationPolicy:
        try:
            return self._registry[policy_type]
        except KeyError as exc:  # pragma: no cover - 防御性分支
            raise ValueError(f"未注册的报名策略: {policy_type}") from exc

    @property
    def supported(self) -> list[PolicyType]:
        return list(self._registry)
