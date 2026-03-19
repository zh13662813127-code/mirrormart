# 镜市 MirrorMart — 技术规范文档 (Tech Spec)

> 版本 1.0 · 2026-03 · 状态: Phase 0 准备中

---

## 1. 技术架构总览

```
┌─────────────────────────────────────────────────────┐
│                   前端展示层                          │
│         React + ECharts + G6 (AntV)                  │
├─────────────────────────────────────────────────────┤
│                   API 网关层                          │
│            FastAPI + WebSocket                        │
├──────────┬──────────┬───────────┬───────────────────┤
│ 模拟引擎  │ Agent系统 │ 平台插件   │  蒙特卡洛执行器   │
│  SimPy   │ 记忆/人设 │ 小红书/抖音 │  Ray分布式       │
│  调度器   │ 认知循环  │ 淘宝/微博  │  状态分叉        │
├──────────┴──────────┴───────────┴───────────────────┤
│                  LLM 推理层                           │
│     SGLang/vLLM (本地) + API网关 (云端)               │
│     三级模型路由: 日常→社交→复杂                       │
├─────────────────────────────────────────────────────┤
│                   数据存储层                          │
│  Redis(热缓存) Neo4j(图谱) TimescaleDB(时序) PG(元数据)│
│  Chroma→Qdrant (向量记忆)                            │
└─────────────────────────────────────────────────────┘
```

---

## 2. 技术栈确认

### 2.1 语言与运行时
- **核心引擎**: Python 3.11+（async/await 原生支持）
- **前端**: TypeScript + React 18
- **构建工具**: uv (Python包管理), pnpm (前端包管理)
- **容器化**: Docker + Docker Compose

### 2.2 核心依赖

| 层级 | 技术 | 版本要求 | 用途 |
|------|------|---------|------|
| LLM推理 | litellm | latest | 统一多模型API调用网关 |
| LLM推理 | SGLang | >=0.3 | 本地模型高性能推理 |
| Agent框架 | 自研 (基于OASIS模式) | - | 核心Agent循环与调度 |
| 模拟引擎 | SimPy | >=4.0 | 离散事件时间管理 |
| 分布式 | Ray | >=2.9 | 多分支并行执行 |
| 向量数据库 | chromadb | >=0.4 | Agent记忆存储(Phase 0-1) |
| 缓存 | redis | >=7.0 | 热状态+事件流+LLM缓存 |
| 图数据库 | neo4j | >=5.0 | 社交关系图谱 |
| 时序数据库 | timescaledb | >=2.0 | 行为轨迹+指标时序 |
| 关系数据库 | postgresql | >=15 | 元数据+配置+运行记录 |
| Web框架 | FastAPI | >=0.100 | REST API + WebSocket |
| 前端框架 | React | 18.x | 用户界面 |
| 可视化 | ECharts | >=5.0 | 图表+概率分布 |
| 可视化 | @antv/g6 | >=5.0 | 社交网络图 |

### 2.3 开发工具
- **编辑器**: Cursor (AI原生) / VS Code
- **AI编码**: Claude Code + Codex
- **版本控制**: Git + GitHub
- **CI/CD**: GitHub Actions
- **代码质量**: ruff (lint) + mypy (类型检查) + pytest (测试)
- **文档**: MkDocs + mkdocs-material (中英双语)

---

## 3. 项目目录结构

