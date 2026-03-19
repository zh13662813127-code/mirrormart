"""FastAPI 应用入口。

启动:
    uv run uvicorn mirrormart.api.app:app --reload --port 8000

仪表盘: http://localhost:8000/
WebSocket: ws://localhost:8000/ws/{run_id}
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from mirrormart.api.routes.simulation import router as simulation_router
from mirrormart.api.websocket import manager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理。"""
    logger.info("MirrorMart API 服务启动")
    yield
    logger.info("MirrorMart API 服务关闭")


app = FastAPI(
    title="MirrorMart API",
    description="镜市社会模拟引擎 REST API",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS 配置（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 注册路由
app.include_router(simulation_router)


@app.get("/")
async def dashboard() -> FileResponse:
    """仪表盘首页。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    """健康检查端点。"""
    return {"status": "healthy"}


@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str) -> None:
    """WebSocket 事件流端点。"""
    await manager.connect(websocket, run_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, run_id)
        logger.info("WebSocket 客户端断开: run_id=%s", run_id)
