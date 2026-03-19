"""Agent 反思机制 — Phase 1 实现。

触发条件（任一满足）:
1. 完成购买行为
2. 连续 browse/skip 超过 3 步
3. 每 N 步强制反思（默认 N=5）

反思输出:
- 对自身行为模式的高层认知
- 更新后的兴趣标签（interest_tags）
- 更新后的决策意向摘要（decision_summary）
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from mirrormart.llm import call_llm

if TYPE_CHECKING:
    from mirrormart.agent import Agent

logger = logging.getLogger(__name__)

REFLECT_SYSTEM_PROMPT = """你是一个模拟环境中的虚拟中国消费者，正在对自己最近的行为进行反思。

【任务】
回顾你最近的行为，总结你的消费模式，更新你的兴趣方向，并形成下一阶段的决策意向。

【输出格式】严格输出以下 JSON，不含其他文字:
{{
  "reflection": "对自己近期行为的2-3句总结",
  "interest_tags": ["兴趣标签1", "兴趣标签2", "兴趣标签3"],
  "decision_summary": "当前购物决策意向的一句话总结",
  "updated_intent": 0.0到1.0的更新后购买意向
}}"""

REFLECT_USER_TEMPLATE = """【你的人设】
姓名: {name}
描述: {description}

【最近 {n_memories} 条行为记忆】
{memories}

【当前内部状态】
兴趣值: {interest_level}
购买意向: {purchase_intent}

请对你最近的行为进行反思，更新你的消费认知。"""


class ReflectEngine:
    """Agent 反思引擎。"""

    def __init__(
        self,
        llm_model: str,
        api_base: str = "",
        api_key: str = "",
        max_tokens: int = 512,
        reflect_every_n_steps: int = 5,
    ) -> None:
        """初始化反思引擎。

        Args:
            llm_model: litellm 模型标识
            api_base: API base URL
            api_key: API key
            max_tokens: 最大 token 数
            reflect_every_n_steps: 每隔多少步强制反思
        """
        self.llm_model = llm_model
        self.api_base = api_base
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.reflect_every_n_steps = reflect_every_n_steps

    def should_reflect(self, agent: "Agent", step: int, last_action_type: str) -> bool:
        """判断是否需要触发反思。

        Args:
            agent: Agent 实例
            step: 当前时间步
            last_action_type: 上一步行为类型

        Returns:
            是否触发反思
        """
        # 触发条件1: 购买行为后立即反思
        if last_action_type == "purchase":
            return True

        # 触发条件2: 每 N 步强制反思
        if step > 0 and step % self.reflect_every_n_steps == 0:
            return True

        # 触发条件3: 连续无效行为（检查最后3条记忆）
        recent = agent.memories[-3:] if len(agent.memories) >= 3 else []
        idle_types = {"browse", "skip", "search"}
        if len(recent) == 3 and all(m.get("action_type") in idle_types for m in recent):
            return True

        return False

    async def reflect(self, agent: "Agent", step: int) -> dict[str, Any] | None:
        """执行反思，更新 Agent 内部状态。

        Args:
            agent: Agent 实例
            step: 当前时间步

        Returns:
            反思结果字典，失败时返回 None
        """
        recent_memories = agent.memories[-10:]
        if not recent_memories:
            return None

        memory_lines = [
            f"步骤{m.get('step', '?')}: {m.get('summary', str(m))}"
            for m in recent_memories
        ]
        memory_text = "\n".join(memory_lines)

        persona = agent.persona
        user_message = REFLECT_USER_TEMPLATE.format(
            name=persona.get("name", agent.id),
            description=persona.get("description", ""),
            n_memories=len(recent_memories),
            memories=memory_text,
            interest_level=round(agent.internal_state.get("interest_level", 0.0), 2),
            purchase_intent=round(agent.internal_state.get("purchase_intent", 0.0), 2),
        )

        try:
            result = await call_llm(
                system_prompt=REFLECT_SYSTEM_PROMPT,
                user_message=user_message,
                model=self.llm_model,
                temperature=0.7,
                max_tokens=self.max_tokens,
                api_base=self.api_base,
                api_key=self.api_key,
            )

            # 用反思结果更新 Agent 状态
            updated_intent = float(result.get("updated_intent", agent.internal_state["purchase_intent"]))
            agent.internal_state["purchase_intent"] = updated_intent

            # 把反思本身存入记忆（高重要性）
            agent.add_memory({
                "step": step,
                "summary": f"[反思] {result.get('reflection', '')}",
                "action_type": "reflect",
                "platform": "internal",
                "importance": 0.9,
                "interest_tags": result.get("interest_tags", []),
                "decision_summary": result.get("decision_summary", ""),
            })

            logger.debug("[%s] 完成反思: %s", agent.id, result.get("reflection", "")[:60])
            return result

        except Exception as e:
            logger.warning("[%s] 反思失败: %s", agent.id, e)
            return None
