# 镜市 MirrorMart — 前端指南 (Frontend Guidelines)

> 版本 1.0 · 2026-03 · 状态: Phase 2 开始时启用，Phase 0-1 无前端

---

## 0. 重要说明

**Phase 0 和 Phase 1 不需要前端。** 输出通过终端日志 + JSON 文件 + Jupyter Notebook 完成。本文档为 Phase 2 开始构建 Web UI 时的规范，提前写好以确保架构预留正确。

---

## 1. 技术选型

| 类别 | 技术 | 理由 |
|------|------|------|
| 框架 | React 18 + TypeScript | 生态成熟，AI工具支持最好 |
| 构建 | Vite | 快速，支持HMR |
| 包管理 | pnpm | 快速，磁盘高效 |
| 样式 | Tailwind CSS + shadcn/ui | 原子化CSS + 高质量组件库 |
| 图表 | ECharts (apache-echarts) | 中文生态最好，WebGL渲染 |
| 网络图 | @antv/g6 | 蚂蚁出品，GPU加速，中文文档 |
| 状态管理 | Zustand | 轻量，TypeScript友好 |
| 数据请求 | TanStack Query (React Query) | 缓存+实时+分页 |
| 路由 | React Router v6 | 标准选择 |
| WebSocket | 原生WebSocket + reconnecting | 实时模拟事件推送 |
| 国际化 | i18next | 中英双语支持 |

---

## 2. 页面结构

```
/                          # 首页/仪表板：最近模拟列表 + 快速开始
/simulations/new           # 创建新模拟（设定页）
/simulations/:id           # 模拟详情（模拟中 = 实时视图，完成 = 结果视图）
/simulations/:id/observe   # 观察页（概率分布 + 群体动态 + 个体旅程）
/simulations/:id/compare   # 干预对比页（A/B条件对比）
/agents/:id                # Agent详情页（画像 + 跨分支行为对比）
/scenarios                 # 场景模板库
/settings                  # 配置页（LLM设置/API密钥/默认参数）
```

---

## 3. 核心可视化组件

### 3.1 概率分布图 (ECharts)
- 类型: 直方图 + KDE曲线叠加
- 数据: 多分支结果的聚合分布
- 交互: hover显示具体分支，点击跳转该分支详情
- 颜色编码: 绿色(积极)→黄色(中性)→红色(消极)

### 3.2 传播网络图 (G6)
- 节点: Agent（大小=影响力，颜色=态度）
- 边: 信息传播路径（粗细=影响强度）
- 时间轴: 可拖动，回放传播过程
- 布局: Force-directed，支持社区聚类

### 3.3 Agent旅程时间线
- 类型: 垂直时间线 + 多泳道（每个平台一个泳道）
- 节点: 每个行为事件（类型图标 + 简述）
- 展开: 点击事件查看LLM推理过程和记忆检索结果
- 对比模式: 同一Agent在不同分支的旅程并排显示

### 3.4 模拟实时仪表板
- 实时指标卡片: 当前时间步 / 活跃Agent数 / 总互动数
- 事件流: 实时滚动的Agent行为日志
- 迷你网络图: 实时更新的简化传播图
- 分支进度: 各分支的执行进度条

---

## 4. 设计规范

### 4.1 配色方案
```css
/* 主色 */
--primary: #1A3A5C;         /* 深海军蓝，品牌主色 */
--primary-light: #2E75B6;   /* 蓝色强调 */
--accent: #4ECDC4;          /* 青绿色，交互强调 */

/* 语义色 */
--positive: #2D7D46;        /* 积极结果 */
--neutral: #D4A017;         /* 中性结果 */
--negative: #C44E52;        /* 消极结果 */

/* 背景 */
--bg-primary: #0F172A;      /* 深色主背景（默认暗色主题）*/
--bg-secondary: #1E293B;    /* 卡片/面板背景 */
--bg-tertiary: #334155;     /* 悬浮/选中状态 */

/* 文本 */
--text-primary: #F1F5F9;
--text-secondary: #94A3B8;
--text-muted: #64748B;
```

### 4.2 暗色主题优先
- 默认暗色主题（数据密集型仪表板更适合）
- 提供亮色主题切换
- 所有可视化组件需同时适配两种主题

### 4.3 字体
- 英文/代码: Inter / JetBrains Mono
- 中文: 系统默认 (PingFang SC / Microsoft YaHei / Noto Sans CJK)
- 数据标签: Tabular figures (等宽数字)

### 4.4 响应式
- 桌面优先（1280px+），主要使用场景
- 平板适配（768px+），可查看结果
- 手机不做适配（模拟控制和数据分析不适合小屏）

---

## 5. 组件命名规范

```
components/
├── ui/                      # 基础UI组件 (shadcn/ui)
├── simulation/              # 模拟相关
│   ├── SimulationSetup.tsx      # 设定表单
│   ├── SimulationRunner.tsx     # 运行控制
│   ├── SimulationTimeline.tsx   # 时间线控制
│   └── InterventionPanel.tsx    # 干预面板
├── visualization/           # 可视化组件
│   ├── ProbabilityChart.tsx     # 概率分布图
│   ├── SpreadNetwork.tsx        # 传播网络图
│   ├── AgentJourney.tsx         # Agent旅程时间线
│   ├── MetricsCards.tsx         # 实时指标卡片
│   └── EventStream.tsx          # 事件流
├── agent/                   # Agent相关
│   ├── AgentCard.tsx            # Agent卡片
│   ├── AgentProfile.tsx         # Agent画像详情
│   └── AgentComparison.tsx      # 跨分支对比
└── layout/                  # 布局
    ├── Header.tsx
    ├── Sidebar.tsx
    └── DashboardLayout.tsx
```

---

## 6. 数据流规范

### 6.1 API 请求 (TanStack Query)
```typescript
// 所有API请求通过 TanStack Query 管理
// key命名规范: ['资源类型', id, 参数]
const { data } = useQuery({
  queryKey: ['simulation', simulationId, 'results'],
  queryFn: () => api.getSimulationResults(simulationId),
  refetchInterval: isRunning ? 3000 : false, // 运行中3秒轮询
});
```

### 6.2 WebSocket (实时事件)
```typescript
// 模拟运行中通过WebSocket接收实时事件
// 事件类型:
type SimEvent =
  | { type: 'agent_action'; data: AgentAction }
  | { type: 'branch_complete'; data: BranchResult }
  | { type: 'simulation_complete'; data: SimulationResult }
  | { type: 'metric_update'; data: MetricUpdate }
```

### 6.3 全局状态 (Zustand)
```typescript
// 仅存储全局UI状态，不存储服务器数据
interface AppStore {
  // 主题
  theme: 'dark' | 'light';
  // 当前选中
  selectedBranchId: string | null;
  selectedAgentId: string | null;
  // 时间线控制
  currentTimeStep: number;
  isPlaying: boolean;
  playbackSpeed: number;
  // 配置
  llmConfig: LLMConfig;
}
```

---

## 7. 性能要求

- 首屏加载: < 2s (代码分割，路由级懒加载)
- 概率分布图渲染: < 500ms (100个分支的数据)
- 网络图渲染: < 1s (1000节点)
- WebSocket延迟: < 100ms (本地部署)
- 内存占用: < 500MB (浏览器标签页)
