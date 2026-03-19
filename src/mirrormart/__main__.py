"""镜市 MirrorMart — CLI 入口。

用法:
    uv run python -m mirrormart                              # 使用默认场景
    uv run python -m mirrormart --scenario scenarios/facemask_launch.yml
    uv run python -m mirrormart --branches 3 --steps 10     # 快速测试
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from mirrormart.config import SimulationConfig
from mirrormart.engine import SimulationEngine


def setup_logging(level: str = "INFO") -> None:
    """配置日志格式。"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # 静默第三方库的 DEBUG 日志
    for lib in ("httpx", "httpcore", "openai", "litellm"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def main() -> None:
    """主函数。"""
    parser = argparse.ArgumentParser(
        description="镜市 MirrorMart — 中国社会模拟引擎 (Phase 0)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        default="scenarios/facemask_launch.yml",
        help="场景配置文件路径",
    )
    parser.add_argument("--branches", type=int, default=None, help="蒙特卡洛分支数（覆盖场景配置）")
    parser.add_argument("--steps", type=int, default=None, help="每分支时间步数（覆盖场景配置）")
    parser.add_argument("--model", default=None, help="LLM 模型标识（litellm 格式）")
    parser.add_argument("--output-dir", default="outputs", help="输出目录")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()

    setup_logging(args.log_level)

    config = SimulationConfig.from_env(scenario_path=args.scenario)
    if args.branches:
        config.num_branches = args.branches
    if args.steps:
        config.num_steps = args.steps
    if args.model:
        config.llm_model = args.model
    if args.output_dir:
        config.output_dir = args.output_dir

    print(f"\n{'='*60}")
    print(f"  镜市 MirrorMart — Phase 0 模拟")
    print(f"{'='*60}")
    print(f"  场景: {args.scenario}")
    print(f"  模型: {config.llm_model}")
    print(f"  分支: {config.num_branches}  步数: {config.num_steps}")
    print(f"{'='*60}\n")

    engine = SimulationEngine(config)
    result = asyncio.run(engine.run_monte_carlo())

    print(f"\n{'='*60}")
    print(f"  模拟完成！运行ID: {result.get('run_id', '')}")
    print(f"  结局分布: {result.get('outcome_distribution', {})}")
    print(f"  平均转化率: {result.get('metrics', {}).get('conversion_rate', {}).get('mean', 0):.1%}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
