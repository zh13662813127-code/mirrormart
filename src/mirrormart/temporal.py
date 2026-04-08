"""时间维度分析模块。

追踪每个时间步的行为密度、平台使用分布、转化事件，
生成时间维度统计数据，用于热力图和趋势分析。
"""

from __future__ import annotations

from typing import Any


class TemporalAnalyzer:
    """按时间步追踪和分析模拟事件。"""

    def __init__(self, num_steps: int) -> None:
        """初始化时间维度分析器。

        Args:
            num_steps: 模拟总步数
        """
        self.num_steps = num_steps
        # 每步的行为计数: step → {action_type → count}
        self._action_counts: dict[int, dict[str, int]] = {}
        # 每步的平台使用: step → {platform → count}
        self._platform_counts: dict[int, dict[str, int]] = {}
        # 每步的转化事件: step → [event_detail]
        self._conversions: dict[int, list[dict[str, Any]]] = {}
        # 每步的总事件数
        self._event_counts: dict[int, int] = {}
        # 每步的平均购买意向
        self._intent_sums: dict[int, float] = {}
        self._intent_counts: dict[int, int] = {}

    def track_event(self, event: dict[str, Any]) -> None:
        """记录一个事件到时间维度统计。"""
        step = event.get("branch_step", 0)
        action = event.get("action", {})
        action_type = action.get("type", "unknown")
        platform = event.get("platform", "unknown")
        intent = event.get("internal_state", {}).get("purchase_intent", 0)

        # 事件计数
        self._event_counts[step] = self._event_counts.get(step, 0) + 1

        # 行为类型计数
        step_actions = self._action_counts.setdefault(step, {})
        step_actions[action_type] = step_actions.get(action_type, 0) + 1

        # 平台使用计数
        step_platforms = self._platform_counts.setdefault(step, {})
        step_platforms[platform] = step_platforms.get(platform, 0) + 1

        # 购买意向追踪
        self._intent_sums[step] = self._intent_sums.get(step, 0) + intent
        self._intent_counts[step] = self._intent_counts.get(step, 0) + 1

        # 转化事件特别记录
        if action_type == "purchase":
            self._conversions.setdefault(step, []).append({
                "agent_id": event.get("agent_id", ""),
                "product_id": action.get("target_id", ""),
                "effect": event.get("result", {}).get("effect", ""),
            })

    def get_summary(self) -> dict[str, Any]:
        """生成时间维度分析汇总。"""
        # 每步行为密度（事件数）
        step_density = [
            self._event_counts.get(s, 0) for s in range(self.num_steps)
        ]

        # 每步平台分布
        all_platforms = set()
        for counts in self._platform_counts.values():
            all_platforms.update(counts.keys())
        platform_timeline: dict[str, list[int]] = {
            pf: [
                self._platform_counts.get(s, {}).get(pf, 0)
                for s in range(self.num_steps)
            ]
            for pf in sorted(all_platforms)
        }

        # 每步行为类型分布
        all_actions = set()
        for counts in self._action_counts.values():
            all_actions.update(counts.keys())
        action_timeline: dict[str, list[int]] = {
            at: [
                self._action_counts.get(s, {}).get(at, 0)
                for s in range(self.num_steps)
            ]
            for at in sorted(all_actions)
        }

        # 每步平均购买意向
        intent_timeline = []
        for s in range(self.num_steps):
            total = self._intent_sums.get(s, 0)
            count = self._intent_counts.get(s, 0)
            intent_timeline.append(round(total / count, 3) if count > 0 else 0)

        # 转化时间线
        conversion_timeline = [
            len(self._conversions.get(s, [])) for s in range(self.num_steps)
        ]
        conversion_details = {
            str(s): events for s, events in self._conversions.items() if events
        }

        # 行为密度热力图数据：platform × step
        heatmap: dict[str, list[int]] = platform_timeline

        # 关键时刻：转化集中的时间步
        peak_steps = sorted(
            range(self.num_steps),
            key=lambda s: conversion_timeline[s],
            reverse=True,
        )[:5]
        peak_moments = [
            {"step": s, "conversions": conversion_timeline[s]}
            for s in peak_steps if conversion_timeline[s] > 0
        ]

        # 阶段分析：将步骤分为 早期/中期/晚期
        phases = self._analyze_phases()

        return {
            "num_steps": self.num_steps,
            "step_density": step_density,
            "platform_timeline": platform_timeline,
            "action_timeline": action_timeline,
            "intent_timeline": intent_timeline,
            "conversion_timeline": conversion_timeline,
            "conversion_details": conversion_details,
            "heatmap": heatmap,
            "peak_moments": peak_moments,
            "phases": phases,
        }

    def _analyze_phases(self) -> dict[str, Any]:
        """将模拟分为早中晚三阶段，分析各阶段特征。"""
        if self.num_steps < 3:
            return {}

        third = self.num_steps // 3
        ranges = {
            "early": (0, third),
            "mid": (third, third * 2),
            "late": (third * 2, self.num_steps),
        }

        phases: dict[str, Any] = {}
        for phase_name, (start, end) in ranges.items():
            events = sum(self._event_counts.get(s, 0) for s in range(start, end))
            conversions = sum(
                len(self._conversions.get(s, [])) for s in range(start, end)
            )
            # 阶段主要行为
            action_totals: dict[str, int] = {}
            for s in range(start, end):
                for at, cnt in self._action_counts.get(s, {}).items():
                    action_totals[at] = action_totals.get(at, 0) + cnt
            top_action = max(action_totals, key=action_totals.get) if action_totals else "none"

            # 阶段主要平台
            platform_totals: dict[str, int] = {}
            for s in range(start, end):
                for pf, cnt in self._platform_counts.get(s, {}).items():
                    platform_totals[pf] = platform_totals.get(pf, 0) + cnt
            top_platform = max(platform_totals, key=platform_totals.get) if platform_totals else "none"

            # 阶段平均意向
            intent_total = sum(self._intent_sums.get(s, 0) for s in range(start, end))
            intent_count = sum(self._intent_counts.get(s, 0) for s in range(start, end))
            avg_intent = round(intent_total / intent_count, 3) if intent_count > 0 else 0

            phases[phase_name] = {
                "steps": f"{start}-{end-1}",
                "total_events": events,
                "conversions": conversions,
                "top_action": top_action,
                "top_platform": top_platform,
                "avg_purchase_intent": avg_intent,
            }

        return phases
