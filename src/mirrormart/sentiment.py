"""情感分析追踪器。

从 Agent 的评论、帖子、评价中提取情感极性，
追踪各平台的舆情趋势变化。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 正面关键词（中文消费场景）
POSITIVE_KEYWORDS = [
    "好用", "推荐", "回购", "惊艳", "喜欢", "不错", "性价比", "温和",
    "舒服", "好评", "满意", "值得", "有效", "水润", "滋润", "平价",
    "好闻", "无刺激", "安心", "靠谱", "划算", "宝藏", "良心", "干净",
    "明显改善", "效果好", "很棒", "真心推荐", "必买", "入股不亏",
    "绝了", "yyds", "爱了", "太香了", "种草", "心动",
]

# 负面关键词
NEGATIVE_KEYWORDS = [
    "踩雷", "不推荐", "垃圾", "过敏", "刺激", "假的", "难用",
    "不好用", "失望", "后悔", "坑", "智商税", "鸡肋", "差评",
    "拔草", "退款", "太贵", "不值", "没效果", "浪费钱", "翻车",
    "无感", "一般般", "不回购", "虚假宣传", "烂脸", "闷痘",
]


def analyze_sentiment(text: str) -> dict[str, Any]:
    """分析文本的情感极性。

    Args:
        text: 待分析文本（评论、帖子、评价内容）

    Returns:
        {"polarity": float (-1~1), "label": "positive"|"negative"|"neutral",
         "positive_hits": [...], "negative_hits": [...]}
    """
    if not text:
        return {"polarity": 0.0, "label": "neutral", "positive_hits": [], "negative_hits": []}

    pos_hits = [kw for kw in POSITIVE_KEYWORDS if kw in text]
    neg_hits = [kw for kw in NEGATIVE_KEYWORDS if kw in text]

    pos_score = len(pos_hits)
    neg_score = len(neg_hits)
    total = pos_score + neg_score

    if total == 0:
        return {"polarity": 0.0, "label": "neutral", "positive_hits": [], "negative_hits": []}

    polarity = round((pos_score - neg_score) / total, 3)

    if polarity > 0.2:
        label = "positive"
    elif polarity < -0.2:
        label = "negative"
    else:
        label = "neutral"

    return {
        "polarity": polarity,
        "label": label,
        "positive_hits": pos_hits,
        "negative_hits": neg_hits,
    }


class SentimentTracker:
    """舆情追踪器：按平台、按时间步收集情感数据。"""

    def __init__(self) -> None:
        """初始化追踪器。"""
        # {step: [{"agent_id", "platform", "action_type", "polarity", "label", "text_preview"}]}
        self.timeline: dict[int, list[dict[str, Any]]] = {}
        # {platform: {"positive": int, "negative": int, "neutral": int}}
        self.platform_counts: dict[str, dict[str, int]] = {}

    def track_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """分析事件中的文本内容并记录情感。

        Args:
            event: 引擎产生的事件字典

        Returns:
            情感分析结果（如果有文本内容），否则 None
        """
        action = event.get("action", {})
        action_type = action.get("type", "")

        # 只分析有文本内容的行为
        text_actions = {"comment", "post", "review", "quote", "repost"}
        if action_type not in text_actions:
            return None

        # 从多个位置提取文本
        text = (
            action.get("content", "")
            or event.get("thinking", "")
            or event.get("result", {}).get("effect", "")
        )
        if not text:
            return None

        result = analyze_sentiment(text)
        step = event.get("branch_step", 0)
        platform = event.get("platform", "unknown")
        agent_id = event.get("agent_id", "unknown")

        record = {
            "agent_id": agent_id,
            "platform": platform,
            "action_type": action_type,
            "polarity": result["polarity"],
            "label": result["label"],
            "text_preview": text[:60],
            "positive_hits": result["positive_hits"],
            "negative_hits": result["negative_hits"],
        }

        # 记录到时间线
        if step not in self.timeline:
            self.timeline[step] = []
        self.timeline[step].append(record)

        # 更新平台计数
        if platform not in self.platform_counts:
            self.platform_counts[platform] = {"positive": 0, "negative": 0, "neutral": 0}
        self.platform_counts[platform][result["label"]] += 1

        return result

    def get_trend(self) -> list[dict[str, Any]]:
        """获取情感趋势（按时间步聚合）。

        Returns:
            [{"step": int, "avg_polarity": float, "positive": int, "negative": int, "neutral": int}]
        """
        trend = []
        for step in sorted(self.timeline.keys()):
            records = self.timeline[step]
            polarities = [r["polarity"] for r in records]
            avg_pol = round(sum(polarities) / len(polarities), 3) if polarities else 0.0
            labels = [r["label"] for r in records]
            trend.append({
                "step": step,
                "avg_polarity": avg_pol,
                "count": len(records),
                "positive": labels.count("positive"),
                "negative": labels.count("negative"),
                "neutral": labels.count("neutral"),
            })
        return trend

    def get_platform_sentiment(self) -> dict[str, dict[str, Any]]:
        """获取各平台的情感汇总。

        Returns:
            {platform: {"positive": int, "negative": int, "neutral": int, "ratio": float}}
        """
        result = {}
        for platform, counts in self.platform_counts.items():
            total = sum(counts.values())
            ratio = (counts["positive"] - counts["negative"]) / max(total, 1)
            result[platform] = {
                **counts,
                "total": total,
                "sentiment_ratio": round(ratio, 3),
            }
        return result

    def get_summary(self) -> dict[str, Any]:
        """获取完整情感分析摘要。"""
        all_records = []
        for records in self.timeline.values():
            all_records.extend(records)

        if not all_records:
            return {
                "total_analyzed": 0,
                "overall_polarity": 0.0,
                "trend": [],
                "platform_sentiment": {},
                "top_positive": [],
                "top_negative": [],
            }

        polarities = [r["polarity"] for r in all_records]
        overall = round(sum(polarities) / len(polarities), 3)

        # 最正面和最负面的内容
        sorted_pos = sorted(all_records, key=lambda r: r["polarity"], reverse=True)
        sorted_neg = sorted(all_records, key=lambda r: r["polarity"])

        return {
            "total_analyzed": len(all_records),
            "overall_polarity": overall,
            "overall_label": "positive" if overall > 0.2 else ("negative" if overall < -0.2 else "neutral"),
            "trend": self.get_trend(),
            "platform_sentiment": self.get_platform_sentiment(),
            "top_positive": sorted_pos[:3],
            "top_negative": [r for r in sorted_neg[:3] if r["polarity"] < 0],
        }
