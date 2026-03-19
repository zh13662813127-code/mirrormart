"""小红书平台环境（增强版）。

核心规则:
- 信息流 = 关注(40%) + 热度(40%) + 兴趣标签(20%)
- 热度 = log10(互动分) + 时间衰减(1 - age*0.01)
- 支持转发(repost)、引用评论(quote)
- get_trending() 返回热榜
"""

from __future__ import annotations

import math
import random
import uuid
from typing import Any

from mirrormart.platforms.base import PlatformBase


class XiaohongshuEnvironment(PlatformBase):
    """小红书环境（增强版）。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        """初始化小红书环境。

        Args:
            rng: 随机数生成器（传入以控制随机性）
        """
        self.rng = rng or random.Random()
        self.posts: list[dict[str, Any]] = []
        self.comments: dict[str, list[dict]] = {}    # post_id → comments
        self.likes: dict[str, set[str]] = {}          # post_id → {agent_ids}
        self.collections: dict[str, set[str]] = {}    # post_id → {agent_ids}
        self.following: dict[str, set[str]] = {}      # agent_id → {agent_ids}
        self.reposts: dict[str, list[dict]] = {}      # post_id → [repost records]
        self.current_step: int = 0

    # ──────────────── 初始化方法 ────────────────

    def add_initial_post(
        self,
        content: str,
        author_id: str,
        title: str = "",
        tags: list[str] | None = None,
        initial_likes: int = 0,
        initial_comments: int = 0,
        step: int = 0,
    ) -> str:
        """添加帖子（用于场景初始化或 Agent 发帖）。"""
        post_id = f"post_{uuid.uuid4().hex[:8]}"
        post = {
            "post_id": post_id,
            "author_id": author_id,
            "title": title,
            "content": content,
            "tags": tags or [],
            "likes": initial_likes,
            "comments_count": initial_comments,
            "collections": 0,
            "reposts": 0,
            "step": step,
        }
        self.posts.append(post)
        self.likes[post_id] = set()
        self.collections[post_id] = set()
        self.comments[post_id] = []
        self.reposts[post_id] = []
        return post_id

    def init_following(
        self,
        agent_ids: list[str],
        density: float = 0.15,
        min_follows: int = 3,
    ) -> None:
        """随机初始化关注关系。

        Args:
            agent_ids: 所有 Agent ID 列表
            density: 关注密度（每对 Agent 互相关注的概率）
            min_follows: 每个 Agent 最少关注人数，保证网络连通性
        """
        for aid in agent_ids:
            self.following[aid] = set()

        # 按密度建立随机关注关系
        for i, a in enumerate(agent_ids):
            for b in agent_ids[i + 1:]:
                if self.rng.random() < density:
                    self.following[a].add(b)
                    self.following[b].add(a)

        # 保底：确保每人至少关注 min_follows 个人，防止孤立节点
        for aid in agent_ids:
            others = [x for x in agent_ids if x != aid]
            deficit = min_follows - len(self.following[aid])
            if deficit > 0:
                candidates = [x for x in others if x not in self.following[aid]]
                extra = self.rng.sample(candidates, min(deficit, len(candidates)))
                for target in extra:
                    self.following[aid].add(target)

    # ──────────────── PlatformBase 实现 ────────────────

    def get_feed(
        self,
        agent_id: str,
        limit: int = 10,
        interest_tags: list[str] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """获取信息流。

        算法: 关注(40%) + 热度(40%) + 兴趣标签(20%)
        """
        if not self.posts:
            return []

        followed = self.following.get(agent_id, set())
        followed_posts = [p for p in self.posts if p["author_id"] in followed]
        hot_posts = sorted(self.posts, key=self._heat_score, reverse=True)

        # 兴趣标签匹配
        interest_tags = interest_tags or []
        tag_set = {t.lower() for t in interest_tags}
        tag_posts = [
            p for p in self.posts
            if tag_set & {t.lower() for t in p.get("tags", [])}
        ] if tag_set else []

        # 三路混合比例
        n_followed = max(1, int(limit * 0.4))
        n_hot = max(1, int(limit * 0.4))
        n_tag = max(1, limit - n_followed - n_hot)

        selected: list[dict] = []
        seen: set[str] = set()

        def _pick(pool: list[dict], n: int) -> None:
            sample = self.rng.sample(pool, min(n, len(pool))) if pool else []
            for p in sample:
                if p["post_id"] not in seen:
                    selected.append(p)
                    seen.add(p["post_id"])

        _pick(followed_posts, n_followed)
        # 热度路：按排序取，不随机
        for p in hot_posts:
            if len([x for x in selected if x["post_id"] not in {x["post_id"] for x in followed_posts}]) >= n_hot:
                break
            if p["post_id"] not in seen:
                selected.append(p)
                seen.add(p["post_id"])
        _pick(tag_posts, n_tag)

        # 补齐不足的部分
        for p in hot_posts:
            if len(selected) >= limit:
                break
            if p["post_id"] not in seen:
                selected.append(p)
                seen.add(p["post_id"])

        self.rng.shuffle(selected)
        return selected[:limit]

    def execute_action(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """执行 Agent 行为。

        支持: post, like, collect, comment, search, follow, repost, quote, browse, skip
        """
        action_type = action.get("type", "")
        handlers = {
            "post": self._action_post,
            "like": self._action_like,
            "collect": self._action_collect,
            "comment": self._action_comment,
            "search": self._action_search,
            "follow": self._action_follow,
            "repost": self._action_repost,
            "quote": self._action_quote,
        }
        handler = handlers.get(action_type)
        if handler:
            return handler(agent_id, action)
        if action_type in ("browse", "skip"):
            return {"success": True, "action_type": action_type, "effect": "无"}
        return {"success": False, "error": f"未知行为类型: {action_type}"}

    def get_trending(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回热榜（按热度降序）。"""
        return sorted(self.posts, key=self._heat_score, reverse=True)[:limit]

    def get_state_snapshot(self) -> dict[str, Any]:
        """获取平台状态快照。"""
        import copy
        return {
            "posts": copy.deepcopy(self.posts),
            "comments": copy.deepcopy(self.comments),
            "likes": {k: set(v) for k, v in self.likes.items()},
            "collections": {k: set(v) for k, v in self.collections.items()},
            "following": {k: set(v) for k, v in self.following.items()},
            "reposts": copy.deepcopy(self.reposts),
            "current_step": self.current_step,
        }

    def restore_state(self, snapshot: dict[str, Any]) -> None:
        """从快照恢复状态。"""
        import copy
        self.posts = copy.deepcopy(snapshot["posts"])
        self.comments = copy.deepcopy(snapshot["comments"])
        self.likes = {k: set(v) for k, v in snapshot["likes"].items()}
        self.collections = {k: set(v) for k, v in snapshot["collections"].items()}
        self.following = {k: set(v) for k, v in snapshot["following"].items()}
        self.reposts = copy.deepcopy(snapshot.get("reposts", {}))
        self.current_step = snapshot.get("current_step", 0)

    def get_metrics(self) -> dict[str, Any]:
        """返回平台关键指标。"""
        total_likes = sum(p["likes"] for p in self.posts)
        total_comments = sum(p["comments_count"] for p in self.posts)
        total_collections = sum(p["collections"] for p in self.posts)
        total_reposts = sum(p.get("reposts", 0) for p in self.posts)
        return {
            "total_posts": len(self.posts),
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_collections": total_collections,
            "total_reposts": total_reposts,
            "avg_heat": (
                sum(self._heat_score(p) for p in self.posts) / len(self.posts)
                if self.posts else 0
            ),
        }

    # ──────────────── 私有辅助方法 ────────────────

    def _heat_score(self, post: dict[str, Any]) -> float:
        """计算帖子热度分（含时间衰减）。

        公式: log10(互动分+1) + (1 - age * 0.01)
        互动分 = likes*2 + comments*3 + collections*5 + reposts*4
        age = current_step - post_step
        """
        interaction = (
            post["likes"] * 2
            + post["comments_count"] * 3
            + post["collections"] * 5
            + post.get("reposts", 0) * 4
        )
        age = max(0, self.current_step - post.get("step", 0))
        time_decay = max(0.0, 1.0 - age * 0.01)
        return math.log10(interaction + 1) + time_decay

    def _action_post(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        post_id = self.add_initial_post(
            content=action.get("content", ""),
            author_id=agent_id,
            title=action.get("title", ""),
            tags=action.get("tags", []),
            step=self.current_step,
        )
        return {"success": True, "action_type": "post", "post_id": post_id,
                "effect": f"发布了新笔记 {post_id}"}

    def _action_like(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        post = self._find_post(target_id)
        if not post:
            return {"success": False, "error": f"帖子 {target_id} 不存在"}
        if agent_id not in self.likes.get(target_id, set()):
            self.likes.setdefault(target_id, set()).add(agent_id)
            post["likes"] += 1
        return {"success": True, "action_type": "like", "target_id": target_id,
                "effect": f"点赞了 {target_id}"}

    def _action_collect(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        post = self._find_post(target_id)
        if not post:
            return {"success": False, "error": f"帖子 {target_id} 不存在"}
        if agent_id not in self.collections.get(target_id, set()):
            self.collections.setdefault(target_id, set()).add(agent_id)
            post["collections"] += 1
        return {"success": True, "action_type": "collect", "target_id": target_id,
                "effect": f"收藏了 {target_id}"}

    def _action_comment(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        post = self._find_post(target_id)
        if not post:
            return {"success": False, "error": f"帖子 {target_id} 不存在"}
        comment = {
            "comment_id": f"cmt_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "content": action.get("content", ""),
        }
        self.comments.setdefault(target_id, []).append(comment)
        post["comments_count"] += 1
        return {"success": True, "action_type": "comment", "comment_id": comment["comment_id"],
                "effect": f"在 {target_id} 下评论了"}

    def _action_search(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        query = action.get("query", "").lower()
        results = [
            p for p in self.posts
            if query in p["content"].lower() or query in p["title"].lower()
            or any(query in tag.lower() for tag in p.get("tags", []))
        ]
        results.sort(key=self._heat_score, reverse=True)
        return {
            "success": True,
            "action_type": "search",
            "query": query,
            "results": results[:10],
            "effect": f"搜索'{query}'，找到{len(results)}条结果",
        }

    def _action_follow(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        self.following.setdefault(agent_id, set()).add(target_id)
        return {"success": True, "action_type": "follow", "target_id": target_id,
                "effect": f"关注了 {target_id}"}

    def _action_repost(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """转发帖子。"""
        target_id = action.get("target_id", "")
        post = self._find_post(target_id)
        if not post:
            return {"success": False, "error": f"帖子 {target_id} 不存在"}
        record = {
            "repost_id": f"rp_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "step": self.current_step,
        }
        self.reposts.setdefault(target_id, []).append(record)
        post["reposts"] = post.get("reposts", 0) + 1
        return {"success": True, "action_type": "repost", "target_id": target_id,
                "effect": f"转发了 {target_id}"}

    def _action_quote(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """引用评论：转发 + 附带评论内容。"""
        target_id = action.get("target_id", "")
        post = self._find_post(target_id)
        if not post:
            return {"success": False, "error": f"帖子 {target_id} 不存在"}
        quote_content = action.get("content", "")
        # 引用算一次转发 + 一条评论
        record = {
            "repost_id": f"qt_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "content": quote_content,
            "step": self.current_step,
        }
        self.reposts.setdefault(target_id, []).append(record)
        post["reposts"] = post.get("reposts", 0) + 1
        comment = {
            "comment_id": f"cmt_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "content": f"[引用转发] {quote_content}",
        }
        self.comments.setdefault(target_id, []).append(comment)
        post["comments_count"] += 1
        return {"success": True, "action_type": "quote", "target_id": target_id,
                "effect": f"引用转发了 {target_id}，附评论: {quote_content[:30]}"}

    def _find_post(self, post_id: str) -> dict[str, Any] | None:
        for p in self.posts:
            if p["post_id"] == post_id:
                return p
        return None

    def get_post_detail(self, post_id: str) -> dict[str, Any] | None:
        """获取帖子详情（含评论和转发数）。"""
        post = self._find_post(post_id)
        if not post:
            return None
        return {
            **post,
            "comment_list": self.comments.get(post_id, []),
            "repost_list": self.reposts.get(post_id, []),
        }
