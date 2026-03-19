# 镜市 MirrorMart — 后端结构文档 (Backend Structure)

> 版本 1.0 · 2026-03 · 状态: Phase 0 准备中

---

## 1. 后端架构原则

1. **Phase 0 极简**: 纯 Python + JSON 文件，不引入任何数据库或消息队列
2. **渐进式复杂度**: 每个 Phase 只添加当前阶段必需的基础设施
3. **可插拔设计**: 平台环境、LLM 提供商、存储后端均可替换
4. **异步优先**: 核心循环基于 asyncio，LLM 调用全部异步
5. **配置驱动**: Agent 画像、平台规则、场景定义全部用 YAML/JSON 配置

---

## 2. Phase 0 后端结构（极简版）

Phase 0 的目标是用最少的代码验证核心假设。不需要数据库、不需要 Web 框架、不需要 Docker。

```
mirrormart-phase0/
├── CLAUDE.md
├── progress.txt
├── lessons.md
├── pyproject.toml
├── src/
│   └── mirrormart/
│       ├── __init__.py
│       ├── config.py              # 配置加载
│       ├── engine.py              # 模拟主循环
│       ├── agent.py               # Agent类(含记忆和决策)
│       ├── platforms/
│       │   ├── __init__.py
│       │   ├── base.py            # 平台基类
│       │   ├── xiaohongshu.py     # 小红书简化环境
│       │   └── taobao.py          # 淘宝简化环境
│       ├── llm.py                 # LLM调用封装(litellm)
│       └── analysis.py            # 结果分析+输出
├── profiles/                      # Agent画像YAML
│   ├── rational_buyer.yml
│   ├── impulsive_buyer.yml
│   ├── ingredient_nerd.yml        # 成分党
│   ├── price_hunter.yml           # 价格敏感型
│   └── kol_beauty.yml             # 美妆KOL
├── scenarios/
│   └── facemask_launch.yml        # 面膜发布场景
├── outputs/                       # 模拟输出目录
└── notebooks/
    └── analyze_results.ipynb      # 结果分析笔记本
```

### 2.1 Phase 0 核心类

```python
# ===== config.py =====
from dataclasses import dataclass

@dataclass
class SimulationConfig:
    scenario_path: str           # 场景YAML路径
    num_agents: int = 20         # Agent数量
    num_branches: int = 5        # 蒙特卡洛分支数
    num_steps: int = 20          # 每分支的时间步数
    llm_model: str = "anthropic/claude-haiku"  # litellm模型标识
    output_dir: str = "outputs"


# ===== agent.py =====
class Agent:
    """Phase 0 极简Agent"""

    def __init__(self, persona: dict, agent_id: str):
        self.id = agent_id
        self.persona = persona           # YAML加载的人设
        self.memories: list[dict] = []   # 简化记忆列表
        self.action_log: list[dict] = [] # 行为日志

    async def perceive(self, environment_state: dict) -> str:
        """从环境获取可见信息，返回感知摘要"""
        ...

    async def decide(self, perception: str) -> dict:
        """基于感知+记忆+人设做决策，返回行动指令"""
        ...

    async def act(self, decision: dict, platform) -> dict:
        """在平台上执行行动，返回结果"""
        ...

    def add_memory(self, event: dict):
        """记录到记忆列表"""
        ...


# ===== engine.py =====
class SimulationEngine:
    """Phase 0 模拟引擎"""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.agents: list[Agent] = []
        self.platforms: dict = {}       # 平台环境实例

    async def run_branch(self, branch_id: int, seed: int) -> dict:
        """运行单个分支，返回结果"""
        ...

    async def run_monte_carlo(self) -> dict:
        """运行所有分支并聚合结果"""
        results = []
        for i in range(self.config.num_branches):
            result = await self.run_branch(i, seed=i * 42)
            results.append(result)
        return self.aggregate(results)

    def aggregate(self, branch_results: list[dict]) -> dict:
        """聚合多分支结果为概率分布"""
        ...
```

---

## 3. 平台环境接口规范

```python
# src/mirrormart/platforms/base.py
from abc import ABC, abstractmethod

class PlatformBase(ABC):
    """所有平台环境的抽象基类"""

    @abstractmethod
    def get_feed(self, agent_id: str, **kwargs) -> list[dict]:
        """获取该Agent可见的信息流内容
        返回: [{"content_id": str, "title": str, "author_id": str,
                "content": str, "likes": int, "comments": int, ...}]
        """
        ...

    @abstractmethod
    def execute_action(self, agent_id: str, action: dict) -> dict:
        """执行Agent的行为
        action: {"type": "like|comment|post|purchase|search|...",
                 "target_id": str, "content": str, ...}
        返回: 行为结果 + 环境变更
        """
        ...

    @abstractmethod
    def get_state_snapshot(self) -> dict:
        """获取当前平台状态快照（用于分支分叉和分析）"""
        ...

    @abstractmethod
    def restore_state(self, snapshot: dict):
        """从快照恢复平台状态（用于分支分叉）"""
        ...

    def get_metrics(self) -> dict:
        """获取平台级别的分析指标（可选覆盖）"""
        return {}
```

