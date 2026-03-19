"""模拟管理 REST API 路由。

端点:
  POST /simulations                — 创建并启动模拟
  GET  /simulations                — 列出所有运行记录
  GET  /simulations/{run_id}       — 获取单次运行结果
  GET  /simulations/{run_id}/status — 获取运行状态
  GET  /simulations/{run_id}/branch/{branch_id} — 获取分支详情
  GET  /simulations/compare        — A/B 对比两次运行
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from mirrormart.api.websocket import EventQueue
from mirrormart.config import SimulationConfig
from mirrormart.engine import SimulationEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])

# 内存状态存储
_run_status: dict[str, str] = {}
_run_results: dict[str, dict[str, Any]] = {}


class SimulationRequest(BaseModel):
    """创建模拟的请求体。"""
    scenario: str = Field(default="scenarios/facemask_launch.yml")
    num_branches: int = Field(default=5, ge=1, le=20)
    num_steps: int = Field(default=20, ge=1, le=100)
    model: str | None = Field(default=None)


class SimulationStatus(BaseModel):
    """模拟状态响应。"""
    run_id: str
    status: str
    result: dict[str, Any] | None = None


# ──────────────── 辅助函数 ────────────────

def _load_result(run_id: str) -> dict[str, Any] | None:
    """从内存或磁盘加载运行结果。"""
    if run_id in _run_results:
        return _run_results[run_id]
    path = Path("outputs") / run_id / "aggregated_results.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _load_branch(run_id: str, branch_id: int) -> dict[str, Any] | None:
    """加载分支 summary。"""
    path = Path("outputs") / run_id / f"branch_{branch_id}" / "summary.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


# ──────────────── 后台任务 ────────────────

async def _run_simulation(run_id: str, config: SimulationConfig) -> None:
    """后台异步执行模拟（含 WebSocket 事件推送）。"""
    _run_status[run_id] = "running"
    event_queue = EventQueue(run_id)
    event_queue.start()

    try:
        engine = SimulationEngine(config, event_callback=event_queue.put)
        result = await engine.run_monte_carlo()
        result["run_id"] = run_id
        _run_results[run_id] = result
        _run_status[run_id] = "completed"
        logger.info("模拟完成: run_id=%s", run_id)
        await event_queue.put({"type": "run_complete", "run_id": run_id, "result": result})
    except Exception as e:
        logger.error("模拟失败: run_id=%s, error=%s", run_id, e)
        _run_status[run_id] = "failed"
        _run_results[run_id] = {"error": str(e)}
    finally:
        await event_queue.finish()


# ──────────────── 路由 ────────────────

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

    run_id = time.strftime("run_%Y%m%d_%H%M%S")
    _run_status[run_id] = "queued"
    background_tasks.add_task(_run_simulation, run_id, config)

    return {
        "run_id": run_id,
        "status": "queued",
        "message": f"模拟已排队，使用 GET /simulations/{run_id}/status 查看进度",
    }


@router.get("/compare")
async def compare_runs(
    run_a: str = Query(..., description="运行 A 的 ID"),
    run_b: str = Query(..., description="运行 B 的 ID"),
) -> dict[str, Any]:
    """A/B 对比两次运行的结果。"""
    result_a = _load_result(run_a)
    result_b = _load_result(run_b)
    if not result_a:
        raise HTTPException(404, f"运行 {run_a} 不存在")
    if not result_b:
        raise HTTPException(404, f"运行 {run_b} 不存在")

    ma = result_a.get("metrics", {})
    mb = result_b.get("metrics", {})

    def _cmp(key: str) -> dict[str, Any]:
        va = ma.get(key, {})
        vb = mb.get(key, {})
        a_mean = va.get("mean", 0) if isinstance(va, dict) else 0
        b_mean = vb.get("mean", 0) if isinstance(vb, dict) else 0
        return {
            "a": a_mean,
            "b": b_mean,
            "diff": round(a_mean - b_mean, 4),
            "a_values": va.get("values", []) if isinstance(va, dict) else [],
            "b_values": vb.get("values", []) if isinstance(vb, dict) else [],
        }

    comparison = {
        "conversion_rate": _cmp("conversion_rate"),
        "main_product_purchases": _cmp("main_product_purchases"),
        "xhs_posts": _cmp("xhs_posts"),
        "xhs_likes": _cmp("xhs_likes"),
    }

    # 判断赢家（以转化率为主指标）
    cr_diff = comparison["conversion_rate"]["diff"]
    if abs(cr_diff) < 0.001:
        winner = "平局"
        conclusion = "两个方案的转化率基本持平，没有显著差异。建议增加分支数或步数以获得更可靠的对比。"
    elif cr_diff > 0:
        winner = "A"
        conclusion = f"方案 A 的平均转化率高出 {abs(cr_diff)*100:.1f} 个百分点。方案 A 在当前模拟条件下表现更优。"
    else:
        winner = "B"
        conclusion = f"方案 B 的平均转化率高出 {abs(cr_diff)*100:.1f} 个百分点。方案 B 在当前模拟条件下表现更优。"

    return {
        "run_a": run_a,
        "run_b": run_b,
        "winner": winner,
        "comparison": comparison,
        "conclusion": conclusion,
        "outcome_a": result_a.get("outcome_distribution", {}),
        "outcome_b": result_b.get("outcome_distribution", {}),
    }


@router.get("")
async def list_simulations() -> list[dict[str, Any]]:
    """列出所有运行记录。"""
    runs = []
    for run_id, status in _run_status.items():
        runs.append({"run_id": run_id, "status": status, "source": "memory"})
    outputs_dir = Path("outputs")
    if outputs_dir.exists():
        for run_dir in sorted(outputs_dir.iterdir(), reverse=True):
            if run_dir.is_dir() and run_dir.name not in _run_status:
                runs.append({"run_id": run_dir.name, "status": "completed", "source": "disk"})
    return runs


@router.get("/{run_id}/status")
async def get_simulation_status(run_id: str) -> SimulationStatus:
    """获取模拟运行状态。"""
    if run_id in _run_status:
        return SimulationStatus(run_id=run_id, status=_run_status[run_id], result=_run_results.get(run_id))
    path = Path("outputs") / run_id / "aggregated_results.json"
    if path.exists():
        result = json.loads(path.read_text(encoding="utf-8"))
        return SimulationStatus(run_id=run_id, status="completed", result=result)
    raise HTTPException(404, f"运行 {run_id} 不存在")


@router.get("/{run_id}/branch/{branch_id}")
async def get_branch_detail(run_id: str, branch_id: int) -> dict[str, Any]:
    """获取单分支详细结果。"""
    branch = _load_branch(run_id, branch_id)
    if not branch:
        raise HTTPException(404, f"分支 {run_id}/branch_{branch_id} 不存在")
    return branch


@router.get("/{run_id}")
async def get_simulation_result(run_id: str) -> dict[str, Any]:
    """获取完整模拟结果。"""
    result = _load_result(run_id)
    if result:
        return result
    raise HTTPException(404, f"运行 {run_id} 不存在或尚未完成")
