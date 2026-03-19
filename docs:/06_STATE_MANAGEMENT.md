# 镜市 MirrorMart — 状态管理文档 (State Management)

> 版本 1.0 · 2026-03 · 状态: Phase 0 准备中

---

## 1. 状态管理总览

镜市的状态管理有两个独特挑战：**多 Agent 并发状态** 和 **蒙特卡洛分支状态分叉**。本文档定义了所有状态的结构、生命周期、持久化策略和分叉机制。

---

## 2. 状态层次结构

```
SimulationState (顶层)
├── config: SimulationConfig              # 不可变，所有分支共享
├── branches: dict[str, BranchState]      # 每个蒙特卡洛分支
│   └── BranchState
│       ├── branch_id: str
│       ├── seed: int                     # 随机种子
│       ├── current_step: int
│       ├── status: running|complete|failed
│       ├── agents: dict[str, AgentState] # 该分支中所有Agent
│       │   └── AgentState
│       │       ├── agent_id: str
│       │       ├── persona: PersonaConfig        # 不可变，所有分支共享
│       │       ├── current_platform: str          # 当前所在平台
│       │       ├── memories: list[Memory]         # 记忆流
│       │       ├── reflections: list[Reflection]  # 反思洞察
│       │       ├── current_plan: Plan | None      # 当前计划
│       │       ├── internal_state: InternalState   # 内部状态
│       │       │   ├── mood: float                # 情绪 [-1, 1]
│       │       │   ├── purchase_intent: dict      # 产品→购买意向
│       │       │   ├── brand_perception: dict     # 品牌→印象
│       │       │   └── information_needs: list    # 未解决的信息需求
│       │       ├── action_log: list[Action]       # 行为日志
│       │       └── is_dormant: bool               # 是否休眠
│       ├── platforms: dict[str, PlatformState]    # 该分支中的平台状态
│       │   └── PlatformState
│       │       ├── platform_type: str
│       │       ├── contents: list[Content]        # 所有内容
│       │       ├── interactions: list[Interaction] # 所有互动
│       │       └── metrics: PlatformMetrics       # 平台级指标
│       └── events: list[Event]                    # 本分支事件流
└── results: SimulationResults | None              # 聚合结果(完成后)
```

---

## 3. 核心状态对象定义

### 3.1 Memory (记忆)

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class Memory:
    """Agent记忆流中的一条记忆"""
    id: str                          # 唯一标识
    timestamp: int                   # 模拟时间步
    type: str                        # "observation" | "action" | "reflection" | "emotion"
    content: str                     # 自然语言描述
    importance: float                # 重要性评分 [1-10]，LLM评定
    embedding: list[float] | None    # 向量嵌入 (Phase 1+)
    metadata: dict = field(default_factory=dict)
    # metadata 示例:
    # {"platform": "xiaohongshu", "related_content_id": "post_001",
    #  "related_agent_id": "kol_01", "action_type": "comment"}
```

### 3.2 InternalState (内部状态)

```python
@dataclass
class InternalState:
    """Agent的内部心理状态，每步可变"""
    mood: float = 0.0                        # 情绪 [-1, 1]
    energy: float = 1.0                      # 精力 [0, 1]
    purchase_intent: dict[str, float] = field(default_factory=dict)
        # product_id → 购买意向 [0, 1]
    brand_perception: dict[str, float] = field(default_factory=dict)
        # brand_name → 好感度 [-1, 1]
    information_needs: list[str] = field(default_factory=list)
        # 当前未满足的信息需求
    social_influence_buffer: list[dict] = field(default_factory=list)
        # 待处理的社交影响事件
```

### 3.3 Action (行为记录)

```python
@dataclass
class Action:
    """Agent执行的一个行为"""
    step: int                    # 时间步
    platform: str                # 执行平台
    action_type: str             # "post"|"like"|"comment"|"search"|"purchase"|...
    target_id: str | None        # 目标对象ID
    content: str | None          # 行为内容(评论文字/搜索关键词等)
    result: dict                 # 平台返回的执行结果
    llm_reasoning: str           # LLM的推理过程(thinking字段)
    decision_tier: str           # "routine"|"social"|"complex"
