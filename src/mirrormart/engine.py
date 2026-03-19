"""模拟引擎主循环 — Phase 1 实现。

支持单分支运行和蒙特卡洛多分支并发。
Phase 1 新增: reflect 机制、Chroma 记忆、Redis 缓存、WebSocket 事件流。
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import yaml

from mirrormart.agent import Agent
from mirrormart.cache.redis_cache import RedisCache
from mirrormart.config import SimulationConfig
from mirrormart.memory.chroma_store import ChromaMemoryStore
from mirrormart.platforms.douyin import DouyinEnvironment
from mirrormart.platforms.taobao import TaobaoEnvironment
from mirrormart.platforms.weibo import WeiboEnvironment
from mirrormart.platforms.xiaohongshu import XiaohongshuEnvironment
from mirrormart.reflect import ReflectEngine

logger = logging.getLogger(__name__)


class SimulationEngine:
    """Phase 1 模拟引擎。"""

    def __init__(
        self,
        config: SimulationConfig,
        event_callback: Any | None = None,
    ) -> None:
        """初始化模拟引擎。

        Args:
            config: 模拟配置
            event_callback: 可选的事件回调协程，签名 async (event: dict) -> None，
                            用于 WebSocket 实时推送
        """
        self.config = config
        self.scenario: dict[str, Any] = {}
        self._event_callback = event_callback
        self._reflect_engine = ReflectEngine(
            llm_model=config.llm_model,
            api_base=config.api_base,
            api_key=config.api_key,
            max_tokens=min(config.max_tokens, 512),
        )
        self._redis: RedisCache = RedisCache()
        # 并发限速：限制同时调用 LLM 的 Agent 数量
        self._semaphore = asyncio.Semaphore(config.concurrency or 5)
        self._load_scenario()

    def _load_scenario(self) -> None:
        """加载场景配置。"""
        path = Path(self.config.scenario_path)
        if not path.exists():
            raise FileNotFoundError(f"场景文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            self.scenario = yaml.safe_load(f)
        logger.info("已加载场景: %s", self.scenario.get("name", path.name))

    def _load_profiles(self) -> dict[str, dict[str, Any]]:
        """加载所有 Agent 画像模板。"""
        profiles: dict[str, dict] = {}
        profiles_dir = Path("profiles")
        if not profiles_dir.exists():
            logger.warning("profiles/ 目录不存在，使用内置默认画像")
            return {}
        for yml_file in profiles_dir.glob("*.yml"):
            with open(yml_file, encoding="utf-8") as f:
                p = yaml.safe_load(f)
                profiles[p["id"]] = p
        logger.info("已加载 %d 个 Agent 画像模板", len(profiles))
        return profiles

    def _build_agents(
        self,
        profiles: dict[str, dict[str, Any]],
        rng: random.Random,
    ) -> list[Agent]:
        """根据场景配置构建 Agent 列表。"""
        agents: list[Agent] = []
        agent_configs: list[dict] = self.scenario.get("agents", {}).get("profiles", [])

        for agent_cfg in agent_configs:
            profile_type = agent_cfg["type"]
            count = agent_cfg.get("count", 1)
            profile = profiles.get(profile_type)
            if not profile:
                logger.warning("未找到画像类型 '%s'，跳过", profile_type)
                continue
            for i in range(count):
                agent_id = f"{profile_type}_{i+1:02d}"
                agent_rng = random.Random(rng.randint(0, 2**32))
                agent = Agent(
                    persona=profile,
                    agent_id=agent_id,
                    llm_model=self.config.llm_model,
                    rng=agent_rng,
                    max_memory=self.config.max_memory_per_agent,
                )
                agent.api_base = self.config.api_base
                agent.api_key = self.config.api_key
                agent.max_tokens = self.config.max_tokens
                agents.append(agent)

        logger.info("构建了 %d 个 Agent", len(agents))
        return agents

    def _build_platforms(self, rng: random.Random) -> dict[str, Any]:
        """根据场景配置构建平台环境。"""
        xhs = XiaohongshuEnvironment(rng=random.Random(rng.randint(0, 2**32)))
        taobao = TaobaoEnvironment(rng=random.Random(rng.randint(0, 2**32)))
        douyin = DouyinEnvironment(rng=random.Random(rng.randint(0, 2**32)))
        weibo = WeiboEnvironment(rng=random.Random(rng.randint(0, 2**32)))

        product_info = self.scenario.get("product", {})

        for platform_cfg in self.scenario.get("platforms", []):
            ptype = platform_cfg["type"]
            if ptype == "xiaohongshu":
                for post_cfg in platform_cfg.get("initial_content", []):
                    xhs.add_initial_post(
                        content=post_cfg.get("content", ""),
                        author_id="brand_official",
                        title=post_cfg.get("title", ""),
                        tags=post_cfg.get("tags", []),
                        initial_likes=post_cfg.get("initial_likes", 0),
                        initial_comments=post_cfg.get("initial_comments", 0),
                    )
            elif ptype == "taobao":
                for prod_cfg in platform_cfg.get("initial_products", []):
                    taobao.add_product(
                        product_id=prod_cfg["id"],
                        name=prod_cfg.get("name", product_info.get("name", "未知商品")),
                        price=prod_cfg.get("price", product_info.get("price", 0)),
                        category=product_info.get("category", ""),
                        description=" ".join(product_info.get("selling_points", [])),
                        key_ingredients=product_info.get("key_ingredients", []),
                        selling_points=product_info.get("selling_points", []),
                        initial_sales=prod_cfg.get("initial_sales", 0),
                        initial_rating=prod_cfg.get("initial_rating", 4.5),
                        initial_reviews=prod_cfg.get("initial_reviews", 0),
                    )
            elif ptype == "douyin":
                for vid_cfg in platform_cfg.get("initial_content", []):
                    douyin.add_video(
                        content=vid_cfg.get("content", ""),
                        author_id=vid_cfg.get("author_id", "brand_official"),
                        title=vid_cfg.get("title", ""),
                        tags=vid_cfg.get("tags", []),
                        duration=vid_cfg.get("duration", 30),
                        initial_views=vid_cfg.get("initial_views", 0),
                        initial_likes=vid_cfg.get("initial_likes", 0),
                        initial_comments=vid_cfg.get("initial_comments", 0),
                        completion_rate=vid_cfg.get("completion_rate", 0.6),
                    )
            elif ptype == "weibo":
                for post_cfg in platform_cfg.get("initial_content", []):
                    weibo.add_post(
                        content=post_cfg.get("content", ""),
                        author_id=post_cfg.get("author_id", "brand_official"),
                        topics=post_cfg.get("topics", []),
                        initial_likes=post_cfg.get("initial_likes", 0),
                        initial_reposts=post_cfg.get("initial_reposts", 0),
                        initial_comments=post_cfg.get("initial_comments", 0),
                    )

        return {
            "xiaohongshu": xhs,
            "taobao": taobao,
            "douyin": douyin,
            "weibo": weibo,
        }

    async def run_branch(
        self,
        branch_id: int,
        seed: int,
        profiles: dict[str, dict[str, Any]],
        output_dir: Path,
    ) -> dict[str, Any]:
        """运行单个蒙特卡洛分支。

        Args:
            branch_id: 分支编号
            seed: 随机种子
            profiles: Agent 画像模板
            output_dir: 输出目录

        Returns:
            分支结果字典
        """
        branch_tag = f"[Branch {branch_id}]"
        logger.info("%s 开始运行（seed=%d）", branch_tag, seed)

        rng = random.Random(seed)
        agents = self._build_agents(profiles, rng)
        platforms = self._build_platforms(rng)
        xhs: XiaohongshuEnvironment = platforms["xiaohongshu"]
        taobao: TaobaoEnvironment = platforms["taobao"]
        douyin: DouyinEnvironment = platforms["douyin"]
        weibo: WeiboEnvironment = platforms["weibo"]

        # 为每个 Agent 创建 Chroma 记忆存储（分支隔离）
        chroma_dir = f".chroma_data/branch_{branch_id}"
        chroma_stores: dict[str, ChromaMemoryStore] = {}
        if ChromaMemoryStore.is_available():
            for agent in agents:
                store = ChromaMemoryStore(
                    persist_dir=chroma_dir,
                    branch_id=branch_id,
                    agent_id=agent.id,
                )
                if store.available:
                    chroma_stores[agent.id] = store

        # 初始化关注关系
        agent_ids = [a.id for a in agents]
        follow_density = (
            self.scenario.get("agents", {})
            .get("relationships", [{}])[0]
            .get("density", 0.15)
        )
        xhs.init_following(agent_ids, density=follow_density)
        douyin.init_following(agent_ids, density=follow_density * 0.7)
        weibo.init_following(agent_ids, density=follow_density * 1.3)

        events: list[dict[str, Any]] = []
        num_steps = self.config.num_steps

        run_id = output_dir.parent.name

        for step in range(num_steps):
            # 更新平台时间步（用于热度时间衰减）
            xhs.current_step = step
            douyin.current_step = step
            weibo.current_step = step

            # 打乱 Agent 顺序（模拟并发）
            rng.shuffle(agents)
            step_tasks = [
                self._run_agent_step_throttled(
                    agent, platforms, step, branch_tag, events,
                    chroma_store=chroma_stores.get(agent.id),
                    run_id=run_id,
                    branch_id=branch_id,
                )
                for agent in agents
            ]
            await asyncio.gather(*step_tasks)

            if (step + 1) % 5 == 0:
                xhs_metrics = xhs.get_metrics()
                taobao_metrics = taobao.get_metrics()
                douyin_metrics = douyin.get_metrics()
                weibo_metrics = weibo.get_metrics()
                logger.info(
                    "%s Step %d 完成 | XHS: 帖子%d 点赞%d | 抖音: 视频%d 播放%d | 微博: 帖子%d 转发%d | 淘宝: 购买%d",
                    branch_tag, step + 1,
                    xhs_metrics["total_posts"], xhs_metrics["total_likes"],
                    douyin_metrics["total_videos"], douyin_metrics["total_views"],
                    weibo_metrics["total_posts"], weibo_metrics["total_reposts"],
                    taobao_metrics["total_purchases"],
                )
                if self._event_callback:
                    await self._event_callback({
                        "type": "step_complete",
                        "run_id": run_id,
                        "branch_id": branch_id,
                        "step": step + 1,
                        "metrics": {
                            "xhs": xhs_metrics,
                            "taobao": taobao_metrics,
                            "douyin": douyin_metrics,
                            "weibo": weibo_metrics,
                        },
                    })

        # 汇总分支结果
        result = self._summarize_branch(branch_id, agents, platforms, events)

        # 写入文件
        branch_dir = output_dir / f"branch_{branch_id}"
        branch_dir.mkdir(parents=True, exist_ok=True)
        self._write_jsonl(branch_dir / "events.jsonl", events)
        self._write_json(branch_dir / "summary.json", result)
        agent_states = {a.id: a.to_state_dict() for a in agents}
        self._write_json(branch_dir / "agent_states.json", agent_states)

        logger.info("%s 运行完成，购买次数: %d", branch_tag, result["taobao_purchases"])
        return result

    async def _run_agent_step_throttled(
        self,
        agent: Agent,
        platforms: dict[str, Any],
        step: int,
        branch_tag: str,
        events: list[dict[str, Any]],
        chroma_store: ChromaMemoryStore | None = None,
        run_id: str = "",
        branch_id: int = 0,
    ) -> None:
        """带 Semaphore 限速的 Agent 单步循环。"""
        async with self._semaphore:
            await self._run_agent_step(
                agent, platforms, step, branch_tag, events,
                chroma_store=chroma_store, run_id=run_id, branch_id=branch_id,
            )

    def _pick_platform(
        self, agent: Agent, step: int, platforms: dict[str, Any],
    ) -> tuple[Any, str, str, str | None]:
        """选择本步使用的平台，返回 (platform, name, context, query)。"""
        purchase_intent = agent.internal_state.get("purchase_intent", 0)

        # 基础概率：小红书35%、抖音25%、微博15%、淘宝25%
        weights = {"xiaohongshu": 0.35, "douyin": 0.25, "weibo": 0.15, "taobao": 0.25}

        # 前半段偏向种草平台，后半段偏向转化
        if step < 10:
            weights["xiaohongshu"] += 0.1
            weights["douyin"] += 0.05
            weights["taobao"] -= 0.15
        else:
            weights["taobao"] += 0.15
            weights["xiaohongshu"] -= 0.1
            weights["douyin"] -= 0.05

        # 购买意向高时更倾向淘宝
        if purchase_intent > 0.6:
            weights["taobao"] += 0.2
            weights["xiaohongshu"] -= 0.1
            weights["douyin"] -= 0.05
            weights["weibo"] -= 0.05

        # 归一化
        total = sum(weights.values())
        probs = {k: v / total for k, v in weights.items()}

        # 加权随机选择
        r = agent.rng.random()
        cumulative = 0.0
        chosen = "xiaohongshu"
        for name, prob in probs.items():
            cumulative += prob
            if r < cumulative:
                chosen = name
                break

        contexts = {
            "xiaohongshu": (
                "你正在小红书浏览。小红书是种草社区，人们在这里分享使用体验、"
                "找产品推荐。你可以看笔记、评论、收藏、转发或搜索。"
            ),
            "taobao": (
                "你正在淘宝购物。淘宝是购物平台，你可以搜索商品、查看详情、"
                "比价、加购物车、收藏或直接购买。"
            ),
            "douyin": (
                "你正在刷抖音。抖音是短视频平台，你可以观看视频、点赞、评论、"
                "分享或搜索感兴趣的内容。"
            ),
            "weibo": (
                "你正在刷微博。微博是社交媒体平台，你可以看热搜、转发、评论、"
                "搜索话题或发表自己的观点。"
            ),
        }

        query = None
        search_keywords = ["面膜", "氨基酸面膜", "敏感肌面膜", "温和护肤"]
        if chosen in ("xiaohongshu", "douyin", "weibo"):
            if agent.rng.random() < 0.3:
                query = agent.rng.choice(search_keywords)
        elif chosen == "taobao" and purchase_intent > 0.4:
            query = agent.rng.choice(["氨基酸面膜", "面膜", "温和面膜"])

        return platforms[chosen], chosen, contexts[chosen], query

    async def _run_agent_step(
        self,
        agent: Agent,
        platforms: dict[str, Any],
        step: int,
        branch_tag: str,
        events: list[dict[str, Any]],
        chroma_store: ChromaMemoryStore | None = None,
        run_id: str = "",
        branch_id: int = 0,
    ) -> None:
        """运行单个 Agent 的单步循环（含 reflect 机制和 Chroma 记忆）。"""
        try:
            platform, platform_name, platform_context, query = self._pick_platform(
                agent, step, platforms,
            )

            # 感知（先查 Redis 缓存）
            cached = await self._redis.get_perception(agent.id, platform_name, step)
            if cached:
                perception = cached
            else:
                perception = await agent.perceive(platform, platform_name, step, query)
                await self._redis.set_perception(agent.id, platform_name, step, perception)

            # 如果 Chroma 可用，用语义检索补充记忆上下文
            if chroma_store and chroma_store.available:
                relevant = chroma_store.retrieve(perception, n_results=5)
                if relevant:
                    extra = "\n".join(f"- [{m['step']}步] {m['summary']}" for m in relevant)
                    perception = perception + f"\n\n【相关历史记忆（语义检索）】\n{extra}"

            # 决策
            decision = await agent.decide(perception, platform_name, step, platform_context)

            # 行动
            result = await agent.act(decision, platform, step)

            # 将新记忆写入 Chroma
            if chroma_store and chroma_store.available and agent.memories:
                last_mem = agent.memories[-1]
                mem_id = f"{agent.id}_{step}_{len(agent.memories)}"
                chroma_store.add(last_mem, mem_id)

            # 条件触发反思
            action_type = decision.get("action", {}).get("type", "?")
            if self._reflect_engine.should_reflect(agent, step, action_type):
                await self._reflect_engine.reflect(agent, step)

            # 记录事件
            event = {
                "branch_step": step,
                "agent_id": agent.id,
                "platform": platform_name,
                "action": decision.get("action", {}),
                "result": result,
                "thinking": decision.get("thinking", ""),
                "internal_state": dict(agent.internal_state),
            }
            events.append(event)

            logger.debug(
                "%s Step %d [%s] %s → %s",
                branch_tag, step, agent.id, action_type, result.get("effect", "")
            )

            # WebSocket 事件推送
            if self._event_callback and run_id:
                await self._event_callback({
                    "type": "agent_action",
                    "run_id": run_id,
                    "branch_id": branch_id,
                    "step": step,
                    "agent_id": agent.id,
                    "action_type": action_type,
                    "platform": platform_name,
                    "thinking": decision.get("thinking", "")[:100],
                    "effect": result.get("effect", ""),
                    "purchase_intent": round(agent.internal_state.get("purchase_intent", 0), 2),
                })

        except Exception as e:
            logger.error("%s Step %d [%s] 出错: %s", branch_tag, step, agent.id, e)

    def _summarize_branch(
        self,
        branch_id: int,
        agents: list[Agent],
        platforms: dict[str, Any],
        events: list[dict],
    ) -> dict[str, Any]:
        """汇总单分支结果。"""
        xhs_metrics = platforms["xiaohongshu"].get_metrics()
        taobao_metrics = platforms["taobao"].get_metrics()
        douyin_metrics = platforms["douyin"].get_metrics()
        weibo_metrics = platforms["weibo"].get_metrics()
        purchases = taobao_metrics["total_purchases"]
        num_agents = len(agents)

        # 主产品购买数
        main_product_purchases = taobao_metrics["conversion_by_product"].get("product_main", 0)

        # 最终购买意向分布
        high_intent = sum(
            1 for a in agents if a.internal_state.get("purchase_intent", 0) > 0.6
        )

        # 判定结局类型
        conversion_rate = main_product_purchases / max(num_agents, 1)
        if conversion_rate >= 0.3:
            outcome = "爆款"
        elif conversion_rate >= 0.1:
            outcome = "一般"
        else:
            outcome = "平淡"

        return {
            "branch_id": branch_id,
            "outcome": outcome,
            "conversion_rate": round(conversion_rate, 3),
            "main_product_purchases": main_product_purchases,
            "taobao_purchases": purchases,
            "taobao_revenue": taobao_metrics["total_revenue"],
            "taobao_wishlist": taobao_metrics.get("total_wishlist", 0),
            "taobao_questions": taobao_metrics.get("total_questions", 0),
            "xhs_posts": xhs_metrics["total_posts"],
            "xhs_likes": xhs_metrics["total_likes"],
            "xhs_comments": xhs_metrics["total_comments"],
            "xhs_reposts": xhs_metrics.get("total_reposts", 0),
            "douyin_videos": douyin_metrics["total_videos"],
            "douyin_views": douyin_metrics["total_views"],
            "douyin_likes": douyin_metrics["total_likes"],
            "douyin_shares": douyin_metrics["total_shares"],
            "weibo_posts": weibo_metrics["total_posts"],
            "weibo_reposts": weibo_metrics["total_reposts"],
            "weibo_comments": weibo_metrics["total_comments"],
            "high_intent_agents": high_intent,
            "total_events": len(events),
        }

    async def run_monte_carlo(self) -> dict[str, Any]:
        """运行所有蒙特卡洛分支并聚合结果。"""
        # 创建输出目录
        run_id = time.strftime("run_%Y%m%d_%H%M%S")
        output_dir = Path(self.config.output_dir) / run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # 尝试连接 Redis（失败则静默降级）
        await self._redis.ping()

        # 保存本次运行配置
        self._write_json(output_dir / "config.json", {
            "scenario": self.scenario.get("name", ""),
            "num_branches": self.config.num_branches,
            "num_steps": self.config.num_steps,
            "llm_model": self.config.llm_model,
            "redis_available": self._redis.available,
            "chroma_available": ChromaMemoryStore.is_available(),
        })

        profiles = self._load_profiles()
        num_branches = self.config.num_branches

        logger.info(
            "开始蒙特卡洛模拟: %d 个分支，场景=%s",
            num_branches, self.scenario.get("name", "")
        )

        results: list[dict[str, Any]] = []
        for i in range(num_branches):
            result = await self.run_branch(
                branch_id=i,
                seed=i * 42 + 1,
                profiles=profiles,
                output_dir=output_dir,
            )
            results.append(result)

        aggregated = self._aggregate(results)
        aggregated["run_id"] = run_id
        self._write_json(output_dir / "aggregated_results.json", aggregated)

        # 生成简单分析报告
        report = self._generate_report(aggregated, results)
        (output_dir / "analysis.md").write_text(report, encoding="utf-8")

        logger.info("模拟完成！结果保存到: %s", output_dir)
        return aggregated

    def _aggregate(self, branch_results: list[dict[str, Any]]) -> dict[str, Any]:
        """聚合多分支结果为概率分布。"""
        if not branch_results:
            return {}

        # 结局分布
        outcomes: dict[str, int] = {}
        for r in branch_results:
            o = r.get("outcome", "未知")
            outcomes[o] = outcomes.get(o, 0) + 1
        n = len(branch_results)
        outcome_distribution = {k: round(v / n, 2) for k, v in outcomes.items()}

        def avg(key: str) -> float:
            vals = [r.get(key, 0) for r in branch_results]
            return round(sum(vals) / len(vals), 2) if vals else 0.0

        def std(key: str) -> float:
            vals = [r.get(key, 0) for r in branch_results]
            mean = sum(vals) / len(vals) if vals else 0
            variance = sum((v - mean) ** 2 for v in vals) / len(vals) if vals else 0
            return round(variance ** 0.5, 3)

        return {
            "num_branches": n,
            "outcome_distribution": outcome_distribution,
            "metrics": {
                "conversion_rate": {
                    "mean": avg("conversion_rate"),
                    "std": std("conversion_rate"),
                    "values": [r.get("conversion_rate", 0) for r in branch_results],
                },
                "main_product_purchases": {
                    "mean": avg("main_product_purchases"),
                    "std": std("main_product_purchases"),
                    "values": [r.get("main_product_purchases", 0) for r in branch_results],
                },
                "xhs_posts": {
                    "mean": avg("xhs_posts"),
                    "std": std("xhs_posts"),
                },
                "xhs_likes": {
                    "mean": avg("xhs_likes"),
                    "std": std("xhs_likes"),
                },
            },
        }

    def _generate_report(
        self,
        aggregated: dict[str, Any],
        branch_results: list[dict[str, Any]],
    ) -> str:
        """生成 Markdown 分析报告。"""
        lines = [
            f"# 模拟分析报告",
            f"",
            f"**运行ID**: {aggregated.get('run_id', '')}  ",
            f"**分支数**: {aggregated['num_branches']}  ",
            f"",
            f"## 结局概率分布",
            f"",
        ]
        for outcome, prob in aggregated["outcome_distribution"].items():
            lines.append(f"- **{outcome}**: {prob * 100:.0f}%")

        metrics = aggregated.get("metrics", {})
        cr = metrics.get("conversion_rate", {})
        lines += [
            f"",
            f"## 关键指标",
            f"",
            f"| 指标 | 均值 | 标准差 | 各分支值 |",
            f"|------|------|--------|---------|",
            f"| 主产品转化率 | {cr.get('mean', 0):.1%} | {cr.get('std', 0):.3f} | {cr.get('values', [])} |",
        ]

        mp = metrics.get("main_product_purchases", {})
        lines.append(
            f"| 主产品购买次数 | {mp.get('mean', 0):.1f} | {mp.get('std', 0):.1f} | {mp.get('values', [])} |"
        )

        lines += [
            f"",
            f"## 各分支详情",
            f"",
            f"| 分支 | 结局 | 转化率 | 购买数 | XHS帖子 | XHS点赞 |",
            f"|------|------|--------|--------|---------|---------|",
        ]
        for r in branch_results:
            lines.append(
                f"| Branch {r['branch_id']} | {r['outcome']} | "
                f"{r['conversion_rate']:.1%} | {r['main_product_purchases']} | "
                f"{r['xhs_posts']} | {r['xhs_likes']} |"
            )

        lines += [
            f"",
            f"## 结论",
            f"",
            f"> 注意: 本模拟仅用于相对比较，不代表绝对预测。",
            f"> 不同分支间的差异性是概率分布分析有意义的前提。",
        ]
        return "\n".join(lines)

    # ──────────────── 文件工具 ────────────────

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        """写入 JSON 文件。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict]) -> None:
        """写入 JSONL 文件（每行一个 JSON）。"""
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
