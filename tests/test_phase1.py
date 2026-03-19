"""Phase 1 组件单元测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mirrormart.cache.redis_cache import RedisCache
from mirrormart.memory.chroma_store import ChromaMemoryStore
from mirrormart.reflect import ReflectEngine


# ──────────────── ChromaMemoryStore ────────────────


class TestChromaMemoryStore:
    """Chroma 记忆存储测试。"""

    def test_init_unavailable_gracefully(self) -> None:
        """Chroma 不可用时不应抛出异常。"""
        with patch("mirrormart.memory.chroma_store._CHROMA_AVAILABLE", False):
            store = ChromaMemoryStore(persist_dir="/tmp/test_chroma", branch_id=0, agent_id="test")
            assert store.available is False

    def test_add_and_retrieve_no_crash_when_unavailable(self) -> None:
        """不可用时 add/retrieve 应静默返回。"""
        with patch("mirrormart.memory.chroma_store._CHROMA_AVAILABLE", False):
            store = ChromaMemoryStore(persist_dir="/tmp/test_chroma", branch_id=0, agent_id="test")
            # Should not raise
            store.add({"summary": "test", "step": 1}, "mem_1")
            result = store.retrieve("test query")
            assert result == []

    def test_add_and_retrieve_with_chroma(self, tmp_path: Any) -> None:
        """Chroma 可用时能正确存储和检索。"""
        if not ChromaMemoryStore.is_available():
            pytest.skip("chromadb 未安装")

        store = ChromaMemoryStore(
            persist_dir=str(tmp_path / "chroma"),
            branch_id=0,
            agent_id="test_agent",
        )
        if not store.available:
            pytest.skip("Chroma 初始化失败")

        # 添加几条记忆
        memories = [
            {"summary": "购买了氨基酸面膜", "step": 1, "action_type": "purchase", "platform": "taobao", "importance": 1.0},
            {"summary": "在小红书点赞了护肤笔记", "step": 2, "action_type": "like", "platform": "xiaohongshu", "importance": 0.1},
            {"summary": "搜索了氨基酸成分表", "step": 3, "action_type": "search", "platform": "taobao", "importance": 0.3},
        ]
        for i, mem in enumerate(memories):
            store.add(mem, f"mem_{i}")

        # 检索相关记忆
        results = store.retrieve("面膜购买决策", n_results=2)
        assert len(results) >= 1
        # 最相关的应该包含购买相关内容
        summaries = [r["summary"] for r in results]
        assert any("面膜" in s or "购买" in s for s in summaries)

        # 清理
        store.delete_collection()

    def test_is_available_static(self) -> None:
        """is_available 应该返回 bool。"""
        result = ChromaMemoryStore.is_available()
        assert isinstance(result, bool)


# ──────────────── RedisCache ────────────────


class TestRedisCache:
    """Redis 缓存测试。"""

    def test_init_without_redis(self) -> None:
        """Redis 不可用时不应抛出异常。"""
        with patch("mirrormart.cache.redis_cache._REDIS_AVAILABLE", False):
            cache = RedisCache()
            assert cache.available is False

    @pytest.mark.asyncio
    async def test_get_returns_none_when_unavailable(self) -> None:
        """不可用时 get 应返回 None。"""
        with patch("mirrormart.cache.redis_cache._REDIS_AVAILABLE", False):
            cache = RedisCache()
            result = await cache.get_feed("xiaohongshu", "agent_01", 0)
            assert result is None

    @pytest.mark.asyncio
    async def test_set_no_crash_when_unavailable(self) -> None:
        """不可用时 set 应静默返回。"""
        with patch("mirrormart.cache.redis_cache._REDIS_AVAILABLE", False):
            cache = RedisCache()
            # Should not raise
            await cache.set_feed("xiaohongshu", "agent_01", 0, [{"title": "test"}])

    @pytest.mark.asyncio
    async def test_ping_returns_false_when_no_server(self) -> None:
        """无 Redis server 时 ping 应返回 False。"""
        cache = RedisCache(host="localhost", port=16379)  # 不存在的端口
        result = await cache.ping()
        assert result is False
        assert cache.available is False

    def test_feed_key_format(self) -> None:
        """feed key 格式应包含所有参数。"""
        key = RedisCache._feed_key("xiaohongshu", "agent_01", 3, "面膜")
        assert "xiaohongshu" in key
        assert "agent_01" in key
        assert "3" in key
        assert "面膜" in key

    def test_is_available_static(self) -> None:
        """is_available 应该返回 bool。"""
        result = RedisCache.is_available()
        assert isinstance(result, bool)


# ──────────────── ReflectEngine ────────────────


class TestReflectEngine:
    """反思引擎测试。"""

    def _make_agent(self, memories: list[dict], purchase_intent: float = 0.3) -> MagicMock:
        """创建 mock Agent。"""
        agent = MagicMock()
        agent.id = "test_agent"
        agent.persona = {"name": "测试用户", "description": "测试人设"}
        agent.memories = memories
        agent.internal_state = {"interest_level": 0.5, "purchase_intent": purchase_intent}
        agent.add_memory = MagicMock()
        return agent

    def test_should_reflect_on_purchase(self) -> None:
        """购买后应触发反思。"""
        engine = ReflectEngine(llm_model="test/model")
        agent = self._make_agent([])
        assert engine.should_reflect(agent, 1, "purchase") is True

    def test_should_reflect_every_n_steps(self) -> None:
        """每 N 步应触发反思。"""
        engine = ReflectEngine(llm_model="test/model", reflect_every_n_steps=5)
        agent = self._make_agent([])
        assert engine.should_reflect(agent, 5, "browse") is True
        assert engine.should_reflect(agent, 10, "browse") is True
        assert engine.should_reflect(agent, 3, "browse") is False

    def test_should_reflect_on_consecutive_idle(self) -> None:
        """连续3次空闲行为后应触发反思。"""
        engine = ReflectEngine(llm_model="test/model")
        idle_memories = [
            {"action_type": "browse"},
            {"action_type": "skip"},
            {"action_type": "search"},
        ]
        agent = self._make_agent(idle_memories)
        assert engine.should_reflect(agent, 3, "browse") is True

    def test_should_not_reflect_on_normal_action(self) -> None:
        """正常行为不触发反思（排除 N 步强制触发）。"""
        engine = ReflectEngine(llm_model="test/model", reflect_every_n_steps=5)
        agent = self._make_agent([
            {"action_type": "like"},
            {"action_type": "collect"},
            {"action_type": "comment"},
        ])
        assert engine.should_reflect(agent, 3, "like") is False

    @pytest.mark.asyncio
    async def test_reflect_returns_none_with_empty_memories(self) -> None:
        """记忆为空时反思应返回 None。"""
        engine = ReflectEngine(llm_model="test/model")
        agent = self._make_agent([])
        result = await engine.reflect(agent, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_reflect_updates_purchase_intent(self) -> None:
        """反思应更新 Agent 的 purchase_intent。"""
        engine = ReflectEngine(llm_model="test/model")
        agent = self._make_agent(
            [{"step": 1, "summary": "购买了面膜，效果不错"}],
            purchase_intent=0.4,
        )

        mock_result = {
            "reflection": "我最近购买了氨基酸面膜",
            "interest_tags": ["护肤", "面膜"],
            "decision_summary": "已购买，等待体验",
            "updated_intent": 0.2,  # 购买后意向降低
        }

        with patch("mirrormart.reflect.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_result
            result = await engine.reflect(agent, 2)

        assert result is not None
        assert agent.internal_state["purchase_intent"] == 0.2
        agent.add_memory.assert_called_once()


# 使 pytest 能处理 tmp_path fixture
from typing import Any