```

### 3.4 Content (平台内容)

```python
@dataclass
class Content:
    """平台上的一条内容(帖子/商品/评论)"""
    id: str
    platform: str
    content_type: str            # "post"|"product"|"comment"|"review"
    author_id: str               # 创建者Agent ID 或 "system"
    title: str
    body: str
    created_at_step: int
    metrics: dict = field(default_factory=dict)
        # {"views": 0, "likes": 0, "comments": 0, "collections": 0, "shares": 0}
    metadata: dict = field(default_factory=dict)
        # 平台特定属性: {"price": 59, "rating": 4.6, "sales": 230, ...}
```

### 3.5 Event (事件)

```python
@dataclass
class Event:
    """模拟中的一个事件，用于事件流记录"""
    step: int
    branch_id: str
    agent_id: str
    event_type: str              # "action"|"state_change"|"milestone"|"anomaly"
    platform: str | None
    description: str             # 人类可读的事件描述
    data: dict                   # 结构化事件数据
    timestamp: datetime = field(default_factory=datetime.now)
```

---

## 4. 状态生命周期

### 4.1 创建阶段

```
SimulationConfig (用户输入/YAML)
    │
    ▼ 初始化
SimulationState
    ├── agents: 从画像模板生成，所有分支共享初始persona
    ├── platforms: 从场景配置初始化，注入初始内容
    └── branches: 空列表，等待模拟开始时创建
```

### 4.2 分支分叉

```
基础状态 (Base State)
    │
    ├─ fork(seed=0) ──→ Branch 0: 深拷贝Agent状态 + 平台状态
    ├─ fork(seed=1) ──→ Branch 1: 深拷贝Agent状态 + 平台状态
    ├─ fork(seed=2) ──→ Branch 2: 深拷贝Agent状态 + 平台状态
    └─ ...

每个分支从相同起点出发，因随机种子不同而走向不同路径。
```

### Phase 0 分叉实现（简单版）

```python
import copy
import random

def fork_state(base_agents, base_platforms, seed: int):
    """Phase 0: 简单的深拷贝分叉"""
    branch_agents = copy.deepcopy(base_agents)
    branch_platforms = copy.deepcopy(base_platforms)
    branch_rng = random.Random(seed)
    return branch_agents, branch_platforms, branch_rng
```

### Phase 3 分叉实现（优化版）

```python
# 使用 Copy-on-Write 避免不必要的深拷贝
# 使用 pyrsistent 持久化数据结构
from pyrsistent import PMap, pmap

def fork_state_cow(parent_state: PMap, seed: int):
    """Phase 3: Copy-on-Write 分叉
    只有被修改的Agent状态才会实际复制，
    未变更的Agent共享父分支的数据。
    """
    return parent_state.set('seed', seed).set('branch_id', new_id())
```

---

## 5. 状态变更规则

### 5.1 不可变状态（创建后不变）
- `SimulationConfig`: 模拟配置
- `Agent.persona`: Agent 人设（大五人格、消费画像等）
- `Branch.seed`: 分支随机种子

### 5.2 追加型状态（只增不删）
- `Agent.memories`: 记忆只增加，不删除不修改
- `Agent.reflections`: 反思只增加
- `Agent.action_log`: 行为日志只增加
- `Branch.events`: 事件流只增加
- `Platform.contents`: 内容只增加（不支持删帖，简化模型）
- `Platform.interactions`: 互动只增加

### 5.3 可变状态（每步可能变化）
- `Agent.internal_state`: mood, purchase_intent, brand_perception 等
- `Agent.current_platform`: Agent 可跨平台
- `Agent.current_plan`: 计划可更新
- `Agent.is_dormant`: 休眠状态可切换
- `Content.metrics`: 内容的点赞/评论数等
- `Branch.current_step`: 当前时间步递增
- `Branch.status`: 运行状态变更

### 5.4 变更触发者
| 状态 | 谁触发变更 | 触发时机 |
|------|-----------|---------|
| Agent.memories | Agent.act() | 每次行动后 |
| Agent.reflections | Agent.reflect() | 累积重要性超阈值 |
| Agent.internal_state | Agent.decide() | 每次决策后 |
| Agent.current_platform | Agent.act() | 跨平台行为时 |
| Content.metrics | Platform.execute_action() | 有Agent互动时 |
| Branch.current_step | Engine.run_step() | 每步递增 |

---

## 6. Phase 0 持久化策略

Phase 0 不使用数据库，所有状态持久化为文件:

```python
import json
from pathlib import Path

