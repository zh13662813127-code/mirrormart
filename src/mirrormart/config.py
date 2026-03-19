"""配置加载模块。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """手动加载 .env 文件（避免额外依赖 python-dotenv）。"""
    env_file = Path(".env")
    if not env_file.exists():
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # 只在未设置时写入（不覆盖已有环境变量）
                os.environ.setdefault(key, value)


# 模块加载时自动读取 .env
_load_dotenv()


@dataclass
class SimulationConfig:
    """Phase 0 模拟配置。"""

    scenario_path: str
    num_agents: int = 20
    num_branches: int = 5
    num_steps: int = 20
    llm_model: str = "openai/MiniMax-Text-01"
    api_base: str = ""          # 自定义 API base URL（MiniMax 等需要）
    api_key: str = ""           # API Key
    output_dir: str = "outputs"
    log_level: str = "INFO"
    max_memory_per_agent: int = 100
    temperature: float = 0.8
    max_tokens: int = 512

    @classmethod
    def from_env(cls, scenario_path: str) -> "SimulationConfig":
        """从环境变量加载配置（优先级高于默认值）。"""
        return cls(
            scenario_path=scenario_path,
            num_agents=int(os.getenv("MM_NUM_AGENTS", "20")),
            num_branches=int(os.getenv("MM_NUM_BRANCHES", "5")),
            num_steps=int(os.getenv("MM_NUM_STEPS", "20")),
            llm_model=os.getenv("MM_LLM_MODEL", "openai/MiniMax-Text-01"),
            api_base=os.getenv("MINIMAX_API_BASE", "https://api.minimax.chat/v1"),
            api_key=os.getenv("MINIMAX_API_KEY", ""),
            output_dir=os.getenv("MM_OUTPUT_DIR", "outputs"),
            temperature=float(os.getenv("MM_TEMPERATURE", "0.8")),
            max_tokens=int(os.getenv("MM_MAX_TOKENS", "2048")),
        )
