"""KOL 影响力追踪器。

追踪 KOL 内容的互动表现和转化归因，计算各 KOL 的 ROI 指标。
核心逻辑：
- 记录每个 KOL 的内容及其互动数据
- 追踪 Agent 的浏览→购买路径，归因到影响该决策的 KOL 内容
- 计算曝光→互动→转化的漏斗
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# KOL 类型的默认成本（模拟，用于 ROI 计算）
DEFAULT_KOL_COSTS: dict[str, float] = {
    "kol_beauty": 5000,      # 美妆 KOL
    "kol_skincare": 8000,    # 护肤专家 KOL
    "kol_lifestyle": 3000,   # 生活方式 KOL
    "brand_official": 0,     # 品牌官方（自有内容）
}


class KOLTracker:
    """KOL 影响力追踪器。"""

    def __init__(self, product_price: float = 59.0) -> None:
        """初始化 KOL 追踪器。

        Args:
            product_price: 主产品价格（用于计算转化价值）
        """
        self.product_price = product_price
        # KOL 内容注册表: {content_id: {"author_id", "platform", "title", ...}}
        self.kol_contents: dict[str, dict[str, Any]] = {}
        # KOL 互动统计: {author_id: {"views": int, "likes": int, ...}}
        self.kol_stats: dict[str, dict[str, int]] = {}
        # Agent 曝光记录: {agent_id: [content_id, ...]}（按时间顺序）
        self.agent_exposures: dict[str, list[str]] = {}
        # 转化归因: {agent_id: {"attributed_kol", "content_id", "step"}}
        self.conversions: list[dict[str, Any]] = {}
        # KOL 成本配置
        self.kol_costs: dict[str, float] = dict(DEFAULT_KOL_COSTS)

    def register_content(
        self,
        content_id: str,
        author_id: str,
        platform: str,
        title: str = "",
        content_type: str = "post",
    ) -> None:
        """注册一条 KOL 内容。

        Args:
            content_id: 内容 ID（帖子/视频 ID）
            author_id: 作者 ID（KOL 标识）
            platform: 平台名
            title: 标题
            content_type: 内容类型（post/video/weibo）
        """
        if not self._is_kol(author_id):
            return

        self.kol_contents[content_id] = {
            "author_id": author_id,
            "platform": platform,
            "title": title,
            "content_type": content_type,
        }

        if author_id not in self.kol_stats:
            self.kol_stats[author_id] = {
                "content_count": 0,
                "total_views": 0,
                "total_likes": 0,
                "total_comments": 0,
                "total_reposts": 0,
                "total_shares": 0,
                "conversions": 0,
            }
        self.kol_stats[author_id]["content_count"] += 1

    def track_interaction(self, event: dict[str, Any]) -> None:
        """追踪与 KOL 内容的互动事件。

        Args:
            event: 引擎事件字典
        """
        action = event.get("action", {})
        action_type = action.get("type", "")
        target_id = action.get("target_id", "")
        agent_id = event.get("agent_id", "")

        # 检查目标是否是 KOL 内容
        if target_id and target_id in self.kol_contents:
            kol_info = self.kol_contents[target_id]
            author_id = kol_info["author_id"]
            stats = self.kol_stats.get(author_id, {})

            # 记录 Agent 曝光
            if agent_id not in self.agent_exposures:
                self.agent_exposures[agent_id] = []
            if target_id not in self.agent_exposures[agent_id]:
                self.agent_exposures[agent_id].append(target_id)

            # 更新互动统计
            if action_type in ("like",):
                stats["total_likes"] = stats.get("total_likes", 0) + 1
            elif action_type in ("comment", "quote"):
                stats["total_comments"] = stats.get("total_comments", 0) + 1
            elif action_type in ("repost", "share"):
                stats["total_reposts"] = stats.get("total_reposts", 0) + 1
                stats["total_shares"] = stats.get("total_shares", 0) + 1
            elif action_type in ("view", "watch", "browse"):
                stats["total_views"] = stats.get("total_views", 0) + 1
            elif action_type == "collect":
                stats["total_likes"] = stats.get("total_likes", 0) + 1

        # 追踪浏览行为（feed 曝光归因）
        if action_type in ("browse", "view", "watch") and not target_id:
            # 通过 thinking 中的内容推断曝光的 KOL 内容
            thinking = event.get("thinking", "")
            for cid, info in self.kol_contents.items():
                title = info.get("title", "")
                if title and title[:6] in thinking:
                    if agent_id not in self.agent_exposures:
                        self.agent_exposures[agent_id] = []
                    if cid not in self.agent_exposures[agent_id]:
                        self.agent_exposures[agent_id].append(cid)

        # 追踪购买转化 → 归因到最近曝光的 KOL
        if action_type == "purchase" and agent_id:
            self._attribute_conversion(agent_id, event.get("branch_step", 0))

    def _attribute_conversion(self, agent_id: str, step: int) -> None:
        """将购买行为归因到最近曝光的 KOL 内容（末次归因模型）。"""
        exposures = self.agent_exposures.get(agent_id, [])
        if not exposures:
            return

        # 末次归因：最后曝光的 KOL 内容获得归因
        last_content_id = exposures[-1]
        kol_info = self.kol_contents.get(last_content_id)
        if not kol_info:
            return

        author_id = kol_info["author_id"]
        self.conversions.append({
            "agent_id": agent_id,
            "attributed_kol": author_id,
            "content_id": last_content_id,
            "step": step,
            "model": "last_touch",
        })

        if author_id in self.kol_stats:
            self.kol_stats[author_id]["conversions"] += 1

        logger.debug("转化归因: %s → KOL %s (内容 %s)", agent_id, author_id, last_content_id)

    def get_kol_performance(self) -> list[dict[str, Any]]:
        """获取各 KOL 的表现排行。

        Returns:
            按互动率排序的 KOL 表现列表
        """
        results = []
        for author_id, stats in self.kol_stats.items():
            views = stats.get("total_views", 0)
            likes = stats.get("total_likes", 0)
            comments = stats.get("total_comments", 0)
            reposts = stats.get("total_reposts", 0)
            conversions = stats.get("conversions", 0)
            content_count = stats.get("content_count", 0)

            total_engagement = likes + comments + reposts
            engagement_rate = round(total_engagement / max(views, 1), 3)

            # ROI 计算
            cost = self.kol_costs.get(author_id, 2000)
            revenue = conversions * self.product_price
            roi = round((revenue - cost) / max(cost, 1), 2) if cost > 0 else 0.0

            results.append({
                "kol_id": author_id,
                "content_count": content_count,
                "views": views,
                "likes": likes,
                "comments": comments,
                "reposts": reposts,
                "total_engagement": total_engagement,
                "engagement_rate": engagement_rate,
                "conversions": conversions,
                "conversion_rate": round(conversions / max(views, 1), 3),
                "cost": cost,
                "revenue": revenue,
                "roi": roi,
            })

        return sorted(results, key=lambda x: x["total_engagement"], reverse=True)

    def get_funnel(self) -> dict[str, Any]:
        """获取 KOL 整体的曝光→互动→转化漏斗。"""
        total_exposures = sum(len(v) for v in self.agent_exposures.values())
        total_engaged_agents = sum(
            1 for exposures in self.agent_exposures.values()
            if len(exposures) > 1  # 多次曝光 = 有兴趣
        )
        total_conversions = len(self.conversions)
        total_reached = len(self.agent_exposures)

        return {
            "reached_agents": total_reached,
            "total_exposures": total_exposures,
            "engaged_agents": total_engaged_agents,
            "conversions": total_conversions,
            "reach_to_engage": round(total_engaged_agents / max(total_reached, 1), 3),
            "engage_to_convert": round(total_conversions / max(total_engaged_agents, 1), 3),
            "overall_conversion": round(total_conversions / max(total_reached, 1), 3),
        }

    def get_summary(self) -> dict[str, Any]:
        """获取完整 KOL 分析摘要。"""
        performance = self.get_kol_performance()
        funnel = self.get_funnel()

        best_kol = performance[0] if performance else None
        best_roi_kol = max(performance, key=lambda x: x["roi"]) if performance else None

        return {
            "kol_count": len(self.kol_stats),
            "total_kol_content": sum(s["content_count"] for s in self.kol_stats.values()),
            "kol_performance": performance,
            "funnel": funnel,
            "conversions": self.conversions,
            "best_engagement_kol": best_kol["kol_id"] if best_kol else None,
            "best_roi_kol": best_roi_kol["kol_id"] if best_roi_kol else None,
        }

    @staticmethod
    def _is_kol(author_id: str) -> bool:
        """判断是否为 KOL（非普通 Agent）。"""
        return author_id.startswith("kol_") or author_id == "brand_official"
