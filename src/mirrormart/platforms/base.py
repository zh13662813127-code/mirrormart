"""平台环境抽象基类。"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import Any


class PlatformBase(ABC):
    """所有平台环境的抽象基类。"""

    @abstractmethod
    def get_feed(self, agent_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """获取该 Agent 可见的信息流内容。

        Returns:
            内容列表，每项包含 content_id, title, content, author_id, likes, comments 等字段
        """
        ...

    @abstractmethod
    def execute_action(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """执行 Agent 的行为。

        Args:
            agent_id: Agent 标识
            action: 行动指令，包含 type 字段及其他参数

        Returns:
            行为结果 + 环境变更描述
        """
        ...

    @abstractmethod
    def get_state_snapshot(self) -> dict[str, Any]:
        """获取当前平台状态快照（用于分支分叉和分析）。"""
        ...

    @abstractmethod
    def restore_state(self, snapshot: dict[str, Any]) -> None:
        """从快照恢复平台状态（用于分支分叉）。"""
        ...

    def get_metrics(self) -> dict[str, Any]:
        """获取平台级别的分析指标（可选覆盖）。"""
        return {}

    def deep_clone(self) -> "PlatformBase":
        """深拷贝平台实例（用于蒙特卡洛分支隔离）。"""
        return copy.deepcopy(self)