```
mirrormart/
├── CLAUDE.md                    # Claude Code 规则文件
├── progress.txt                 # 当前进度追踪
├── lessons.md                   # 经验教训记录
├── pyproject.toml               # Python项目配置 (uv)
├── docker-compose.yml           # 本地开发环境编排
├── .github/
│   └── workflows/
│       ├── ci.yml               # 代码检查+测试
│       └── release.yml          # PyPI发布
│
├── src/
│   └── mirrormart/
│       ├── __init__.py
│       ├── core/                # 核心引擎
│       │   ├── __init__.py
│       │   ├── engine.py        # 模拟引擎主循环
│       │   ├── scheduler.py     # Agent激活调度器
│       │   ├── monte_carlo.py   # 蒙特卡洛运行器+状态分叉
│       │   ├── event_bus.py     # 事件总线(Redis Streams)
│       │   └── config.py        # 全局配置
│       │
│       ├── agents/              # Agent系统
│       │   ├── __init__.py
│       │   ├── base.py          # BaseAgent抽象类
│       │   ├── persona.py       # 人设加载器(YAML→对象)
│       │   ├── memory/
│       │   │   ├── __init__.py
│       │   │   ├── stream.py    # 记忆流(Memory Stream)
│       │   │   ├── retrieval.py # 加权检索(时间×重要性×相关性)
│       │   │   └── reflection.py # 反思合成
│       │   ├── cognition/
│       │   │   ├── __init__.py
│       │   │   ├── perceive.py  # 感知:从环境获取信息
│       │   │   ├── decide.py    # 决策:LLM推理+人设约束
│       │   │   ├── act.py       # 行动:在平台执行操作
│       │   │   └── plan.py      # 规划:日程生成与更新
│       │   └── profiles/        # Agent画像模板(YAML)
│       │       ├── consumer_rational.yml
│       │       ├── consumer_impulsive.yml
│       │       ├── kol_beauty.yml
│       │       ├── kol_tech.yml
│       │       └── merchant.yml
│       │
│       ├── platforms/           # 平台环境插件
│       │   ├── __init__.py
│       │   ├── base.py          # PlatformBase抽象类
│       │   ├── registry.py      # 插件注册器(@register_platform)
│       │   ├── xiaohongshu/     # 小红书环境
│       │   │   ├── __init__.py
│       │   │   ├── environment.py   # 环境主体
│       │   │   ├── feed.py          # 信息流推荐(种草发现)
│       │   │   ├── actions.py       # 用户行为(发帖/点赞/收藏/评论)
│       │   │   ├── content.py       # 内容对象(笔记/评论)
│       │   │   └── config.yml       # 平台规则配置
│       │   ├── taobao/          # 淘宝环境
│       │   │   ├── __init__.py
│       │   │   ├── environment.py
│       │   │   ├── search.py        # 搜索+比价
│       │   │   ├── actions.py       # 浏览/加购/购买/评价
│       │   │   ├── product.py       # 商品对象
│       │   │   └── config.yml
│       │   ├── douyin/          # 抖音环境 (Phase 2)
│       │   └── weibo/           # 微博环境 (Phase 2)
│       │
│       ├── llm/                 # LLM集成层
│       │   ├── __init__.py
│       │   ├── router.py        # 三级模型路由器
│       │   ├── cache.py         # 推理结果缓存(Redis)
│       │   ├── prompts/         # Prompt模板
│       │   │   ├── perceive.py
│       │   │   ├── decide.py
│       │   │   ├── reflect.py
│       │   │   └── plan.py
│       │   └── providers/       # 模型提供商适配器
│       │       ├── __init__.py
│       │       ├── openai_compat.py  # OpenAI兼容接口
│       │       ├── dashscope.py      # 阿里云/Qwen
│       │       └── local.py          # SGLang/vLLM本地
│       │
│       ├── calibration/         # 联网校准模块
│       │   ├── __init__.py
│       │   ├── search.py        # 搜索API调用
│       │   ├── injector.py      # 数据注入到Agent认知
│       │   └── sources/
│       │       ├── tavily.py
│       │       ├── serpapi.py
│       │       └── media_crawler.py
│       │
│       ├── analysis/            # 结果分析
│       │   ├── __init__.py
│       │   ├── aggregator.py    # 多路径结果聚合
│       │   ├── distributions.py # 概率分布计算
│       │   ├── journey.py       # 个体旅程提取
│       │   └── comparison.py    # A/B干预对比
│       │
│       └── api/                 # Web API
│           ├── __init__.py
│           ├── app.py           # FastAPI应用入口
│           ├── routes/
│           │   ├── simulations.py   # 模拟CRUD+控制
│           │   ├── agents.py        # Agent查询
│           │   ├── results.py       # 结果查询
│           │   └── ws.py            # WebSocket实时推送
│           └── schemas/         # Pydantic模型
│               ├── simulation.py
│               ├── agent.py
│               └── result.py
│
├── scenarios/                   # 场景模板(YAML)
│   ├── ecommerce_launch.yml     # 电商产品发布
│   ├── crisis_management.yml    # 舆情危机
│   ├── kol_campaign.yml         # KOL种草活动
│   └── price_war.yml            # 价格战模拟
│
├── frontend/                    # 前端项目
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   ├── components/
│   │   └── hooks/
│   └── public/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
└── docs/                        # MkDocs文档
    ├── mkdocs.yml
    ├── en/
    └── zh/
```

