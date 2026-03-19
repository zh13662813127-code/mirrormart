"""模拟管理 REST API 路由 — Phase 1 实现。

端点:
  POST /simulations          — 创建并启动模拟（后台异步运行）
  GET  /simulations          — 列出所有运行记录
  GET  /simulations/{run_id} — 获取单次运行结果
  GET  /simulations/{run_id}/status — 获取运行状态
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from mirrormart.config import SimulationConfig
from mirrormart.engine import SimulationEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])

# 内存状态存储（Phase 1 不使用数据库）
_run_status: dict[str, str] = {}          # run_id → "running" | "completed" | "failed"
_run_results: dict[str, dict[str, Any]] = {}  # run_id → aggregated result


class SimulationRequest(BaseModel):
    """创建模拟的请求体。"""

    scenario: str = Field(default="scenarios/facemask_launch.yml", description="场景 YAML 路径")
    num_branches: int = Field(default=5, ge=1, le=20, description="蒙特卡洛分支数")
    num_steps: int = Field(default=20, ge=1, le=100, description="每分支时间步数")
    model: str | None = Field(default=None, description="LLM 模型标识（覆盖环境变量）")


class SimulationStatus(BaseModel):
    """模拟状态响应。"""

    run_id: str
    status: str
    result: dict[str, Any] | None = None


async def _run_simulation(run_id: str, config: SimulationConfig) -> None:
    """后台异步执行模拟。"""
    _run_status[run_id] = "running"
    try:
        engine = SimulationEngine(config)
        result = await engine.run_monte_carlo()
        result["run_id"] = run_id
        _run_results[run_id] = result
        _run_status[run_id] = "completed"
        logger.info("模拟完成: run_id=%s", run_id)
    except Exception as e:
        logger.error("模拟失败: run_id=%s, error=%s", run_id, e)
        _run_status[run_id] = "failed"
        _run_results[run_id] = {"error": str(e)}


@router.post("", status_code=202)
async def create_simulation(
    request: SimulationRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """创建并启动模拟（202 Accepted，后台运行）。"""
    config = SimulationConfig.from_env(scenario_path=request.scenario)
    config.num_branches = request.num_branches
    config.num_steps = request.num_steps
    if request.model:
        config.llm_model = request.model

    # 提前确定 run_id（和引擎内部保持同步）
    import time
    run_id = time.strftime("run_%Y%m%d_%H%M%S")
    _run_status[run_id] = "queued"

    background_tasks.add_task(_run_simulation, run_id, config)

    return {
        "run_id": run_id,
        "status": "queued",
        "message": f"模拟已排队，使用 GET /simulations/{run_id}/status 查看进度",
    }


@router.get("")
async def list_simulations() -> list[dict[str, Any]]:
    """列出所有运行记录（含磁盘上的历史运行）。"""
    runs = []

    # 内存中的运行
    for run_id, status in _run_status.items():
        runs.append({"run_id": run_id, "status": status, "source": "memory"})

    # 磁盘上的历史运行
    outputs_dir = Path("outputs")
    if outputs_dir.exists():
        for run_dir in sorted(outputs_dir.iterdir(), reverse=True):
            if run_dir.is_dir() and run_dir.name not in _run_status:
                runs.append({
                    "run_id": run_dir.name,
                    "status": "completed",
                    "source": "disk",
                })

    return runs


@router.get("/{run_id}/status")
async def get_simulation_status(run_id: str) -> SimulationStatus:
    """获取模拟运行状态。"""
    if run_id in _run_status:
        return SimulationStatus(
            run_id=run_id,
            status=_run_status[run_id],
            result=_run_results.get(run_id),
        )

    # 检查磁盘
    result_file = Path("outputs") / run_id / "aggregated_results.json"
    if result_file.exists():
        import json
        result = json.loads(result_file.read_text(encoding="utf-8"))
        return SimulationStatus(run_id=run_id, status="completed", result=result)

    raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在")


@router.get("/{run_id}")
async def get_simulation_result(run_id: str) -> dict[str, Any]:
    """获取完整模拟结果。"""
    if run_id in _run_results:
        return _run_results[run_id]

    result_file = Path("outputs") / run_id / "aggregated_results.json"
    if result_file.exists():
        import json
        return json.loads(result_file.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在或尚未完成")
