# CLAUDE.md — 镜市 MirrorMart 项目规则

> Claude Code 和 Codex 在每次会话开始时必须阅读此文件。

---

## 项目简介
镜市 (MirrorMart) 是一个开源的中国社会模拟引擎。用 LLM 驱动的虚拟个体在模拟的中国互联网平台（小红书、淘宝、抖音、微博）中互动，通过蒙特卡洛多路径推演输出概率分布结果。

## 当前阶段: Phase 0 — 核心假设验证 (3天)
**目标**: 验证两件事:
1. 简化的平台环境规则是否足以驱动有意义的消费者互动链路？
2. 5次模拟的结果是否有足够差异，使得概率分布分析有意义？

**Phase 0 范围**:
- 20个Agent，5个分支，20个时间步
- 仅小红书 + 淘宝两个平台（极简规则）
- 场景: 氨基酸面膜在小红书种草→淘宝转化
- 无数据库、无前端、无Docker
- 输出: JSON文件 + 终端日志

---

## 技术栈
- Python 3.11+, asyncio
- LLM调用: litellm (统一网关)
- 包管理: uv
- 数据: Python dict + JSON文件 (Phase 0)
- 测试: pytest
- 代码质量: ruff + mypy

## 编码规范

### Python
- 类型注解: 所有函数参数和返回值必须有类型注解
- docstring: 所有公开类和函数用中文写docstring
- 异步: LLM调用必须用async/await
- 命名: snake_case (函数/变量), PascalCase (类), UPPER_CASE (常量)
- 导入: stdlib → 第三方 → 本地, 每组之间空一行

### 代码组织
- 每个文件不超过 300 行，超过则拆分
- 避免循环导入: 使用接口/协议类解耦
- 配置与代码分离: 所有可配置项放 YAML/config.py

### LLM Prompt
- 系统提示词和用户消息严格分离
- 所有prompt模板集中在 src/mirrormart/llm/prompts/ 目录
- prompt中要求JSON输出时，提供完整的schema示例
- 所有prompt用中文（Agent是中国消费者）

### 文件路径约定
- Agent画像: profiles/*.yml
- 场景配置: scenarios/*.yml
- 输出结果: outputs/{run_id}/
- 文档: docs/

---

## 关键架构决策

1. **平台环境是简化规则，不是真实算法复现**
   - 小红书信息流 = 关注内容(50%) + 热度推荐(50%) + 随机(10-20%)
   - 淘宝搜索 = 关键词匹配 × 销量权重 × 评分权重
   - 不试图复现任何平台的真实推荐算法

2. **Agent认知循环: perceive → decide → act → [reflect]**
   - perceive: 从平台获取可见信息
   - decide: LLM推理 (人设 + 记忆 + 感知 → 行动)
   - act: 在平台执行行为
   - reflect: 条件触发的高层认知综合 (Phase 1+)

3. **蒙特卡洛分支完全独立**
   - 每个分支深拷贝所有状态
   - 不同分支通过不同随机种子产生差异
   - 结果聚合在所有分支完成后进行

4. **模拟的价值在于相对比较，不是绝对预测**
   - 永远不输出"你的产品会获得X万曝光"
   - 只输出"方案A比方案B的转化率高X%"和概率分布

---

## 常见陷阱 (从lessons.md积累)

- [ ] LLM返回格式: 一定要做JSON解析的try-catch，LLM经常返回非法JSON
- [ ] Agent行为单调: 如果所有Agent行为趋同，检查prompt中人设差异是否足够突出
- [ ] 记忆爆炸: Phase 0 限制每Agent记忆不超过100条，超过则只保留最重要的
- [ ] 模拟时间: 20个Agent × 20步 × 5分支 = 2000次LLM调用，预估耗时和成本

---

## 每次会话开始时
1. 读取此文件 (CLAUDE.md)
2. 读取 progress.txt 了解当前进度
3. 读取 lessons.md 了解已知问题
4. 确认当前要做的任务
5. 开始工作，每完成一个功能就更新 progress.txt