---

## 4. LLM 推理架构

### 4.1 统一调用网关

使用 `litellm` 作为统一网关，屏蔽不同模型提供商的 API 差异:

```python
# src/mirrormart/llm/router.py
from enum import Enum

class DecisionTier(Enum):
    ROUTINE = "routine"      # 日常行为: 吃饭/刷手机/睡觉
    SOCIAL = "social"        # 社交行为: 对话/评论/反应
    COMPLEX = "complex"      # 复杂决策: 重大购买/危机反应/创作

# 路由规则 (可通过config.yml覆盖)
DEFAULT_ROUTING = {
    DecisionTier.ROUTINE: "ollama/qwen2.5:7b",      # 本地轻量
    DecisionTier.SOCIAL: "anthropic/claude-haiku",    # 中端API
    DecisionTier.COMPLEX: "anthropic/claude-sonnet",  # 前沿API
}
```

### 4.2 Prompt 缓存策略
- 所有 Agent 共享的系统提示词（世界观、平台规则、时间步）作为 prefix
- 仅 Agent 个人记忆和当前感知作为变量部分
- 利用 SGLang RadixAttention 或 API 提供商的 prompt caching
- Redis 缓存相同 (状态hash + 输入hash) 的推理结果用于跨分支复用

---

## 5. Agent 认知循环

每个时间步，每个活跃 Agent 执行:

```
perceive() → decide() → act() → [reflect()]
    ↑                                  │
    └──────── 记忆流更新 ←─────────────┘
```

### 5.1 perceive (感知)
- 从当前所在平台环境获取可见信息（信息流、搜索结果、通知）
- 经过注意力过滤（基于人设中的关注偏好）
- 输出: 结构化的感知摘要

### 5.2 decide (决策)
- 输入: 感知摘要 + 检索到的相关记忆 + 当前计划
- LLM 推理: 基于人设约束生成行动决策
- 输出: 具体行动指令 (如 "在这条笔记下评论: 成分看着不错但价格偏高")
- 决策分级: 根据行动复杂度路由到不同 LLM 层级

### 5.3 act (行动)
- 在平台环境中执行决策
- 产生副作用（新内容、互动数据、状态变更）
- 记录到记忆流（带时间戳和重要性评分）

### 5.4 reflect (反思) — 条件触发
- 触发条件: 累积记忆重要性超过阈值（默认每模拟日 2-3 次）
- 行为: 综合近期记忆生成高层洞察
- 输出: 抽象认知（如 "这个品牌的产品评价两极分化，我需要更多信息"）
- 洞察存回记忆流，影响后续决策

---

## 6. 蒙特卡洛执行架构

### 6.1 状态分叉机制

```python
# 概念示意 (非最终实现)
class SimulationState:
    """可分叉的模拟状态"""
    branch_id: str
    parent_branch_id: str | None
    agents: dict[str, AgentState]      # Copy-on-Write
    platform_states: dict[str, Any]    # Copy-on-Write
    global_time: int
    rng_seed: int                      # 每分支独立随机种子
```

