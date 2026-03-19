"""FastAPI 应用入口 — Phase 1 实现。

启动:
    uv run uvicorn mirrormart.api.app:app --reload --port 8000

WebSocket 订阅:
    ws://localhost:8000/ws/{run_id}
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from mirrormart.api.routes.simulation import router as simulation_router
from mirrormart.api.websocket import manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理。"""
    logger.info("MirrorMart API 服务启动")
    yield
    logger.info("MirrorMart API 服务关闭")


app = FastAPI(
    title="MirrorMart API",
    description="镜市社会模拟引擎 REST API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(simulation_router)


@app.get("/")
async def root() -> dict[str, str]:
    """健康检查。"""
    return {"status": "ok", "service": "MirrorMart API", "version": "1.0.0"}


@app.get("/health")
async def health() -> dict[str, str]:
    """健康检查端点。"""
    return {"status": "healthy"}


@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str) -> None:
    """WebSocket 事件流端点。

    客户端连接后，实时接收模拟运行过程中的所有 agent_action 事件。

    消息格式:
        {"type": "agent_action", "run_id": "...", "step": 0, "agent_id": "...", ...}
        {"type": "step_complete", "run_id": "...", "step": 0, "metrics": {...}}
        {"type": "run_complete", "run_id": "...", "result": {...}}
    """
    await manager.connect(websocket, run_id)
    try:
        while True:
            # 保持连接活跃，接收心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, run_id)
        logger.info("WebSocket 客户端断开: run_id=%s", run_id)
