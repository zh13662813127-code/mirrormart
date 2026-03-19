"""WebSocket 事件广播 — Phase 1 实现。

每个模拟步骤产生的 event 通过此模块广播给所有连接的前端客户端。
支持多客户端同时订阅同一 run_id 的事件流。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket 连接管理器，支持按 run_id 分组广播。"""

    def __init__(self) -> None:
        # run_id → [WebSocket, ...]
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, run_id: str) -> None:
        """接受并注册连接。"""
        await websocket.accept()
        self._connections.setdefault(run_id, []).append(websocket)
        logger.info("WebSocket 客户端连接: run_id=%s, 当前连接数=%d",
                    run_id, len(self._connections[run_id]))

    def disconnect(self, websocket: WebSocket, run_id: str) -> None:
        """注销连接。"""
        conns = self._connections.get(run_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(run_id, None)

    async def broadcast(self, run_id: str, event: dict[str, Any]) -> None:
        """向订阅 run_id 的所有客户端广播事件。"""
        conns = self._connections.get(run_id, [])
        if not conns:
            return

        message = json.dumps(event, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in list(conns):
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.debug("WebSocket 发送失败，移除连接: %s", e)
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, run_id)

    async def send_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        """发送结构化事件。

        Args:
            run_id: 模拟运行 ID
            event_type: 事件类型（如 "agent_action", "step_complete", "run_complete"）
            data: 事件数据
        """
        await self.broadcast(run_id, {"type": event_type, "run_id": run_id, **data})

    def active_runs(self) -> list[str]:
        """返回当前有活跃连接的 run_id 列表。"""
        return list(self._connections.keys())


# 全局单例
manager = ConnectionManager()


class EventQueue:
    """模拟引擎与 WebSocket 之间的异步事件队列。

    使用 asyncio.Queue 解耦生产者（引擎）和消费者（WebSocket 广播）。
    """

    def __init__(self, run_id: str, maxsize: int = 1000) -> None:
        self.run_id = run_id
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """启动后台广播任务。"""
        self._task = asyncio.create_task(self._consume())

    async def put(self, event: dict[str, Any]) -> None:
        """将事件放入队列（非阻塞，满则丢弃）。"""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("事件队列满，丢弃事件: run_id=%s", self.run_id)

    async def finish(self) -> None:
        """通知队列消费完毕并等待消费任务结束。"""
        await self._queue.put(None)  # 哨兵值
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _consume(self) -> None:
        """后台消费任务：从队列取事件并广播。"""
        while True:
            event = await self._queue.get()
            if event is None:
                break
            await manager.broadcast(self.run_id, event)
            self._queue.task_done()