class StateManager:
    """Phase 0 极简状态管理器"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)

    def save_branch_state(self, branch_id: str, step: int, state: dict):
        """每N步保存一次状态快照(用于断点恢复)"""
        path = self.output_dir / f"branch_{branch_id}" / f"state_step_{step}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def append_event(self, branch_id: str, event: dict):
        """追加事件到JSONL文件"""
        path = self.output_dir / f"branch_{branch_id}" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')

    def save_agent_journey(self, branch_id: str, agent_id: str, journey: list):
        """保存Agent完整旅程"""
        path = self.output_dir / f"branch_{branch_id}" / "journeys" / f"{agent_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(journey, f, ensure_ascii=False, indent=2)

    def save_aggregated_results(self, results: dict):
        """保存聚合结果"""
        path = self.output_dir / "aggregated_results.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
```

---

## 7. Phase 2+ 持久化策略

| 状态类型 | 存储位置 | 理由 |
|----------|---------|------|
| Agent 当前状态 | Redis Hash | 高频读写，sub-ms延迟 |
| Agent 近期记忆 | Redis List (最近50条) | 热数据快速访问 |
| Agent 全部记忆 | Chroma/Qdrant | 向量检索 |
| 社交关系图 | Neo4j | 图查询(最短路径/社区/影响力) |
| 行为时序数据 | TimescaleDB | 时间聚合查询 |
| 事件流 | Redis Streams → TimescaleDB | 实时→归档 |
| 模拟元数据 | PostgreSQL | 结构化查询+JSONB灵活性 |
| 分支状态快照 | PostgreSQL JSONB | 断点恢复 |
| 聚合结果 | PostgreSQL JSONB | 长期保存+查询 |

---

## 8. 蒙特卡洛分支的状态隔离

### 8.1 隔离原则
- 每个分支的 Agent 状态完全独立（Branch 0 的 Agent A 和 Branch 1 的 Agent A 是不同实例）
- 每个分支的平台状态完全独立
- 分支之间不共享运行时状态
- 只有初始 persona 配置和模拟配置是跨分支共享的

### 8.2 命名空间规范
```
所有持久化的key都包含 branch_id:

Redis:   agent:{branch_id}:{agent_id}:state
Neo4j:   (:Agent {id: agent_id, branch_id: branch_id})
Chroma:  collection = "memory_{branch_id}_{agent_id}"
Timescale: WHERE branch_id = '{branch_id}'
Events:  stream key = "events:{branch_id}"
```

### 8.3 跨分支聚合查询
```sql
-- TimescaleDB: 所有分支中某产品的购买转化率分布
SELECT
    branch_id,
    COUNT(CASE WHEN metric_name = 'purchase' THEN 1 END)::float /
    NULLIF(COUNT(CASE WHEN metric_name = 'view' THEN 1 END), 0) as conversion_rate
FROM agent_metrics
WHERE simulation_id = $1
GROUP BY branch_id;
```

---

## 9. 前端状态管理（Phase 2+）

使用 Zustand，仅管理 UI 状态，服务器数据通过 TanStack Query 管理:

```typescript
// stores/simulationStore.ts
interface SimulationUIStore {
  // 查看控制
  selectedSimulationId: string | null;
  selectedBranchId: string | null;
  selectedAgentId: string | null;

  // 时间线控制
  currentViewStep: number;
  isPlaying: boolean;
  playbackSpeed: 1 | 2 | 5 | 10;

  // 可视化设置
  showNetworkGraph: boolean;
  showProbabilityChart: boolean;
  networkLayoutType: 'force' | 'circular' | 'dagre';
  highlightedAgentIds: Set<string>;

  // 对比模式
  isComparing: boolean;
  comparisonBranchIds: [string, string] | null;

  // Actions
  selectBranch: (id: string) => void;
  selectAgent: (id: string) => void;
  togglePlay: () => void;
  setStep: (step: number) => void;
}
```

---

## 10. 状态恢复与断点续跑

### Phase 0: JSON 快照恢复
```python
# 每5步保存状态快照
if step % 5 == 0:
    state_manager.save_branch_state(branch_id, step, current_state)

# 从快照恢复
def resume_branch(output_dir, branch_id):
    snapshots = sorted(glob(f"{output_dir}/branch_{branch_id}/state_step_*.json"))
    if snapshots:
        latest = json.load(open(snapshots[-1]))
        return latest['step'], restore_state(latest)
    return 0, None
```

### Phase 2+: Redis + PostgreSQL 恢复
- Redis 中保存的是最新状态（热数据）
- PostgreSQL 中定期保存完整快照（冷数据/备份）
- 恢复优先级: Redis → 最新PG快照 → 从头重跑