### 6.2 分支策略
- **完全独立**: 每个分支从起点独立运行（Phase 0-1 默认）
- **决策点分叉**: 在关键决策点复制状态并分叉（Phase 3 目标）
- 所有分支共享 `branch_id` 标签，写入 TimescaleDB 后可跨分支聚合

### 6.3 结果聚合

```python
class SimulationResult:
    """多路径聚合结果"""
    total_branches: int
    outcome_distribution: dict[str, float]   # {"爆款": 0.3, "平淡": 0.55, "危机": 0.15}
    key_metrics: dict[str, Distribution]     # 每指标的统计分布
    critical_events: list[CriticalEvent]     # 跨分支的关键转折点
    agent_journeys: dict[str, list[Journey]] # 典型Agent的多分支旅程对比
```

---

## 7. 数据库 Schema 概要

### 7.1 PostgreSQL (元数据)
- `simulations`: 模拟运行记录 (id, config, status, created_at)
- `branches`: 分支信息 (id, simulation_id, parent_id, seed, status)
- `agent_profiles`: Agent画像模板 (id, name, persona_yaml, category)
- `scenarios`: 场景模板 (id, name, config_yaml, category)

### 7.2 Redis (热状态)
- `agent:{branch_id}:{agent_id}:state`: 当前Agent状态
- `agent:{branch_id}:{agent_id}:memory:recent`: 近期记忆窗口
- `platform:{branch_id}:{platform}:feed`: 当前信息流
- `llm:cache:{hash}`: 推理结果缓存
- Stream: `events:{branch_id}`: 事件流

### 7.3 Neo4j (社交图谱)
- Nodes: Agent, Content, Product
- Edges: FOLLOWS, LIKES, COMMENTS_ON, PURCHASES, INFLUENCED_BY
- 属性: branch_id, timestamp, weight

### 7.4 TimescaleDB (时序)
- `agent_metrics`: (time, branch_id, agent_id, metric_name, value)
- `platform_metrics`: (time, branch_id, platform, metric_name, value)
- `content_metrics`: (time, branch_id, content_id, views, likes, comments)

### 7.5 Chroma/Qdrant (向量)
- Collection per agent per branch: `memory_{branch_id}_{agent_id}`
- 每条记忆: text + embedding + metadata(timestamp, importance, type)

---

## 8. API 设计概要

### 8.1 REST Endpoints

```
POST   /api/v1/simulations              # 创建模拟
GET    /api/v1/simulations/{id}         # 查询模拟状态
POST   /api/v1/simulations/{id}/run     # 启动运行
POST   /api/v1/simulations/{id}/intervene  # 注入干预
GET    /api/v1/simulations/{id}/results # 获取聚合结果
GET    /api/v1/simulations/{id}/branches/{bid}/agents  # 特定分支的Agent列表
GET    /api/v1/agents/{id}/journey?branch_id=xxx       # Agent个体旅程
WS     /api/v1/simulations/{id}/stream  # 实时事件流
```

---

## 9. Phase 分阶段技术目标

| Phase | Agent数 | 分支数 | 平台 | LLM | 存储 | 分布式 |
|-------|---------|--------|------|-----|------|--------|
| 0 | 20 | 5 | 小红书+淘宝(简化) | 单一API | 内存+JSON文件 | 否 |
| 1 | 25-100 | 10 | 小红书+淘宝 | litellm网关 | Chroma+Redis | 否 |
| 2 | 500 | 20 | +抖音 | SGLang本地+API | +Neo4j+TimescaleDB | 单机Ray |
| 3 | 1000+ | 50+ | +微博 | 三级路由 | +Qdrant | 多机Ray |

### Phase 0 极简技术栈
- Python 3.11 + asyncio
- 一个 LLM API (通过 litellm)
- 数据存储: Python dict + JSON dump
- 无数据库、无前端、无Docker
- 输出: 终端日志 + JSON 结果文件 + Jupyter 分析笔记本
