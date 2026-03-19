"""Agent 类 — Phase 0 极简实现。

认知循环: perceive → decide → act → [reflect]
"""

from __future__ import annotations

import json
import logging
import random
from typing import TYPE_CHECKING, Any

from mirrormart.llm import call_llm

if TYPE_CHECKING:
    from mirrormart.platforms.base import PlatformBase

logger = logging.getLogger(__name__)

# ──────────────── Prompt 模板 ────────────────

SYSTEM_PROMPT_TEMPLATE = """你是一个模拟环境中的虚拟中国消费者。你生活在2026年的中国，使用小红书和淘宝等平台。

【重要规则】
1. 你必须严格按照自己的人设行动，不能超越人设范围
2. 你的行为必须符合中国消费者的真实习惯
3. 你只能返回 JSON 格式，不能有任何其他文字
4. 行为要有差异性，不要每次都做同样的事

【当前平台环境】
{platform_context}

【时间上下文】
当前是模拟第 {step} 步（约第 {day} 天）。

【可执行的行为类型】
小红书: post（发笔记）, like（点赞）, collect（收藏）, comment（评论）, search（搜索）, follow（关注）, repost（转发）, quote（引用转发+评论）, browse（浏览不互动）
淘宝: search（搜索商品）, view（查看商品）, add_cart（加购物车）, purchase（购买）, review（写评价）, compare（比价）, wishlist（收藏商品）, ask_question（向商品提问）
抖音: post（发短视频）, watch（观看视频）, like（点赞）, comment（评论）, share（分享/转发）, search（搜索）, follow（关注）, browse（刷视频不互动）
微博: post（发微博）, like（点赞）, comment（评论）, repost（转发）, search（搜索）, search_topic（看话题）, follow（关注）, browse（浏览不互动）

【输出格式】你必须严格返回以下 JSON，不能有任何其他文字:
{{
  "thinking": "你内心的想法（简短）",
  "action": {{
    "type": "行为类型",
    "platform": "xiaohongshu 或 taobao",
    "target_id": "目标ID（如适用）",
    "content": "内容（如适用）",
    "query": "搜索词（如适用）"
  }},
  "internal_state": {{
    "interest_level": 0.0到1.0的兴趣值,
    "purchase_intent": 0.0到1.0的购买意向
  }}
}}"""

USER_MESSAGE_TEMPLATE = """【你的人设】
姓名: {name}
描述: {description}
决策风格: {decision_style}
价格敏感度: {price_sensitivity}（0=不敏感 1=极敏感）
关注内容: {content_preference}
信任KOL: {trust_kol}

【你最近的记忆】
{memories}

【你当前看到的内容】
平台: {current_platform}
{perception}

【你的当前状态】
购买意向: {purchase_intent}（超过0.7必须做最终决定）
已反复查看的商品: {view_counts}（超过3次必须决定买或不买）

【重要行为规则】
- 如果某个商品查看次数 > 3，本步骤必须做最终决定：购买或明确放弃
- 如果 purchase_intent > 0.7，本步骤必须购买或明确说出"决定不买"的理由
- 不要每步都做同样的事，要有真实的行为节奏

【请决定你这一步要做什么】
根据你的人设和当前看到的内容，决定下一步行动。"""


