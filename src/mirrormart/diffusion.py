"""社交网络扩散模型。

在每个时间步结束后，根据 Agent 之间的关注关系传播影响力：
- Agent 发布正面内容 → 关注者 purchase_intent 微增
- Agent 购买了产品 → 关注者 purchase_intent 显著增加
- 影响力衰减：间接关系（二度好友）影响更弱
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 不同行为对关注者的影响力系数
INFLUENCE_WEIGHTS: dict[str, float] = {
    "purchase": 0.12,     # 买了 → 强信号
    "review": 0.10,       # 写了好评 → 强信号
    "post": 0.06,         # 发了种草帖 → 中等
    "repost": 0.05,       # 转发 → 中等
    "quote": 0.05,        # 引用转发 → 中等
    "share": 0.05,        # 抖音分享 → 中等
    "like": 0.02,         # 点赞 → 弱信号
    "collect": 0.03,      # 收藏 → 弱信号
    "wishlist": 0.04,     # 淘宝收藏 → 弱信号
    "comment": 0.03,      # 评论 → 弱信号
    "add_cart": 0.06,     # 加购 → 中等
}


class DiffusionEngine:
    """社交网络影响力扩散引擎。"""

    def __init__(self, decay: float = 0.5, max_boost: float = 0.15) -> None:
        """初始化扩散引擎。

        Args:
            decay: 二度关系的衰减系数（一度=1.0，二度=decay）
            max_boost: 单步最大意向提升值（防止突变）
        """
        self.decay = decay
        self.max_boost = max_boost

    def propagate(
        self,
        agents: list[Any],
        step_events: list[dict[str, Any]],
        follow_graphs: dict[str, dict[str, set[str]]],
    ) -> dict[str, float]:
        """在一步结束后传播社交影响力。

        Args:
            agents: Agent 列表
            step_events: 当前步所有 Agent 的事件
            follow_graphs: 各平台的关注图 {"xiaohongshu": {agent_id: {followers}}, ...}

        Returns:
            {agent_id: intent_delta} 每个 Agent 的购买意向变化量
        """
        agent_map = {a.id: a for a in agents}
        deltas: dict[str, float] = {a.id: 0.0 for a in agents}

        for event in step_events:
            actor_id = event.get("agent_id", "")
            action_type = event.get("action", {}).get("type", "")
            platform = event.get("platform", "")

            weight = INFLUENCE_WEIGHTS.get(action_type, 0.0)
            if weight <= 0:
                continue

            # 获取该平台上关注 actor 的人
            graph = follow_graphs.get(platform, {})
            followers = self._get_followers(actor_id, graph)

            for follower_id in followers:
                if follower_id == actor_id or follower_id not in agent_map:
                    continue
                # 一度关系
                deltas[follower_id] += weight

            # 二度扩散（follower 的 follower）
            if action_type in ("purchase", "review", "post"):
                for follower_id in followers:
                    second_followers = self._get_followers(follower_id, graph)
                    for ff_id in second_followers:
                        if ff_id == actor_id or ff_id == follower_id or ff_id not in agent_map:
                            continue
                        deltas[ff_id] += weight * self.decay

        # 应用 delta，限制最大变化
        applied: dict[str, float] = {}
        for agent_id, delta in deltas.items():
            if delta <= 0:
                continue
            capped = min(delta, self.max_boost)
            agent = agent_map[agent_id]
            old_intent = agent.internal_state.get("purchase_intent", 0.0)
            new_intent = min(1.0, old_intent + capped)
            agent.internal_state["purchase_intent"] = round(new_intent, 3)
            applied[agent_id] = round(capped, 4)

        if applied:
            logger.debug("扩散影响: %d 个 Agent 意向提升", len(applied))

        return applied

    @staticmethod
    def _get_followers(agent_id: str, graph: dict[str, set[str]]) -> set[str]:
        """获取关注了 agent_id 的人（即 agent_id 的粉丝）。"""
        followers = set()
        for uid, following_set in graph.items():
            if agent_id in following_set:
                followers.add(uid)
        return followers

    @staticmethod
    def build_follow_graphs(platforms: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
        """从平台实例提取关注图。"""
        graphs: dict[str, dict[str, set[str]]] = {}
        for name, platform in platforms.items():
            following = getattr(platform, "following", None)
            if following and isinstance(following, dict):
                graphs[name] = {k: set(v) for k, v in following.items()}
        return graphs