### 3.1 小红书环境 Phase 0 实现

```python
# src/mirrormart/platforms/xiaohongshu.py

class XiaohongshuEnvironment(PlatformBase):
    """简化的小红书环境"""

    def __init__(self):
        self.posts: list[dict] = []          # 所有笔记
        self.comments: dict[str, list] = {}  # post_id → comments
        self.likes: dict[str, set] = {}      # post_id → {agent_ids}
        self.collections: dict[str, set] = {} # post_id → {agent_ids}
        self.agent_following: dict[str, set] = {} # agent_id → {agent_ids}

    def get_feed(self, agent_id: str, limit: int = 10) -> list[dict]:
        """信息流 = 关注的人的帖子(50%) + 热度推荐(50%)
        热度 = likes * 2 + comments * 3 + collections * 5
        随机性: 每次feed有10-20%的随机内容混入
        """
        ...

    def execute_action(self, agent_id: str, action: dict) -> dict:
        """支持的action types:
        - post: 发布笔记
        - like: 点赞
        - collect: 收藏
        - comment: 评论
        - search: 搜索关键词
        - follow: 关注用户
        """
        ...
```

### 3.2 淘宝环境 Phase 0 实现

```python
# src/mirrormart/platforms/taobao.py

class TaobaoEnvironment(PlatformBase):
    """简化的淘宝环境"""

    def __init__(self):
        self.products: list[dict] = []      # 商品列表
        self.reviews: dict[str, list] = {}  # product_id → reviews
        self.purchases: dict[str, list] = {} # agent_id → [purchase_records]
        self.carts: dict[str, list] = {}    # agent_id → [product_ids]

    def get_feed(self, agent_id: str, query: str = None) -> list[dict]:
        """搜索结果 = 关键词匹配 × 销量权重 × 评分权重
        不搜索时返回: 基于浏览历史的推荐
        """
        ...

    def execute_action(self, agent_id: str, action: dict) -> dict:
        """支持的action types:
        - search: 搜索商品
        - view: 查看商品详情
        - add_cart: 加购物车
        - purchase: 购买
        - review: 写评价
        - compare: 比价(查看多个商品)
        """
        ...
```

---

## 4. Agent 画像 YAML 规范

```yaml
# profiles/ingredient_nerd.yml
id: ingredient_nerd
name: 成分党小美
description: 关注产品成分和功效，理性决策，愿意为好成分付溢价

demographics:
  age_range: [22, 30]
  gender: female
  city_tier: [1, 2]       # 一二线城市
  income_level: middle

personality:
  openness: 0.7            # 大五人格: 开放性
  conscientiousness: 0.8   # 尽责性
  extraversion: 0.4        # 外向性
  agreeableness: 0.6       # 宜人性
  neuroticism: 0.3         # 神经质

consumer_traits:
  decision_style: rational          # rational | impulsive | conformist
  price_sensitivity: 0.4            # 0=不敏感 1=极敏感
  brand_loyalty: 0.3                # 0=无忠诚 1=死忠粉
  review_dependency: 0.9            # 多大程度依赖他人评价
  content_preference: [成分分析, 测评, 对比]

platform_behavior:
  xiaohongshu:
    daily_usage_minutes: [30, 60]   # 每日使用时长范围
    content_creation_freq: 0.1      # 每日发帖概率
    interaction_style: analytical   # analytical | casual | lurker
    search_before_buy: true
    trust_kol: false                # 不盲信KOL
    trust_ingredients: true         # 信成分表

  taobao:
    search_before_buy: true
    compare_products: 3             # 平均比较商品数
    review_pages_read: [2, 5]       # 阅读评价页数
    cart_before_buy: true           # 先加购再决定
    price_compare: true

decision_triggers:
  buy_positive:
    - "成分表符合预期"
    - "多个真实用户好评"
    - "价格在预算内"
  buy_negative:
    - "成分表有争议成分"
    - "评价数太少不敢下单"
    - "同类竞品性价比更高"
  share_trigger:
    - "发现好产品且成分出色"
    - "使用后效果超预期"
```

---