class Agent:
    """Phase 0 极简 Agent。"""

    def __init__(
        self,
        persona: dict[str, Any],
        agent_id: str,
        llm_model: str,
        rng: random.Random | None = None,
        max_memory: int = 100,
    ) -> None:
        """初始化 Agent。

        Args:
            persona: YAML 加载的人设字典
            agent_id: 全局唯一 Agent ID
            llm_model: litellm 模型标识
            rng: 随机数生成器
            max_memory: 最大记忆条数
        """
        self.id = agent_id
        self.persona = persona
        self.llm_model = llm_model
        self.api_base = ""
        self.api_key = ""
        self.max_tokens = 2048
        self.rng = rng or random.Random()
        self.max_memory = max_memory

        self.memories: list[dict[str, Any]] = []
        self.action_log: list[dict[str, Any]] = []
        self.internal_state: dict[str, float] = {
            "interest_level": 0.0,
            "purchase_intent": 0.0,
        }
        self._view_counts: dict[str, int] = {}  # 记录每个商品/帖子的查看次数

    # ──────────────── 认知循环 ────────────────

    async def perceive(
        self,
        platform: "PlatformBase",
        platform_name: str,
        step: int,
        query: str | None = None,
    ) -> str:
        """从平台获取可见信息，返回格式化感知摘要。

        Args:
            platform: 平台环境实例
            platform_name: 平台名称标识
            step: 当前时间步
            query: 搜索词（淘宝场景）

        Returns:
            人类可读的感知摘要文本
        """
        # 从 persona 提取兴趣标签传给小红书 feed
        interest_tags = self.persona.get("consumer_traits", {}).get("interest_tags", [])
        if query:
            feed = platform.get_feed(self.id, query=query, limit=5)
        else:
            feed = platform.get_feed(self.id, limit=5, interest_tags=interest_tags)

        if not feed:
            return "（没有看到任何内容）"

        lines = []
        for i, item in enumerate(feed[:5], 1):
            if platform_name == "xiaohongshu":
                lines.append(
                    f"{i}. 【{item.get('title', '无标题')}】"
                    f" 内容: {item.get('content', '')[:80]}"
                    f" | 点赞: {item.get('likes', 0)}"
                    f" | 评论: {item.get('comments_count', 0)}"
                    f" | 转发: {item.get('reposts', 0)}"
                    f" | ID: {item.get('post_id', '')}"
                )
            elif platform_name == "douyin":
                lines.append(
                    f"{i}. 【{item.get('title', '无标题')}】"
                    f" {item.get('content', '')[:60]}"
                    f" | 播放: {item.get('views', 0)}"
                    f" | 点赞: {item.get('likes', 0)}"
                    f" | 完播率: {item.get('completion_rate', 0):.0%}"
                    f" | ID: {item.get('video_id', '')}"
                )
            elif platform_name == "weibo":
                lines.append(
                    f"{i}. @{item.get('author_id', '?')}"
                    f" {item.get('content', '')[:80]}"
                    f" | 转发: {item.get('reposts', 0)}"
                    f" | 评论: {item.get('comments_count', 0)}"
                    f" | 点赞: {item.get('likes', 0)}"
                    f" | ID: {item.get('post_id', '')}"
                )
            else:  # taobao
                lines.append(
                    f"{i}. 【{item.get('name', '无名商品')}】"
                    f" ¥{item.get('price', 0)}"
                    f" | 销量: {item.get('sales', 0)}"
                    f" | 评分: {item.get('rating', 0)}"
                    f" | ID: {item.get('product_id', '')}"
                )
        return "\n".join(lines)

    async def decide(
        self,
        perception: str,
        platform_name: str,
        step: int,
        platform_context: str = "",
    ) -> dict[str, Any]:
        """基于感知+记忆+人设做决策。

        Args:
            perception: 感知摘要
            platform_name: 当前平台名
            step: 当前时间步
            platform_context: 平台规则上下文

        Returns:
            行动指令字典
        """
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            platform_context=platform_context or f"你正在使用{platform_name}",
            step=step,
            day=step // 2 + 1,
        )

        # 检索最近 5 条相关记忆
        recent_memories = self.memories[-5:] if self.memories else []
        memory_text = "\n".join(
            f"- {m.get('summary', str(m))}" for m in recent_memories
        ) or "（暂无记忆）"

        consumer_traits = self.persona.get("consumer_traits", {})
        # 找出已查看超过1次的商品供提示
        repeated_views = {k: v for k, v in self._view_counts.items() if v > 1}
        view_counts_text = (
            "、".join(f"{k}（已看{v}次）" for k, v in repeated_views.items())
            if repeated_views else "无"
        )
        user_message = USER_MESSAGE_TEMPLATE.format(
            name=self.persona.get("name", self.id),
            description=self.persona.get("description", ""),
            decision_style=consumer_traits.get("decision_style", "理性"),
            price_sensitivity=consumer_traits.get("price_sensitivity", 0.5),
            content_preference=consumer_traits.get("content_preference", []),
            trust_kol=consumer_traits.get("trust_kol", True),
            memories=memory_text,
            current_platform=platform_name,
            perception=perception,
            purchase_intent=round(self.internal_state.get("purchase_intent", 0.0), 2),
            view_counts=view_counts_text,
        )

        decision = await call_llm(
            system_prompt=system_prompt,
            user_message=user_message,
            model=self.llm_model,
            temperature=0.8,
            max_tokens=self.max_tokens,
            api_base=self.api_base,
            api_key=self.api_key,
        )

        # 更新内部状态
        internal = decision.get("internal_state", {})
        self.internal_state["interest_level"] = float(internal.get("interest_level", 0.0))
        self.internal_state["purchase_intent"] = float(internal.get("purchase_intent", 0.0))

        return decision

    async def act(
        self,
        decision: dict[str, Any],
        platform: "PlatformBase",
        step: int,
    ) -> dict[str, Any]:
        """在平台上执行行动。

        Args:
            decision: decide() 返回的决策字典
            platform: 平台环境实例
            step: 当前时间步

        Returns:
            行动结果字典
        """
        action = decision.get("action", {})
        if action.get("type") == "skip":
            return {"success": True, "action_type": "skip", "effect": "跳过"}

        result = platform.execute_action(self.id, action)

        # 更新查看计数（用于强制决策逻辑）
        if action.get("type") == "view":
            target = action.get("target_id", "")
            if target:
                self._view_counts[target] = self._view_counts.get(target, 0) + 1

        # 记录到行为日志
        log_entry = {
            "step": step,
            "thinking": decision.get("thinking", ""),
            "action": action,
            "result": result,
            "internal_state": dict(self.internal_state),
        }
        self.action_log.append(log_entry)

        # 记录到记忆流
        self.add_memory({
            "step": step,
            "summary": f"{action.get('type', '?')} → {result.get('effect', '?')}",
            "action_type": action.get("type", ""),
            "platform": action.get("platform", ""),
            "importance": self._calc_importance(action, result),
        })

        return result

    def add_memory(self, event: dict[str, Any]) -> None:
        """记录到记忆列表，超出上限时保留高重要性的。"""
        self.memories.append(event)
        if len(self.memories) > self.max_memory:
            # 按重要性排序，保留前 max_memory * 0.8 条
            self.memories.sort(key=lambda m: m.get("importance", 0), reverse=True)
            self.memories = self.memories[:int(self.max_memory * 0.8)]

    # ──────────────── 辅助方法 ────────────────

    def _calc_importance(self, action: dict, result: dict) -> float:
        """计算记忆重要性（0-1）。"""
        high_importance = {"purchase", "post", "review"}
        mid_importance = {"comment", "follow", "add_cart"}
        action_type = action.get("type", "")
        if action_type in high_importance:
            return 1.0
        if action_type in mid_importance:
            return 0.6
        if not result.get("success", True):
            return 0.3
        return 0.1

    def get_journey_summary(self) -> list[dict[str, Any]]:
        """获取个体旅程摘要（用于分析报告）。"""
        return [
            {
                "step": log["step"],
                "action": f"{log['action'].get('platform', '?')} / {log['action'].get('type', '?')}",
                "effect": log["result"].get("effect", ""),
                "thinking": log.get("thinking", ""),
                "interest": log["internal_state"].get("interest_level", 0),
                "purchase_intent": log["internal_state"].get("purchase_intent", 0),
            }
            for log in self.action_log
        ]

    def to_state_dict(self) -> dict[str, Any]:
        """序列化 Agent 状态（用于快照）。"""
        return {
            "id": self.id,
            "persona_name": self.persona.get("name", self.id),
            "memories_count": len(self.memories),
            "actions_count": len(self.action_log),
            "internal_state": dict(self.internal_state),
            "action_log": self.action_log,
        }
