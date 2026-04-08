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
from mirrormart.diffusion import DiffusionEngine
from mirrormart.kol_tracker import KOLTracker
from mirrormart.sentiment import SentimentTracker
from mirrormart.temporal import TemporalAnalyzer
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
        self._diffusion = DiffusionEngine()
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

        # 初始化情感追踪、KOL 追踪和时间维度分析
        product_price = self.scenario.get("product", {}).get("price", 59)
        sentiment_tracker = SentimentTracker()
        kol_tracker = KOLTracker(product_price=product_price)
        temporal_analyzer = TemporalAnalyzer(num_steps=self.config.num_steps)

        # 注册 KOL 初始内容
        self._register_kol_content(kol_tracker, platforms)

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

            # 社交网络扩散：本步事件影响关注者的购买意向
            step_events = [e for e in events if e.get("branch_step") == step]
            if step_events:
                follow_graphs = DiffusionEngine.build_follow_graphs(platforms)
                self._diffusion.propagate(agents, step_events, follow_graphs)

                # 情感分析 + KOL 追踪 + 时间维度分析
                for ev in step_events:
                    sentiment_tracker.track_event(ev)
                    kol_tracker.track_interaction(ev)
                    temporal_analyzer.track_event(ev)

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
        result = self._summarize_branch(
            branch_id, agents, platforms, events,
            sentiment_tracker=sentiment_tracker,
            kol_tracker=kol_tracker,
            temporal_analyzer=temporal_analyzer,
        )

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

        # 基础概率：场景配置 > 默认值
        default_weights = {"xiaohongshu": 0.35, "douyin": 0.25, "weibo": 0.15, "taobao": 0.25}
        scenario_weights = self.scenario.get("simulation", {}).get("platform_weights", {})
        weights = {k: scenario_weights.get(k, default_weights[k]) for k in default_weights}

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
        default_keywords = ["面膜", "氨基酸面膜", "敏感肌面膜", "温和护肤"]
        search_keywords = self.scenario.get("product", {}).get("search_keywords", default_keywords)
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
        sentiment_tracker: SentimentTracker | None = None,
        kol_tracker: KOLTracker | None = None,
        temporal_analyzer: TemporalAnalyzer | None = None,
    ) -> dict[str, Any]:
        """汇总单分支结果。"""
        xhs_metrics = platforms["xiaohongshu"].get_metrics()
        taobao_metrics = platforms["taobao"].get_metrics()
        douyin_metrics = platforms["douyin"].get_metrics()
        weibo_metrics = platforms["weibo"].get_metrics()
        purchases = taobao_metrics["total_purchases"]
        num_agents = len(agents)

        # 各产品购买数
        conversion_by_product = taobao_metrics.get("conversion_by_product", {})
        main_product_purchases = conversion_by_product.get("product_main", 0)

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
            "conversion_by_product": conversion_by_product,
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
            "sentiment": sentiment_tracker.get_summary() if sentiment_tracker else {},
            "kol": kol_tracker.get_summary() if kol_tracker else {},
            "temporal": temporal_analyzer.get_summary() if temporal_analyzer else {},
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

        # 多产品竞争分析：汇总各产品的购买分布
        all_product_ids: set[str] = set()
        for r in branch_results:
            all_product_ids.update(r.get("conversion_by_product", {}).keys())
        product_stats: dict[str, dict[str, Any]] = {}
        for pid in sorted(all_product_ids):
            vals = [r.get("conversion_by_product", {}).get(pid, 0) for r in branch_results]
            mean_val = sum(vals) / len(vals) if vals else 0
            product_stats[pid] = {
                "mean": round(mean_val, 2),
                "values": vals,
            }

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
                "product_competition": product_stats,
            },
            "sentiment_overview": self._aggregate_sentiment(branch_results),
            "kol_overview": self._aggregate_kol(branch_results),
            "temporal_overview": self._aggregate_temporal(branch_results),
        }

    def _generate_report(
        self,
        aggregated: dict[str, Any],
        branch_results: list[dict[str, Any]],
    ) -> str:
        """生成增强版 Markdown 分析报告（含四平台指标 + Agent 行为分析）。"""
        run_id = aggregated.get("run_id", "")
        n = aggregated["num_branches"]
        od = aggregated["outcome_distribution"]
        metrics = aggregated.get("metrics", {})
        cr = metrics.get("conversion_rate", {})
        mp = metrics.get("main_product_purchases", {})

        lines = [
            f"# 模拟分析报告",
            f"",
            f"**运行ID**: {run_id}  ",
            f"**场景**: {self.scenario.get('name', '')}  ",
            f"**分支数**: {n}  ",
            f"**步数**: {self.config.num_steps}  ",
            f"**模型**: {self.config.llm_model}  ",
            f"",
            f"---",
            f"",
            f"## 1. 结局概率分布",
            f"",
        ]
        for outcome, prob in od.items():
            bar = "=" * int(prob * 30)
            lines.append(f"- **{outcome}**: {prob * 100:.0f}% `{bar}`")

        lines += [
            f"",
            f"## 2. 核心转化指标",
            f"",
            f"| 指标 | 均值 | 标准差 |",
            f"|------|------|--------|",
            f"| 主产品转化率 | {cr.get('mean', 0):.1%} | {cr.get('std', 0):.3f} |",
            f"| 主产品购买次数 | {mp.get('mean', 0):.1f} | {mp.get('std', 0):.1f} |",
            f"",
            f"## 3. 四平台指标汇总",
            f"",
            f"| 分支 | 结局 | 转化率 | XHS帖/赞/评/转 | 抖音视频/播放/赞 | 微博帖/转发/评 | 淘宝购买/营收/收藏 |",
            f"|------|------|--------|----------------|-----------------|---------------|-------------------|",
        ]
        for r in branch_results:
            lines.append(
                f"| B{r['branch_id']} | {r['outcome']} | {r['conversion_rate']:.1%} "
                f"| {r['xhs_posts']}/{r['xhs_likes']}/{r['xhs_comments']}/{r.get('xhs_reposts', 0)} "
                f"| {r.get('douyin_videos', 0)}/{r.get('douyin_views', 0)}/{r.get('douyin_likes', 0)} "
                f"| {r.get('weibo_posts', 0)}/{r.get('weibo_reposts', 0)}/{r.get('weibo_comments', 0)} "
                f"| {r['taobao_purchases']}/{r.get('taobao_revenue', 0)}/{r.get('taobao_wishlist', 0)} |"
            )

        # Agent 行为分析（从最近的运行数据统计）
        lines += [
            f"",
            f"## 4. Agent 行为模式分析",
            f"",
        ]
        # 统计各分支的行为分布
        action_counts: dict[str, int] = {}
        platform_counts: dict[str, int] = {}
        total_events = sum(r.get("total_events", 0) for r in branch_results)
        high_intent_total = sum(r.get("high_intent_agents", 0) for r in branch_results)

        for r in branch_results:
            events_file = (
                Path(self.config.output_dir) / run_id / f"branch_{r['branch_id']}" / "events.jsonl"
            )
            if events_file.exists():
                for line in events_file.read_text(encoding="utf-8").strip().split("\n"):
                    if not line:
                        continue
                    ev = json.loads(line)
                    at = ev.get("action", {}).get("type", "unknown")
                    pf = ev.get("platform", "unknown")
                    action_counts[at] = action_counts.get(at, 0) + 1
                    platform_counts[pf] = platform_counts.get(pf, 0) + 1

        if action_counts:
            lines += [
                f"**总事件数**: {total_events}  ",
                f"**高购买意向 Agent 总数**: {high_intent_total}（跨{n}分支累计）  ",
                f"",
                f"### 行为类型分布",
                f"",
                f"| 行为 | 次数 | 占比 |",
                f"|------|------|------|",
            ]
            total_actions = sum(action_counts.values())
            for act, cnt in sorted(action_counts.items(), key=lambda x: x[1], reverse=True):
                pct = cnt / total_actions * 100 if total_actions else 0
                lines.append(f"| {act} | {cnt} | {pct:.1f}% |")

            lines += [
                f"",
                f"### 平台使用分布",
                f"",
                f"| 平台 | 次数 | 占比 |",
                f"|------|------|------|",
            ]
            for pf, cnt in sorted(platform_counts.items(), key=lambda x: x[1], reverse=True):
                pct = cnt / total_actions * 100 if total_actions else 0
                lines.append(f"| {pf} | {cnt} | {pct:.1f}% |")

        # 关键发现与结论
        lines += [
            f"",
            f"## 5. 关键发现",
            f"",
        ]

        # 自动生成发现
        best_branch = max(branch_results, key=lambda r: r["conversion_rate"])
        worst_branch = min(branch_results, key=lambda r: r["conversion_rate"])
        if best_branch["conversion_rate"] > 0:
            lines.append(
                f"- **最佳分支**: Branch {best_branch['branch_id']}，"
                f"转化率 {best_branch['conversion_rate']:.1%}，"
                f"购买 {best_branch['main_product_purchases']} 次"
            )
        if best_branch["branch_id"] != worst_branch["branch_id"]:
            lines.append(
                f"- **最差分支**: Branch {worst_branch['branch_id']}，"
                f"转化率 {worst_branch['conversion_rate']:.1%}"
            )
        cr_std = cr.get("std", 0)
        if cr_std > 0.05:
            lines.append(f"- **分支差异显著**（标准差={cr_std:.3f}），概率分布分析有意义")
        elif cr_std == 0:
            lines.append(f"- **分支差异为零**，所有分支转化率相同，建议增加步数或 Agent 数量")
        else:
            lines.append(f"- **分支差异较小**（标准差={cr_std:.3f}），建议增加分支数以提高统计显著性")

        # 平台贡献度
        if platform_counts:
            top_platform = max(platform_counts.items(), key=lambda x: x[1])
            lines.append(f"- **最活跃平台**: {top_platform[0]}（{top_platform[1]}次行为）")

        if action_counts.get("purchase", 0) == 0 and action_counts.get("add_cart", 0) > 0:
            lines.append(f"- **存在加购未转化问题**：加购 {action_counts['add_cart']} 次但无购买，建议优化价格或促销策略")

        # 多产品竞争分析
        product_comp = metrics.get("product_competition", {})
        if len(product_comp) > 1:
            lines += [
                f"",
                f"## 6. 多产品竞争分析",
                f"",
                f"| 产品 | 平均购买次数 | 各分支购买 |",
                f"|------|-------------|-----------|",
            ]
            for pid, stats in sorted(
                product_comp.items(),
                key=lambda x: x[1].get("mean", 0),
                reverse=True,
            ):
                lines.append(
                    f"| {pid} | {stats['mean']:.1f} | {stats.get('values', [])} |"
                )

            # 市场份额
            total_mean = sum(s["mean"] for s in product_comp.values())
            if total_mean > 0:
                lines += [f"", f"**市场份额分布**:"]
                for pid, stats in sorted(
                    product_comp.items(),
                    key=lambda x: x[1].get("mean", 0),
                    reverse=True,
                ):
                    share = stats["mean"] / total_mean * 100
                    bar = "=" * int(share / 3)
                    lines.append(f"- {pid}: {share:.0f}% `{bar}`")

        # 情感分析
        sentiment = aggregated.get("sentiment_overview", {})
        avg_pol = sentiment.get("avg_polarity", 0)
        pol_label = "正面" if avg_pol > 0.2 else ("负面" if avg_pol < -0.2 else "中性")
        lines += [
            f"",
            f"## 7. 舆情分析",
            f"",
            f"**整体情感极性**: {avg_pol:.3f}（{pol_label}）  ",
            f"**各分支极性**: {sentiment.get('polarity_values', [])}  ",
            f"",
        ]
        pf_sent = sentiment.get("platform_sentiment", {})
        if pf_sent:
            lines += [
                f"| 平台 | 正面 | 负面 | 中性 |",
                f"|------|------|------|------|",
            ]
            for pf, counts in pf_sent.items():
                lines.append(
                    f"| {pf} | {counts.get('positive', 0)} | {counts.get('negative', 0)} | {counts.get('neutral', 0)} |"
                )

        # KOL 分析
        kol_overview = aggregated.get("kol_overview", {})
        kol_list = kol_overview.get("kol_summary", [])
        if kol_list:
            lines += [
                f"",
                f"## 8. KOL 影响力分析",
                f"",
                f"| KOL | 内容数 | 平均互动 | 平均转化 |",
                f"|-----|--------|---------|---------|",
            ]
            for kol in kol_list:
                lines.append(
                    f"| {kol['kol_id']} | {kol['content_count']} "
                    f"| {kol['avg_engagement']:.0f} | {kol['avg_conversions']:.1f} |"
                )

        # 时间维度分析
        temporal = aggregated.get("temporal_overview", {})
        if temporal:
            phases = temporal.get("phases", {})
            lines += [
                f"",
                f"## 9. 时间维度分析",
                f"",
                f"### 阶段对比",
                f"",
                f"| 阶段 | 平均事件数 | 平均转化 | 平均购买意向 |",
                f"|------|-----------|---------|-------------|",
            ]
            phase_labels = {"early": "早期（种草）", "mid": "中期（决策）", "late": "晚期（转化）"}
            for phase in ("early", "mid", "late"):
                p = phases.get(phase, {})
                lines.append(
                    f"| {phase_labels.get(phase, phase)} "
                    f"| {p.get('avg_events', 0):.1f} "
                    f"| {p.get('avg_conversions', 0):.1f} "
                    f"| {p.get('avg_intent', 0):.3f} |"
                )

            # 转化高峰
            conv_timeline = temporal.get("total_conversion_timeline", [])
            if conv_timeline and max(conv_timeline) > 0:
                peak_step = conv_timeline.index(max(conv_timeline))
                lines += [
                    f"",
                    f"**转化高峰**: 第 {peak_step} 步（共 {max(conv_timeline)} 次购买）  ",
                ]

        lines += [
            f"",
            f"---",
            f"",
            f"> 本模拟仅用于相对比较，不代表绝对预测。",
        ]
        return "\n".join(lines)

    def _aggregate_sentiment(
        self, branch_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """聚合多分支的情感分析数据。"""
        polarities = []
        platform_totals: dict[str, dict[str, int]] = {}
        for r in branch_results:
            s = r.get("sentiment", {})
            if s.get("overall_polarity") is not None:
                polarities.append(s["overall_polarity"])
            for pf, counts in s.get("platform_sentiment", {}).items():
                if pf not in platform_totals:
                    platform_totals[pf] = {"positive": 0, "negative": 0, "neutral": 0}
                for k in ("positive", "negative", "neutral"):
                    platform_totals[pf][k] += counts.get(k, 0)

        avg_polarity = round(sum(polarities) / len(polarities), 3) if polarities else 0.0
        return {
            "avg_polarity": avg_polarity,
            "polarity_values": polarities,
            "platform_sentiment": platform_totals,
        }

    def _aggregate_kol(
        self, branch_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """聚合多分支的 KOL 追踪数据。"""
        kol_totals: dict[str, dict[str, float]] = {}
        for r in branch_results:
            kol_data = r.get("kol", {})
            for perf in kol_data.get("kol_performance", []):
                kid = perf["kol_id"]
                if kid not in kol_totals:
                    kol_totals[kid] = {
                        "total_engagement": 0,
                        "conversions": 0,
                        "content_count": 0,
                        "branches": 0,
                    }
                kol_totals[kid]["total_engagement"] += perf.get("total_engagement", 0)
                kol_totals[kid]["conversions"] += perf.get("conversions", 0)
                kol_totals[kid]["content_count"] = perf.get("content_count", 0)
                kol_totals[kid]["branches"] += 1

        kol_summary = []
        for kid, totals in sorted(kol_totals.items(), key=lambda x: x[1]["total_engagement"], reverse=True):
            n = totals["branches"] or 1
            kol_summary.append({
                "kol_id": kid,
                "avg_engagement": round(totals["total_engagement"] / n, 1),
                "avg_conversions": round(totals["conversions"] / n, 2),
                "content_count": totals["content_count"],
            })

        return {"kol_summary": kol_summary}

    def _aggregate_temporal(
        self, branch_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """聚合多分支的时间维度数据（取平均值）。"""
        if not branch_results:
            return {}
        temporals = [r.get("temporal", {}) for r in branch_results if r.get("temporal")]
        if not temporals:
            return {}

        num_steps = temporals[0].get("num_steps", 0)
        n = len(temporals)

        # 平均每步事件密度
        avg_density = [
            round(sum(t.get("step_density", [0] * num_steps)[s] for t in temporals) / n, 1)
            for s in range(num_steps)
        ]

        # 平均每步购买意向
        avg_intent = [
            round(sum(t.get("intent_timeline", [0] * num_steps)[s] for t in temporals) / n, 3)
            for s in range(num_steps)
        ]

        # 累计转化时间线
        total_conversions = [
            sum(t.get("conversion_timeline", [0] * num_steps)[s] for t in temporals)
            for s in range(num_steps)
        ]

        # 平均平台时间线
        all_platforms: set[str] = set()
        for t in temporals:
            all_platforms.update(t.get("platform_timeline", {}).keys())
        avg_platform_timeline: dict[str, list[float]] = {}
        for pf in sorted(all_platforms):
            avg_platform_timeline[pf] = [
                round(
                    sum(
                        t.get("platform_timeline", {}).get(pf, [0] * num_steps)[s]
                        for t in temporals
                    ) / n, 1
                )
                for s in range(num_steps)
            ]

        # 聚合阶段分析
        phase_names = ["early", "mid", "late"]
        avg_phases: dict[str, Any] = {}
        for phase in phase_names:
            events = round(sum(
                t.get("phases", {}).get(phase, {}).get("total_events", 0)
                for t in temporals
            ) / n, 1)
            conversions = round(sum(
                t.get("phases", {}).get(phase, {}).get("conversions", 0)
                for t in temporals
            ) / n, 1)
            intents = [
                t.get("phases", {}).get(phase, {}).get("avg_purchase_intent", 0)
                for t in temporals
            ]
            avg_phases[phase] = {
                "avg_events": events,
                "avg_conversions": conversions,
                "avg_intent": round(sum(intents) / len(intents), 3) if intents else 0,
            }

        return {
            "num_steps": num_steps,
            "avg_step_density": avg_density,
            "avg_intent_timeline": avg_intent,
            "total_conversion_timeline": total_conversions,
            "avg_platform_timeline": avg_platform_timeline,
            "phases": avg_phases,
        }

    def _register_kol_content(
        self,
        kol_tracker: KOLTracker,
        platforms: dict[str, Any],
    ) -> None:
        """从平台初始内容中注册 KOL 内容到追踪器。"""
        # 小红书帖子
        xhs = platforms.get("xiaohongshu")
        if xhs:
            for post in getattr(xhs, "posts", []):
                author = post.get("author_id", "")
                kol_tracker.register_content(
                    content_id=post.get("post_id", ""),
                    author_id=author,
                    platform="xiaohongshu",
                    title=post.get("title", ""),
                    content_type="post",
                )
        # 抖音视频
        douyin = platforms.get("douyin")
        if douyin:
            for video in getattr(douyin, "videos", []):
                author = video.get("author_id", "")
                kol_tracker.register_content(
                    content_id=video.get("video_id", ""),
                    author_id=author,
                    platform="douyin",
                    title=video.get("title", ""),
                    content_type="video",
                )
        # 微博帖子
        weibo = platforms.get("weibo")
        if weibo:
            for post in getattr(weibo, "posts", []):
                author = post.get("author_id", "")
                kol_tracker.register_content(
                    content_id=post.get("post_id", ""),
                    author_id=author,
                    platform="weibo",
                    title="",
                    content_type="weibo",
                )

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