## 5. 场景配置 YAML 规范

```yaml
# scenarios/facemask_launch.yml
id: facemask_launch
name: 氨基酸面膜小红书推广
description: 模拟一款新面膜在小红书种草→淘宝转化的完整链路

# 产品信息
product:
  name: "润颜氨基酸面膜"
  price: 59
  category: 面膜
  key_ingredients: ["氨基酸", "玻尿酸", "烟酰胺"]
  selling_points: ["温和不刺激", "成分干净", "敏感肌可用"]
  brand_awareness: low    # low | medium | high

# 平台配置
platforms:
  - type: xiaohongshu
    initial_content:
      - type: brand_post     # 品牌官方种草帖
        content: "敏感肌救星！氨基酸温和面膜..."
        initial_likes: 5
  - type: taobao
    initial_products:
      - id: product_main
        price: 59
        initial_reviews: 12
        initial_rating: 4.6
        initial_sales: 230
      - id: competitor_a
        name: "某大牌氨基酸面膜"
        price: 89
        initial_reviews: 5600
        initial_rating: 4.8
        initial_sales: 120000

# Agent配置
agents:
  profiles:
    - type: ingredient_nerd
      count: 5
    - type: impulsive_buyer
      count: 4
    - type: price_hunter
      count: 4
    - type: rational_buyer
      count: 4
    - type: kol_beauty
      count: 2
    - type: lurker             # 潜水用户
      count: 1

  # 社交关系初始化
  relationships:
    - type: random_follow       # 随机关注关系
      density: 0.15             # 15%的Agent对互相关注

# 模拟参数
simulation:
  num_steps: 20                 # 模拟20个时间步(约10天)
  step_duration_hours: 12       # 每步12小时
  num_branches: 5               # 5次蒙特卡洛
```

---

## 6. LLM 调用规范

### 6.1 Prompt 结构

所有 Agent 的 LLM 调用遵循统一结构:

```
[系统提示词] (所有Agent共享，利于缓存)
├── 世界观: 你是一个模拟环境中的虚拟消费者...
├── 平台规则: 当前你在模拟小红书环境中...
├── 时间上下文: 当前是模拟第X天，下午...
└── 输出格式要求: 你必须以JSON格式回复...

[用户消息] (每Agent每步不同)
├── 你的人设: {persona摘要}
├── 你的近期记忆: {检索到的相关记忆}
├── 你当前看到的: {感知摘要}
├── 你的当前计划: {今日计划}
└── 请决定你的下一步行动
```

### 6.2 输出格式

```json
{
  "thinking": "我看到这条笔记提到了氨基酸成分，但评论区没人讨论具体配方...",
  "action": {
    "type": "comment",
    "platform": "xiaohongshu",
    "target_id": "post_001",
    "content": "成分表有吗？想看看具体用了哪种氨基酸"
  },
  "internal_state": {
    "interest_level": 0.6,
    "purchase_intent": 0.2,
    "information_need": "成分详情"
  }
}
```

### 6.3 错误处理
- LLM 返回非法 JSON → 重试一次，仍失败则使用默认行为（根据人设的fallback规则）
- LLM API 超时 → Agent 本时间步跳过，标记为"走神了"
- LLM API 限流 → 指数退避重试，最多3次

---

## 7. 日志与输出规范

### 7.1 运行日志
```
[Branch 0][Step 3][Agent: ingredient_nerd_01] PERCEIVE: 在小红书信息流中看到3条笔记
[Branch 0][Step 3][Agent: ingredient_nerd_01] DECIDE: 决定评论post_001，询问成分
[Branch 0][Step 3][Agent: ingredient_nerd_01] ACT: 在post_001下评论 "成分表有吗？"
[Branch 0][Step 3][Agent: impulsive_buyer_01] PERCEIVE: 在小红书看到post_001有新评论
[Branch 0][Step 3][Agent: impulsive_buyer_01] DECIDE: 被种草，去淘宝搜索
[Branch 0][Step 3][Agent: impulsive_buyer_01] ACT: 在淘宝搜索"氨基酸面膜"
```

### 7.2 结果输出文件
```
outputs/
├── run_20260309_143022/
│   ├── config.json              # 本次运行配置
│   ├── branch_0/
│   │   ├── events.jsonl         # 完整事件流 (每行一个事件)
│   │   ├── agent_states.json    # 最终Agent状态
│   │   ├── platform_states.json # 最终平台状态
│   │   └── summary.json         # 分支摘要
│   ├── branch_1/
│   │   └── ...
│   ├── aggregated_results.json  # 聚合概率分布
│   └── analysis.md              # 自动生成的分析报告
```
