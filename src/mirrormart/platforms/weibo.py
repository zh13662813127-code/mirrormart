"""微博平台环境。

核心规则:
- 热搜机制: 短时间内互动量飙升的话题进入热搜榜
- 转发链扩散: 转发带评论形成信息级联传播
- 信息流 = 关注(50%) + 热搜/推荐(50%)
- 热搜分数 = 转发数*3 + 评论数*2 + 点赞数 + 话题引用数*5
"""

from __future__ import annotations

import math
import random
import uuid
from typing import Any

from mirrormart.platforms.base import PlatformBase


class WeiboEnvironment(PlatformBase):
    """微博环境。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        """初始化微博环境。"""
        self.rng = rng or random.Random()
        self.posts: list[dict[str, Any]] = []
        self.comments: dict[str, list[dict]] = {}      # post_id → comments
        self.likes: dict[str, set[str]] = {}            # post_id → {agent_ids}
        self.reposts: dict[str, list[dict]] = {}        # post_id → [repost records]
        self.following: dict[str, set[str]] = {}        # agent_id → {agent_ids}
        self.topics: dict[str, list[str]] = {}          # topic_name → [post_ids]
        self.current_step: int = 0

    # ──────────────── 初始化方法 ────────────────

    def add_post(
        self,
        content: str,
        author_id: str,
        topics: list[str] | None = None,
        initial_likes: int = 0,
        initial_reposts: int = 0,
        initial_comments: int = 0,
        step: int = 0,
    ) -> str:
        """添加微博帖子。"""
        post_id = f"wb_{uuid.uuid4().hex[:8]}"
        post = {
            "post_id": post_id,
            "author_id": author_id,
            "content": content,
            "topics": topics or [],
            "likes": initial_likes,
            "reposts": initial_reposts,
            "comments_count": initial_comments,
            "step": step,
        }
        self.posts.append(post)
        self.likes[post_id] = set()
        self.comments[post_id] = []
        self.reposts[post_id] = []

        # 注册话题索引
        for topic in post["topics"]:
            self.topics.setdefault(topic, []).append(post_id)

        return post_id

    def init_following(
        self,
        agent_ids: list[str],
        density: float = 0.2,
        min_follows: int = 3,
    ) -> None:
        """随机初始化关注关系（微博关注密度较高）。"""
        for aid in agent_ids:
            self.following[aid] = set()

        for i, a in enumerate(agent_ids):
            for b in agent_ids[i + 1:]:
                if self.rng.random() < density:
                    self.following[a].add(b)
                    self.following[b].add(a)

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
        """获取微博信息流。

        关注(50%) + 热门推荐(50%)
        """
        if not self.posts:
            return []

        followed = self.following.get(agent_id, set())
        followed_posts = [p for p in self.posts if p["author_id"] in followed]
        hot_posts = sorted(self.posts, key=self._hot_score, reverse=True)

        n_follow = max(1, int(limit * 0.5))
        n_hot = limit - n_follow

        selected: list[dict] = []
        seen: set[str] = set()

        # 关注的人的微博
        sample = self.rng.sample(followed_posts, min(n_follow, len(followed_posts))) if followed_posts else []
        for p in sample:
            selected.append(p)
            seen.add(p["post_id"])

        # 热门微博补充
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

        支持: post, like, comment, repost, search, search_topic, follow, browse, skip
        """
        action_type = action.get("type", "")
        handlers = {
            "post": self._action_post,
            "like": self._action_like,
            "comment": self._action_comment,
            "repost": self._action_repost,
            "search": self._action_search,
            "search_topic": self._action_search_topic,
            "follow": self._action_follow,
        }
        handler = handlers.get(action_type)
        if handler:
            return handler(agent_id, action)
        if action_type in ("browse", "skip"):
            return {"success": True, "action_type": action_type, "effect": "无"}
        return {"success": False, "error": f"未知行为类型: {action_type}"}

    def get_hot_search(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回热搜榜。

        按话题下所有帖子的热度总分排序。
        """
        topic_scores: dict[str, float] = {}
        for topic, post_ids in self.topics.items():
            score = 0.0
            for pid in post_ids:
                post = self._find_post(pid)
                if post:
                    score += self._hot_score(post)
            topic_scores[topic] = score

        ranked = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
        return [
            {"topic": topic, "score": round(score, 2), "post_count": len(self.topics.get(topic, []))}
            for topic, score in ranked[:limit]
        ]

    def get_state_snapshot(self) -> dict[str, Any]:
        """获取平台状态快照。"""
        import copy
        return {
            "posts": copy.deepcopy(self.posts),
            "comments": copy.deepcopy(self.comments),
            "likes": {k: set(v) for k, v in self.likes.items()},
            "reposts": copy.deepcopy(self.reposts),
            "following": {k: set(v) for k, v in self.following.items()},
            "topics": copy.deepcopy(self.topics),
            "current_step": self.current_step,
        }

    def restore_state(self, snapshot: dict[str, Any]) -> None:
        """从快照恢复状态。"""
        import copy
        self.posts = copy.deepcopy(snapshot["posts"])
        self.comments = copy.deepcopy(snapshot["comments"])
        self.likes = {k: set(v) for k, v in snapshot["likes"].items()}
        self.reposts = copy.deepcopy(snapshot.get("reposts", {}))
        self.following = {k: set(v) for k, v in snapshot["following"].items()}
        self.topics = copy.deepcopy(snapshot.get("topics", {}))
        self.current_step = snapshot.get("current_step", 0)

    def get_metrics(self) -> dict[str, Any]:
        """返回平台关键指标。"""
        total_likes = sum(p["likes"] for p in self.posts)
        total_reposts = sum(p["reposts"] for p in self.posts)
        total_comments = sum(p["comments_count"] for p in self.posts)
        return {
            "total_posts": len(self.posts),
            "total_likes": total_likes,
            "total_reposts": total_reposts,
            "total_comments": total_comments,
            "total_topics": len(self.topics),
            "hot_search": self.get_hot_search(limit=5),
        }

    # ──────────────── 私有辅助方法 ────────────────

    def _hot_score(self, post: dict[str, Any]) -> float:
        """计算微博热度分。

        公式: 转发*3 + 评论*2 + 点赞 + 时间衰减
        """
        interaction = (
            post["reposts"] * 3
            + post["comments_count"] * 2
            + post["likes"]
        )
        age = max(0, self.current_step - post.get("step", 0))
        time_decay = max(0.0, 1.0 - age * 0.015)
        return math.log10(interaction + 1) + time_decay

    def _action_post(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        topics = action.get("topics", [])
        post_id = self.add_post(
            content=action.get("content", ""),
            author_id=agent_id,
            topics=topics,
            step=self.current_step,
        )
        return {"success": True, "action_type": "post", "post_id": post_id,
                "effect": f"发布了微博 {post_id}"}

    def _action_like(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        post = self._find_post(target_id)
        if not post:
            return {"success": False, "error": f"微博 {target_id} 不存在"}
        if agent_id not in self.likes.get(target_id, set()):
            self.likes.setdefault(target_id, set()).add(agent_id)
            post["likes"] += 1
        return {"success": True, "action_type": "like", "target_id": target_id,
                "effect": f"点赞了 {target_id}"}

    def _action_comment(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        post = self._find_post(target_id)
        if not post:
            return {"success": False, "error": f"微博 {target_id} 不存在"}
        comment = {
            "comment_id": f"cmt_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "content": action.get("content", ""),
        }
        self.comments.setdefault(target_id, []).append(comment)
        post["comments_count"] += 1
        return {"success": True, "action_type": "comment",
                "comment_id": comment["comment_id"],
                "effect": f"在 {target_id} 下评论了"}

    def _action_repost(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """转发微博（微博核心传播机制）。"""
        target_id = action.get("target_id", "")
        post = self._find_post(target_id)
        if not post:
            return {"success": False, "error": f"微博 {target_id} 不存在"}
        repost_content = action.get("content", "")
        record = {
            "repost_id": f"rp_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "content": repost_content,
            "step": self.current_step,
        }
        self.reposts.setdefault(target_id, []).append(record)
        post["reposts"] += 1

        # 转发也生成一条新微博（带原文引用）
        new_content = f"转发@{post['author_id']}: {post['content'][:50]}"
        if repost_content:
            new_content = f"{repost_content} //{new_content}"
        self.add_post(
            content=new_content,
            author_id=agent_id,
            topics=post.get("topics", []),
            step=self.current_step,
        )

        return {"success": True, "action_type": "repost", "target_id": target_id,
                "effect": f"转发了 {target_id}"}

    def _action_search(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        query = action.get("query", "").lower()
        results = [
            p for p in self.posts
            if query in p["content"].lower()
            or any(query in t.lower() for t in p.get("topics", []))
        ]
        results.sort(key=self._hot_score, reverse=True)
        return {
            "success": True,
            "action_type": "search",
            "query": query,
            "results": results[:10],
            "effect": f"搜索'{query}'，找到{len(results)}条微博",
        }

    def _action_search_topic(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """搜索话题下的所有微博。"""
        topic = action.get("topic", "")
        post_ids = self.topics.get(topic, [])
        posts = [self._find_post(pid) for pid in post_ids]
        posts = [p for p in posts if p is not None]
        posts.sort(key=self._hot_score, reverse=True)
        return {
            "success": True,
            "action_type": "search_topic",
            "topic": topic,
            "results": posts[:10],
            "effect": f"查看话题#{topic}#，{len(posts)}条微博",
        }

    def _action_follow(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        self.following.setdefault(agent_id, set()).add(target_id)
        return {"success": True, "action_type": "follow", "target_id": target_id,
                "effect": f"关注了 {target_id}"}

    def _find_post(self, post_id: str) -> dict[str, Any] | None:
        for p in self.posts:
            if p["post_id"] == post_id:
                return p
        return None
