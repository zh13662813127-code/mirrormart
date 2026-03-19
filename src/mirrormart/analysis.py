"""结果分析模块 — 读取已运行的模拟输出并打印摘要。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_run(run_dir: str | Path) -> dict[str, Any]:
    """加载一次模拟运行的聚合结果。

    Args:
        run_dir: 运行目录路径（如 outputs/run_20260309_143022）

    Returns:
        聚合结果字典
    """
    run_path = Path(run_dir)
    agg_file = run_path / "aggregated_results.json"
    if not agg_file.exists():
        raise FileNotFoundError(f"聚合结果文件不存在: {agg_file}")
    with open(agg_file, encoding="utf-8") as f:
        return json.load(f)


def load_branch_events(run_dir: str | Path, branch_id: int) -> list[dict[str, Any]]:
    """加载特定分支的事件流。

    Args:
        run_dir: 运行目录
        branch_id: 分支编号

    Returns:
        事件列表
    """
    events_file = Path(run_dir) / f"branch_{branch_id}" / "events.jsonl"
    if not events_file.exists():
        return []
    events = []
    with open(events_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def get_agent_journey(
    run_dir: str | Path,
    branch_id: int,
    agent_id: str,
) -> list[dict[str, Any]]:
    """提取特定 Agent 在特定分支的个体旅程。

    Args:
        run_dir: 运行目录
        branch_id: 分支编号
        agent_id: Agent ID

    Returns:
        该 Agent 的行为步骤列表
    """
    events = load_branch_events(run_dir, branch_id)
    return [e for e in events if e.get("agent_id") == agent_id]


def print_summary(run_dir: str | Path) -> None:
    """打印模拟运行摘要。

    Args:
        run_dir: 运行目录
    """
    results = load_run(run_dir)
    print(f"\n{'='*50}")
    print(f"模拟结果摘要 — {results.get('run_id', '')}")
    print(f"{'='*50}")
    print(f"分支数: {results['num_branches']}")
    print(f"\n结局概率分布:")
    for outcome, prob in results["outcome_distribution"].items():
        bar = "█" * int(prob * 20)
        print(f"  {outcome:8s} {bar} {prob*100:.0f}%")

    metrics = results.get("metrics", {})
    cr = metrics.get("conversion_rate", {})
    mp = metrics.get("main_product_purchases", {})
    print(f"\n主产品转化率: {cr.get('mean', 0):.1%} ± {cr.get('std', 0):.3f}")
    print(f"主产品购买次数: {mp.get('mean', 0):.1f} ± {mp.get('std', 0):.1f}")
    print(f"各分支转化率: {cr.get('values', [])}")
    print(f"{'='*50}\n")


def compare_runs(run_dir_a: str | Path, run_dir_b: str | Path) -> None:
    """比较两次模拟运行的结果（A/B 对比）。

    Args:
        run_dir_a: 方案 A 的运行目录
        run_dir_b: 方案 B 的运行目录
    """
    a = load_run(run_dir_a)
    b = load_run(run_dir_b)

    print(f"\n{'='*60}")
    print(f"A/B 对比分析")
    print(f"{'='*60}")

    cr_a = a.get("metrics", {}).get("conversion_rate", {}).get("mean", 0)
    cr_b = b.get("metrics", {}).get("conversion_rate", {}).get("mean", 0)
    delta = cr_b - cr_a
    direction = "↑" if delta > 0 else "↓"

    print(f"\n转化率对比:")
    print(f"  方案 A: {cr_a:.1%}")
    print(f"  方案 B: {cr_b:.1%}")
    print(f"  差异:  {direction} {abs(delta):.1%}")

    print(f"\n结局分布对比:")
    all_outcomes = set(a["outcome_distribution"]) | set(b["outcome_distribution"])
    for outcome in sorted(all_outcomes):
        pa = a["outcome_distribution"].get(outcome, 0)
        pb = b["outcome_distribution"].get(outcome, 0)
        print(f"  {outcome:8s}: A={pa*100:.0f}%  B={pb*100:.0f}%")

    print(f"{'='*60}\n")
