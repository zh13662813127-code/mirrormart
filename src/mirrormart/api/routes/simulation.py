"""模拟管理 REST API 路由。

端点:
  POST /simulations                — 创建并启动模拟
  GET  /simulations                — 列出所有运行记录
  GET  /simulations/{run_id}       — 获取单次运行结果
  GET  /simulations/{run_id}/status — 获取运行状态
  GET  /simulations/{run_id}/branch/{branch_id} — 获取分支详情
  GET  /simulations/compare        — A/B 对比两次运行
  GET  /scenarios                  — 列出可用场景
  POST /scenarios/upload           — 上传自定义场景 YAML
  GET  /profiles                   — 列出可用人设
  GET  /config                     — 获取系统配置
  PUT  /config                     — 更新系统配置
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mirrormart.api.websocket import EventQueue
from mirrormart.config import SimulationConfig
from mirrormart.engine import SimulationEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])

# 内存状态存储
_run_status: dict[str, str] = {}
_run_results: dict[str, dict[str, Any]] = {}
_run_engines: dict[str, SimulationEngine] = {}  # 引擎实例（暂停/恢复用）


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


def _inject_materials(engine: SimulationEngine) -> None:
    """将已上传物料注入引擎的场景配置。"""
    materials_file = Path("materials") / "materials.json"
    if not materials_file.exists():
        return
    materials = json.loads(materials_file.read_text(encoding="utf-8"))
    if not materials:
        return

    platforms = engine.scenario.setdefault("platforms", [])
    platform_map: dict[str, dict] = {}
    for p in platforms:
        platform_map[p["type"]] = p

    for mat in materials:
        ptype = mat["platform"]
        if ptype not in platform_map:
            platform_map[ptype] = {"type": ptype, "initial_content": []}
            platforms.append(platform_map[ptype])

        entry = {
            "title": mat.get("title", ""),
            "content": mat.get("content", ""),
            "tags": mat.get("tags", []),
            "author_id": "brand_official",
        }
        if ptype in ("xiaohongshu", "douyin", "weibo"):
            key = "initial_content"
        else:
            continue

        platform_map[ptype].setdefault(key, []).append(entry)

    logger.info("已注入 %d 条物料到场景", len(materials))


# ──────────────── 后台任务 ────────────────

async def _run_simulation(run_id: str, config: SimulationConfig) -> None:
    """后台异���执行模拟（含 WebSocket 事���推送）。"""
    _run_status[run_id] = "running"
    event_queue = EventQueue(run_id)
    event_queue.start()

    try:
        engine = SimulationEngine(config, event_callback=event_queue.put)
        # 注入已上传的物料到场景
        _inject_materials(engine)
        _run_engines[run_id] = engine
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
        _run_engines.pop(run_id, None)
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


@router.post("/{run_id}/pause")
async def pause_simulation(run_id: str) -> dict[str, str]:
    """暂停正在运行的模拟。"""
    engine = _run_engines.get(run_id)
    if not engine:
        raise HTTPException(404, f"运行 {run_id} 不存在或已结束")
    if engine.is_paused:
        return {"status": "already_paused", "run_id": run_id}
    engine.pause()
    _run_status[run_id] = "paused"
    return {"status": "paused", "run_id": run_id}


@router.post("/{run_id}/resume")
async def resume_simulation(run_id: str) -> dict[str, str]:
    """恢复暂停的模拟。"""
    engine = _run_engines.get(run_id)
    if not engine:
        raise HTTPException(404, f"运行 {run_id} 不存在或已结束")
    if not engine.is_paused:
        return {"status": "already_running", "run_id": run_id}
    engine.resume()
    _run_status[run_id] = "running"
    return {"status": "running", "run_id": run_id}


# ──────────────── 物料上传 ────────────────

MATERIALS_DIR = Path("materials")


@router.post("/materials/upload")
async def upload_material(
    platform: str = Query(..., description="目标平台: xiaohongshu/douyin/weibo"),
    title: str = Query("", description="内容标题"),
    content: str = Query("", description="文案内容"),
    tags: str = Query("", description="标签，逗号分隔"),
    file: UploadFile | None = File(default=None, description="图片/视频文件"),
) -> dict[str, Any]:
    """上传营销物料（图文/视频），用于注入模拟初始内容。"""
    MATERIALS_DIR.mkdir(exist_ok=True)
    material_id = f"mat_{int(time.time() * 1000)}"

    # 保存上传的文件
    file_path = None
    if file and file.filename:
        ext = Path(file.filename).suffix
        file_path = str(MATERIALS_DIR / f"{material_id}{ext}")
        file_data = await file.read()
        Path(file_path).write_bytes(file_data)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    material = {
        "id": material_id,
        "platform": platform,
        "title": title,
        "content": content,
        "tags": tag_list,
        "file_path": file_path,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 追加到物料列表
    materials_file = MATERIALS_DIR / "materials.json"
    materials: list[dict] = []
    if materials_file.exists():
        materials = json.loads(materials_file.read_text(encoding="utf-8"))
    materials.append(material)
    materials_file.write_text(json.dumps(materials, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "ok", "material": material}


@router.get("/materials")
async def list_materials() -> list[dict[str, Any]]:
    """列出已上传的物料。"""
    materials_file = MATERIALS_DIR / "materials.json"
    if not materials_file.exists():
        return []
    return json.loads(materials_file.read_text(encoding="utf-8"))


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str) -> dict[str, str]:
    """删除物料。"""
    materials_file = MATERIALS_DIR / "materials.json"
    if not materials_file.exists():
        raise HTTPException(404, "物料不存在")
    materials = json.loads(materials_file.read_text(encoding="utf-8"))
    new_materials = [m for m in materials if m["id"] != material_id]
    if len(new_materials) == len(materials):
        raise HTTPException(404, f"物料 {material_id} 不存在")
    # 删除关联文件
    removed = [m for m in materials if m["id"] == material_id]
    for m in removed:
        if m.get("file_path") and Path(m["file_path"]).exists():
            Path(m["file_path"]).unlink()
    materials_file.write_text(json.dumps(new_materials, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "deleted", "material_id": material_id}


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


@router.get("/{run_id}/report")
async def get_report(run_id: str) -> dict[str, Any]:
    """获取模拟分析报告（Markdown 格式）。"""
    report_path = Path("outputs") / run_id / "analysis.md"
    if not report_path.exists():
        raise HTTPException(404, f"报告 {run_id} 不存在")
    content = report_path.read_text(encoding="utf-8")
    return {"run_id": run_id, "report": content}


@router.get("/{run_id}/export")
async def export_csv(run_id: str) -> StreamingResponse:
    """将模拟事件导出为 CSV 文件。"""
    run_dir = Path("outputs") / run_id
    if not run_dir.exists():
        raise HTTPException(404, f"运行 {run_id} 不存在")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "branch", "step", "agent_id", "platform", "action_type",
        "target_id", "thinking", "effect", "interest_level", "purchase_intent",
    ])

    for branch_dir in sorted(run_dir.iterdir()):
        events_file = branch_dir / "events.jsonl"
        if not events_file.exists():
            continue
        branch_id = branch_dir.name.replace("branch_", "")
        for line in events_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line:
                continue
            ev = json.loads(line)
            action = ev.get("action", {})
            state = ev.get("internal_state", {})
            writer.writerow([
                branch_id,
                ev.get("branch_step", ""),
                ev.get("agent_id", ""),
                ev.get("platform", ""),
                action.get("type", ""),
                action.get("target_id", ""),
                ev.get("thinking", "")[:200],
                ev.get("result", {}).get("effect", ""),
                state.get("interest_level", ""),
                state.get("purchase_intent", ""),
            ])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.csv"'},
    )


@router.get("/{run_id}/journeys")
async def get_agent_journeys(run_id: str, branch_id: int = 0) -> dict[str, Any]:
    """获取指定分支中所有 Agent 的决策旅程。"""
    states_path = Path("outputs") / run_id / f"branch_{branch_id}" / "agent_states.json"
    if not states_path.exists():
        raise HTTPException(404, f"分支 {run_id}/branch_{branch_id} 不存在")

    agent_states = json.loads(states_path.read_text(encoding="utf-8"))
    journeys: dict[str, Any] = {}

    for agent_id, state in agent_states.items():
        steps = []
        for log in state.get("action_log", []):
            action = log.get("action", {})
            internal = log.get("internal_state", {})
            steps.append({
                "step": log.get("step", 0),
                "platform": action.get("platform", ""),
                "action_type": action.get("type", ""),
                "target_id": action.get("target_id", ""),
                "thinking": log.get("thinking", "")[:150],
                "effect": log.get("result", {}).get("effect", ""),
                "interest_level": internal.get("interest_level", 0),
                "purchase_intent": internal.get("purchase_intent", 0),
            })
        journeys[agent_id] = {
            "persona_name": state.get("persona_name", agent_id),
            "final_state": state.get("internal_state", {}),
            "total_actions": len(steps),
            "steps": steps,
        }

    return {"run_id": run_id, "branch_id": branch_id, "journeys": journeys}


@router.get("/{run_id}/sentiment")
async def get_sentiment(run_id: str, branch_id: int = 0) -> dict[str, Any]:
    """获取指定分支的情感分析数据。"""
    branch = _load_branch(run_id, branch_id)
    if not branch:
        raise HTTPException(404, f"分支 {run_id}/branch_{branch_id} 不存在")
    sentiment = branch.get("sentiment", {})
    return {"run_id": run_id, "branch_id": branch_id, "sentiment": sentiment}


@router.get("/{run_id}/kol")
async def get_kol_performance(run_id: str, branch_id: int = 0) -> dict[str, Any]:
    """获取指定分支的 KOL 影响力数据。"""
    branch = _load_branch(run_id, branch_id)
    if not branch:
        raise HTTPException(404, f"分支 {run_id}/branch_{branch_id} 不存在")
    kol = branch.get("kol", {})
    return {"run_id": run_id, "branch_id": branch_id, "kol": kol}


@router.get("/{run_id}/temporal")
async def get_temporal_analysis(run_id: str, branch_id: int | None = None) -> dict[str, Any]:
    """获取时间维度分析数据。

    不指定 branch_id 时返回聚合数据，指定时返回单分支数据。
    """
    if branch_id is not None:
        branch = _load_branch(run_id, branch_id)
        if not branch:
            raise HTTPException(404, f"分支 {run_id}/branch_{branch_id} 不存在")
        temporal = branch.get("temporal", {})
        return {"run_id": run_id, "branch_id": branch_id, "temporal": temporal}

    # 返回聚合数据
    result = _load_result(run_id)
    if not result:
        raise HTTPException(404, f"运行 {run_id} 不存在")
    temporal = result.get("temporal_overview", {})
    return {"run_id": run_id, "temporal": temporal}


@router.get("/{run_id}")
async def get_simulation_result(run_id: str) -> dict[str, Any]:
    """获取完整模拟结果。"""
    result = _load_result(run_id)
    if result:
        return result
    raise HTTPException(404, f"运行 {run_id} 不存在或尚未完成")


# ──────────────── 场景与人设管理 ────────────────

# 使用独立 router 避免被 /{run_id} 路径吞掉
scenario_router = APIRouter(tags=["scenarios"])
profile_router = APIRouter(tags=["profiles"])

SCENARIOS_DIR = Path("scenarios")
PROFILES_DIR = Path("profiles")


@scenario_router.get("/scenarios")
async def list_scenarios() -> list[dict[str, Any]]:
    """列出所有可用场景文件。"""
    scenarios = []
    if not SCENARIOS_DIR.exists():
        return scenarios
    for yml_file in sorted(SCENARIOS_DIR.glob("*.yml")):
        try:
            data = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
            scenarios.append({
                "file": f"scenarios/{yml_file.name}",
                "id": data.get("id", yml_file.stem),
                "name": data.get("name", yml_file.stem),
                "description": data.get("description", ""),
                "num_steps": data.get("simulation", {}).get("num_steps", 20),
                "num_branches": data.get("simulation", {}).get("num_branches", 5),
            })
        except Exception:
            scenarios.append({"file": f"scenarios/{yml_file.name}", "id": yml_file.stem,
                              "name": yml_file.stem, "description": "解析失败"})
    return scenarios


@scenario_router.post("/scenarios/upload", status_code=201)
async def upload_scenario(file: UploadFile) -> dict[str, Any]:
    """上传自定义场景 YAML 文件。"""
    if not file.filename or not file.filename.endswith((".yml", ".yaml")):
        raise HTTPException(400, "仅支持 .yml 或 .yaml 文件")

    content = await file.read()
    try:
        data = yaml.safe_load(content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(400, f"YAML 解析失败: {e}")

    # 基础校验
    if not isinstance(data, dict):
        raise HTTPException(400, "YAML 顶层必须是字典")
    if "platforms" not in data:
        raise HTTPException(400, "缺少 platforms 配置")
    if "agents" not in data:
        raise HTTPException(400, "缺少 agents 配置")

    # 写入 scenarios 目录
    SCENARIOS_DIR.mkdir(exist_ok=True)
    dest = SCENARIOS_DIR / file.filename
    dest.write_bytes(content)

    return {
        "file": f"scenarios/{file.filename}",
        "id": data.get("id", dest.stem),
        "name": data.get("name", dest.stem),
        "message": "场景上传成功",
    }


@profile_router.get("/profiles")
async def list_profiles() -> list[dict[str, Any]]:
    """列出所有可用人设。"""
    profiles = []
    if not PROFILES_DIR.exists():
        return profiles
    for yml_file in sorted(PROFILES_DIR.glob("*.yml")):
        try:
            data = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
            profiles.append({
                "id": data.get("id", yml_file.stem),
                "name": data.get("name", yml_file.stem),
                "description": data.get("description", ""),
                "decision_style": data.get("consumer_traits", {}).get("decision_style", ""),
                "price_sensitivity": data.get("consumer_traits", {}).get("price_sensitivity", 0),
            })
        except Exception:
            profiles.append({"id": yml_file.stem, "name": yml_file.stem, "description": "解析失败"})
    return profiles


# ──────────────── 系统配置 + 模型提供商管理 ────────────────

config_router = APIRouter(tags=["config"])
ENV_FILE = Path(".env")
PROVIDERS_FILE = Path(".providers.json")

# 预设模型提供商模板
_PROVIDER_PRESETS: list[dict[str, Any]] = [
    {"id": "minimax-m2", "name": "MiniMax M2", "model": "openai/MiniMax-M2",
     "api_base": "https://api.minimaxi.com/v1", "max_tokens": 1024, "temperature": 0.8,
     "icon": "M", "color": "#6366f1"},
    {"id": "deepseek-v3", "name": "DeepSeek V3", "model": "openai/deepseek-chat",
     "api_base": "https://api.deepseek.com/v1", "max_tokens": 2048, "temperature": 0.7,
     "icon": "D", "color": "#3b82f6"},
    {"id": "deepseek-r1", "name": "DeepSeek R1", "model": "openai/deepseek-reasoner",
     "api_base": "https://api.deepseek.com/v1", "max_tokens": 4096, "temperature": 0.6,
     "icon": "R", "color": "#2563eb"},
    {"id": "qwen-max", "name": "Qwen Max", "model": "openai/qwen-max",
     "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "max_tokens": 2048, "temperature": 0.8,
     "icon": "Q", "color": "#8b5cf6"},
    {"id": "glm-4-plus", "name": "GLM-4-Plus", "model": "openai/glm-4-plus",
     "api_base": "https://open.bigmodel.cn/api/paas/v4", "max_tokens": 2048, "temperature": 0.7,
     "icon": "G", "color": "#10b981"},
    {"id": "openai-gpt4o", "name": "GPT-4o", "model": "gpt-4o",
     "api_base": "https://api.openai.com/v1", "max_tokens": 4096, "temperature": 0.7,
     "icon": "O", "color": "#000000"},
]


def _read_env() -> dict[str, str]:
    """读取 .env 文件为 dict。"""
    result: dict[str, str] = {}
    if not ENV_FILE.exists():
        return result
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _write_env(data: dict[str, str]) -> None:
    """将配置写回 .env 文件，保留注释行。"""
    lines: list[str] = []
    existing_keys: set[str] = set()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.partition("=")[0].strip()
                if key in data:
                    lines.append(f"{key}={data[key]}")
                    existing_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)
    for key, value in data.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_providers() -> list[dict[str, Any]]:
    if PROVIDERS_FILE.exists():
        return json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
    return []


def _save_providers(providers: list[dict[str, Any]]) -> None:
    PROVIDERS_FILE.write_text(json.dumps(providers, ensure_ascii=False, indent=2), encoding="utf-8")


def _mask_provider(p: dict[str, Any]) -> dict[str, Any]:
    result = dict(p)
    key = result.get("api_key", "")
    if key and len(key) > 12:
        result["api_key_display"] = key[:6] + "..." + key[-4:]
    elif key:
        result["api_key_display"] = "***"
    else:
        result["api_key_display"] = ""
    result.pop("api_key", None)
    return result


@config_router.get("/config")
async def get_config() -> dict[str, Any]:
    """获取系统配置 + 当前激活的 provider。"""
    env = _read_env()
    providers = _load_providers()
    active_id = env.get("MM_ACTIVE_PROVIDER", "")
    active_provider = None
    for p in providers:
        if p["id"] == active_id:
            active_provider = _mask_provider(p)
            break
    return {
        "active_provider_id": active_id,
        "active_provider": active_provider,
        "model": env.get("MM_LLM_MODEL", os.getenv("MM_LLM_MODEL", "")),
        "api_base": env.get("MINIMAX_API_BASE", os.getenv("MINIMAX_API_BASE", "")),
        "max_tokens": env.get("MM_MAX_TOKENS", os.getenv("MM_MAX_TOKENS", "1024")),
        "temperature": env.get("MM_TEMPERATURE", os.getenv("MM_TEMPERATURE", "0.8")),
        "num_branches": env.get("MM_NUM_BRANCHES", os.getenv("MM_NUM_BRANCHES", "5")),
        "num_steps": env.get("MM_NUM_STEPS", os.getenv("MM_NUM_STEPS", "20")),
    }


@config_router.get("/config/presets")
async def get_presets() -> list[dict[str, Any]]:
    """获取预设模型提供商列表。"""
    return _PROVIDER_PRESETS


@config_router.get("/config/providers")
async def list_providers() -> list[dict[str, Any]]:
    """获取已保存的 provider 列表（key 脱敏）。"""
    env = _read_env()
    active_id = env.get("MM_ACTIVE_PROVIDER", "")
    result = []
    for p in _load_providers():
        masked = _mask_provider(p)
        masked["active"] = (p["id"] == active_id)
        result.append(masked)
    return result


class ProviderCreateRequest(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    api_base: str = Field(default="")
    api_key: str = Field(default="")
    max_tokens: int = Field(default=1024)
    temperature: float = Field(default=0.8)
    icon: str = Field(default="+")
    color: str = Field(default="#94a3b8")


@config_router.post("/config/providers")
async def add_provider(request: ProviderCreateRequest) -> dict[str, Any]:
    """添加或更新一个 provider。"""
    providers = _load_providers()
    data = request.model_dump()
    for i, p in enumerate(providers):
        if p["id"] == data["id"]:
            if not data["api_key"] and p.get("api_key"):
                data["api_key"] = p["api_key"]
            providers[i] = data
            _save_providers(providers)
            return {"message": f"已更新 {data['name']}", "provider": _mask_provider(data)}
    providers.append(data)
    _save_providers(providers)
    return {"message": f"已添加 {data['name']}", "provider": _mask_provider(data)}


@config_router.delete("/config/providers/{provider_id}")
async def delete_provider(provider_id: str) -> dict[str, Any]:
    """删除一个 provider。"""
    providers = [p for p in _load_providers() if p["id"] != provider_id]
    _save_providers(providers)
    return {"message": f"已删除 {provider_id}"}


@config_router.post("/config/providers/{provider_id}/activate")
async def activate_provider(provider_id: str) -> dict[str, Any]:
    """激活一个 provider（写入 .env 并更新环境变量）。"""
    provider = None
    for p in _load_providers():
        if p["id"] == provider_id:
            provider = p
            break
    if not provider:
        raise HTTPException(404, f"Provider {provider_id} 不存在")
    env = _read_env()
    env["MM_ACTIVE_PROVIDER"] = provider_id
    env["MM_LLM_MODEL"] = provider["model"]
    env["MINIMAX_API_BASE"] = provider.get("api_base", "")
    env["MINIMAX_API_KEY"] = provider.get("api_key", "")
    env["MM_MAX_TOKENS"] = str(provider.get("max_tokens", 1024))
    env["MM_TEMPERATURE"] = str(provider.get("temperature", 0.8))
    _write_env(env)
    for k, v in env.items():
        os.environ[k] = v
    return {"message": f"已切换到 {provider['name']}", "active": _mask_provider(provider)}
