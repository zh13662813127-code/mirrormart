"""LLM 调用封装模块，使用 litellm 作为统一网关。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import litellm

logger = logging.getLogger(__name__)

# 静默 litellm 的冗余日志
litellm.suppress_debug_info = True


async def call_llm(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float = 0.8,
    max_tokens: int = 512,
    retries: int = 2,
    api_base: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    """调用 LLM 并解析 JSON 输出。

    Args:
        system_prompt: 系统提示词（所有Agent共享部分）
        user_message: 用户消息（每Agent每步不同）
        model: litellm 模型标识
        temperature: 采样温度
        max_tokens: 最大输出 token 数
        retries: JSON 解析失败时的重试次数
        api_base: 自定义 API base URL（MiniMax 等需要）
        api_key: API Key

    Returns:
        解析后的 JSON 字典，失败时返回 fallback 字典
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    extra_kwargs: dict[str, Any] = {}
    if api_base:
        extra_kwargs["api_base"] = api_base
    if api_key:
        extra_kwargs["api_key"] = api_key

    for attempt in range(retries + 1):
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **extra_kwargs,
            )
            content = response.choices[0].message.content or ""
            return _parse_json_response(content)
        except json.JSONDecodeError as e:
            if attempt < retries:
                logger.warning("JSON 解析失败（第%d次），重试... 错误: %s", attempt + 1, e)
                await asyncio.sleep(0.5)
            else:
                logger.error("LLM 返回非法 JSON，使用 fallback 行为")
                return _fallback_decision()
        except Exception as e:
            error_str = str(e)
            # 余额不足 / 认证错误 — 不重试，直接报错
            if "insufficient balance" in error_str or "1008" in error_str:
                logger.error("❌ API 余额不足（错误码 1008）。请充值后重试。")
                raise RuntimeError("MiniMax API 余额不足，请前往 https://platform.minimaxi.com 充值") from e
            if "401" in error_str or "AuthenticationError" in error_str:
                logger.error("❌ API Key 无效，请检查 .env 中的 MINIMAX_API_KEY")
                raise RuntimeError("API Key 无效") from e
            # 限流 — 指数退避重试
            if "rate" in error_str.lower() or "429" in error_str:
                wait = 2 ** attempt
                logger.warning("API 限流，等待 %d 秒后重试...", wait)
                await asyncio.sleep(wait)
            elif attempt < retries:
                logger.warning("LLM 调用失败（第%d次）: %s", attempt + 1, e)
                await asyncio.sleep(1)
            else:
                logger.error("LLM 调用最终失败: %s，Agent 本步骤跳过", e)
                return _fallback_skip()

    return _fallback_skip()


def _parse_json_response(content: str) -> dict[str, Any]:
    """从 LLM 响应中提取 JSON。

    支持:
    - 推理模型的 <think>...</think> 标签（MiniMax M2.5 等）
    - ```json ... ``` 代码块
    - 文本中内嵌的 JSON 对象
    """
    # 剥离 <think>...</think> 推理过程（推理模型如 MiniMax M2.5）
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    if not content:
        raise json.JSONDecodeError("响应内容为空（可能 max_tokens 太小）", content, 0)

    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    # 尝试提取第一个 { ... } 块
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise json.JSONDecodeError("未找到 JSON", content, 0)


def _fallback_decision() -> dict[str, Any]:
    """JSON 解析失败时的默认行为：潜水。"""
    return {
        "thinking": "（格式异常，默认潜水）",
        "action": {"type": "browse", "platform": "xiaohongshu"},
        "internal_state": {"interest_level": 0.3, "purchase_intent": 0.0},
    }


def _fallback_skip() -> dict[str, Any]:
    """API 调用失败时的跳过行为。"""
    return {
        "thinking": "（走神了）",
        "action": {"type": "skip"},
        "internal_state": {"interest_level": 0.0, "purchase_intent": 0.0},
    }
