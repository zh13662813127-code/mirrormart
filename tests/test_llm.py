"""LLM 模块单元测试（Mock LLM 调用）。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from mirrormart.llm import _parse_json_response, call_llm


class TestParseJsonResponse:
    """JSON 解析工具测试。"""

    def test_direct_json(self) -> None:
        data = _parse_json_response('{"action": {"type": "like"}}')
        assert data["action"]["type"] == "like"

    def test_json_in_code_block(self) -> None:
        content = '```json\n{"action": {"type": "comment"}}\n```'
        data = _parse_json_response(content)
        assert data["action"]["type"] == "comment"

    def test_json_in_text(self) -> None:
        content = '这是我的决定：{"action": {"type": "search"}} 就这样'
        data = _parse_json_response(content)
        assert data["action"]["type"] == "search"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("这根本不是JSON")


class TestCallLLM:
    """LLM 调用封装测试。"""

    @pytest.mark.asyncio
    async def test_successful_call(self) -> None:
        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(message=AsyncMock(content='{"thinking": "ok", "action": {"type": "like"}}'))
        ]

        with patch("mirrormart.llm.litellm.acompletion", return_value=mock_response):
            result = await call_llm("system", "user", "test/model")

        assert result["action"]["type"] == "like"

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self) -> None:
        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(message=AsyncMock(content="这不是JSON格式的响应"))
        ]

        with patch("mirrormart.llm.litellm.acompletion", return_value=mock_response):
            result = await call_llm("system", "user", "test/model", retries=0)

        # 应该返回 fallback
        assert "action" in result
