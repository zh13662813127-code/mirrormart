"""Redis 热态缓存 — Phase 1 实现。

功能:
- 缓存平台 feed 结果（避免重复计算热度排序）
- 缓存 Agent 感知摘要
- TTL 自动过期，不影响模拟正确性
- 优雅降级: Redis 不可用时返回 None，调用方走正常路径
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class RedisCache:
    """Redis 热态缓存，提供 feed 和 perception 的 TTL 缓存。"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        ttl: int = 30,
    ) -> None:
        """初始化 Redis 连接。

        Args:
            host: Redis 主机地址
            port: Redis 端口
            db: Redis 数据库编号
            ttl: 缓存过期秒数（默认 30s，对应约 1 个模拟步）
        """
        self.ttl = ttl
        self._client: Any = None
        self.available = False

        if not _REDIS_AVAILABLE:
            logger.debug("redis 包未安装，缓存已禁用")
            return

        try:
            self._client = aioredis.Redis(
                host=host, port=port, db=db,
                socket_connect_timeout=1,
                decode_responses=True,
            )
        except Exception as e:
            logger.warning("Redis 连接创建失败: %s", e)

    async def ping(self) -> bool:
        """测试 Redis 连接是否可用。"""
        if self._client is None:
            return False
        try:
            await self._client.ping()
            self.available = True
            logger.info("Redis 连接成功")
            return True
        except Exception as e:
            logger.debug("Redis ping 失败（将使用无缓存模式）: %s", e)
            self.available = False
            return False

    async def get_feed(
        self,
        platform: str,
        agent_id: str,
        step: int,
        query: str | None = None,
    ) -> list[dict[str, Any]] | None:
        """从缓存获取 feed 结果。

        Returns:
            命中则返回 feed 列表，未命中返回 None
        """
        if not self.available or self._client is None:
            return None
        key = self._feed_key(platform, agent_id, step, query)
        try:
            value = await self._client.get(key)
            if value:
                return json.loads(value)  # type: ignore[no-any-return]
        except Exception as e:
            logger.debug("Redis get_feed 失败: %s", e)
        return None

    async def set_feed(
        self,
        platform: str,
        agent_id: str,
        step: int,
        feed: list[dict[str, Any]],
        query: str | None = None,
    ) -> None:
        """写入 feed 缓存。"""
        if not self.available or self._client is None:
            return
        key = self._feed_key(platform, agent_id, step, query)
        try:
            await self._client.setex(key, self.ttl, json.dumps(feed, ensure_ascii=False))
        except Exception as e:
            logger.debug("Redis set_feed 失败: %s", e)

    async def get_perception(
        self,
        agent_id: str,
        platform: str,
        step: int,
    ) -> str | None:
        """获取缓存的感知摘要。"""
        if not self.available or self._client is None:
            return None
        key = f"perc:{platform}:{agent_id}:{step}"
        try:
            return await self._client.get(key)  # type: ignore[no-any-return]
        except Exception as e:
            logger.debug("Redis get_perception 失败: %s", e)
        return None

    async def set_perception(
        self,
        agent_id: str,
        platform: str,
        step: int,
        perception: str,
    ) -> None:
        """写入感知摘要缓存。"""
        if not self.available or self._client is None:
            return
        key = f"perc:{platform}:{agent_id}:{step}"
        try:
            await self._client.setex(key, self.ttl, perception)
        except Exception as e:
            logger.debug("Redis set_perception 失败: %s", e)

    async def close(self) -> None:
        """关闭 Redis 连接。"""
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass

    @staticmethod
    def _feed_key(platform: str, agent_id: str, step: int, query: str | None) -> str:
        q = query or ""
        return f"feed:{platform}:{agent_id}:{step}:{q}"

    @staticmethod
    def is_available() -> bool:
        """检查 redis 包是否安装。"""
        return _REDIS_AVAILABLE
