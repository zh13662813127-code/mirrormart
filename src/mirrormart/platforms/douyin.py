"""抖音平台环境。

核心规则:
- 短视频信息流 = 完播率加权推荐 + 互动热度 + 兴趣标签
- 完播率(completion_rate) 是核心指标，影响推荐权重
- 推荐算法: score = 完播率*3 + 点赞率*2 + 评论率*1 + 时间衰减
"""

from __future__ import annotations

import math
import random
import uuid
from typing import Any

from mirrormart.platforms.base import PlatformBase


class DouyinEnvironment(PlatformBase):
    """抖音短视频环境。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        """初始化抖音环境。"""
        self.rng = rng or random.Random()
        self.videos: list[dict[str, Any]] = []
        self.comments: dict[str, list[dict]] = {}     # video_id → comments
        self.likes: dict[str, set[str]] = {}           # video_id → {agent_ids}
        self.shares: dict[str, list[dict]] = {}        # video_id → [share records]
        self.following: dict[str, set[str]] = {}       # agent_id → {agent_ids}
        self.watch_history: dict[str, list[str]] = {}  # agent_id → [video_ids]
        self.current_step: int = 0

    # ──────────────── 初始化方法 ────────────────

    def add_video(
        self,
        content: str,
        author_id: str,
        title: str = "",
        tags: list[str] | None = None,
        duration: int = 30,
        initial_views: int = 0,
        initial_likes: int = 0,
        initial_comments: int = 0,
        completion_rate: float = 0.6,
        step: int = 0,
    ) -> str:
        """添加视频（用于场景初始化或 Agent 发布）。"""
        video_id = f"vid_{uuid.uuid4().hex[:8]}"
        video = {
            "video_id": video_id,
            "author_id": author_id,
            "title": title,
            "content": content,
            "tags": tags or [],
            "duration": duration,
            "views": initial_views,
            "likes": initial_likes,
            "comments_count": initial_comments,
            "shares": 0,
            "completion_rate": completion_rate,
            "step": step,
        }
        self.videos.append(video)
        self.likes[video_id] = set()
        self.comments[video_id] = []
        self.shares[video_id] = []
        return video_id

    def init_following(
        self,
        agent_ids: list[str],
        density: float = 0.1,
        min_follows: int = 2,
    ) -> None:
        """随机初始化关注关系（抖音关注密度比小红书低）。"""
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
        """获取推荐视频流。

        抖音以推荐为主（80%），关注仅占 20%。
        推荐权重 = 完播率*3 + 互动热度 + 兴趣标签匹配 + 时间衰减
        """
        if not self.videos:
            return []

        watched = set(self.watch_history.get(agent_id, []))
        interest_tags = interest_tags or []
        tag_set = {t.lower() for t in interest_tags}

        # 给每个视频打分
        scored: list[tuple[dict, float]] = []
        for v in self.videos:
            if v["video_id"] in watched:
                continue  # 已看过的不再推
            score = self._recommend_score(v, agent_id, tag_set)
            scored.append((v, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        # 80% 推荐 + 20% 关注
        followed = self.following.get(agent_id, set())
        followed_vids = [v for v in self.videos if v["author_id"] in followed and v["video_id"] not in watched]

        n_follow = max(1, int(limit * 0.2))
        n_rec = limit - n_follow

        selected: list[dict] = []
        seen: set[str] = set()

        # 关注的人的视频
        sample = self.rng.sample(followed_vids, min(n_follow, len(followed_vids))) if followed_vids else []
        for v in sample:
            selected.append(v)
            seen.add(v["video_id"])

        # 推荐视频
        for v, _ in scored:
            if len(selected) >= limit:
                break
            if v["video_id"] not in seen:
                selected.append(v)
                seen.add(v["video_id"])

        self.rng.shuffle(selected)
        return selected[:limit]

    def execute_action(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """执行 Agent 行为。

        支持: post, watch, like, comment, share, search, follow, browse, skip
        """
        action_type = action.get("type", "")
        handlers = {
            "post": self._action_post,
            "watch": self._action_watch,
            "like": self._action_like,
            "comment": self._action_comment,
            "share": self._action_share,
            "search": self._action_search,
            "follow": self._action_follow,
        }
        handler = handlers.get(action_type)
        if handler:
            return handler(agent_id, action)
        if action_type in ("browse", "skip"):
            return {"success": True, "action_type": action_type, "effect": "无"}
        return {"success": False, "error": f"未知行为类型: {action_type}"}

    def get_trending(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回热门视频（按推荐分数降序）。"""
        scored = [(v, self._recommend_score(v, "", set())) for v in self.videos]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [v for v, _ in scored[:limit]]

    def get_state_snapshot(self) -> dict[str, Any]:
        """获取平台状态快照。"""
        import copy
        return {
            "videos": copy.deepcopy(self.videos),
            "comments": copy.deepcopy(self.comments),
            "likes": {k: set(v) for k, v in self.likes.items()},
            "shares": copy.deepcopy(self.shares),
            "following": {k: set(v) for k, v in self.following.items()},
            "watch_history": copy.deepcopy(self.watch_history),
            "current_step": self.current_step,
        }

    def restore_state(self, snapshot: dict[str, Any]) -> None:
        """从快照恢复状态。"""
        import copy
        self.videos = copy.deepcopy(snapshot["videos"])
        self.comments = copy.deepcopy(snapshot["comments"])
        self.likes = {k: set(v) for k, v in snapshot["likes"].items()}
        self.shares = copy.deepcopy(snapshot.get("shares", {}))
        self.following = {k: set(v) for k, v in snapshot["following"].items()}
        self.watch_history = copy.deepcopy(snapshot.get("watch_history", {}))
        self.current_step = snapshot.get("current_step", 0)

    def get_metrics(self) -> dict[str, Any]:
        """返回平台关键指标。"""
        total_views = sum(v["views"] for v in self.videos)
        total_likes = sum(v["likes"] for v in self.videos)
        total_comments = sum(v["comments_count"] for v in self.videos)
        total_shares = sum(v["shares"] for v in self.videos)
        avg_completion = (
            sum(v["completion_rate"] for v in self.videos) / len(self.videos)
            if self.videos else 0
        )
        return {
            "total_videos": len(self.videos),
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "avg_completion_rate": round(avg_completion, 3),
        }

    # ──────────────── 私有辅助方法 ────────────────

    def _recommend_score(
        self,
        video: dict[str, Any],
        agent_id: str,
        interest_tags: set[str],
    ) -> float:
        """计算推荐分数。

        公式: 完播率*3 + log10(互动分+1) + 标签匹配*0.5 + 时间衰减
        """
        completion = video.get("completion_rate", 0.5) * 3.0

        views = max(video["views"], 1)
        like_rate = video["likes"] / views
        comment_rate = video["comments_count"] / views
        interaction = math.log10(
            video["likes"] * 2 + video["comments_count"] * 3 + video["shares"] * 4 + 1
        )

        # 标签匹配
        tag_match = 0.0
        if interest_tags:
            video_tags = {t.lower() for t in video.get("tags", [])}
            if interest_tags & video_tags:
                tag_match = 0.5

        # 时间衰减
        age = max(0, self.current_step - video.get("step", 0))
        time_decay = max(0.0, 1.0 - age * 0.02)  # 抖音衰减更快

        return completion + interaction + tag_match + time_decay

    def _action_post(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        video_id = self.add_video(
            content=action.get("content", ""),
            author_id=agent_id,
            title=action.get("title", ""),
            tags=action.get("tags", []),
            duration=action.get("duration", 30),
            step=self.current_step,
        )
        return {"success": True, "action_type": "post", "video_id": video_id,
                "effect": f"发布了短视频 {video_id}"}

    def _action_watch(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """观看视频，更新完播率。"""
        target_id = action.get("target_id", "")
        video = self._find_video(target_id)
        if not video:
            return {"success": False, "error": f"视频 {target_id} 不存在"}

        video["views"] += 1
        self.watch_history.setdefault(agent_id, []).append(target_id)

        # 模拟完播率变化（新观看与当前完播率加权平均）
        watch_pct = action.get("watch_percent", self.rng.uniform(0.3, 1.0))
        old_rate = video["completion_rate"]
        video["completion_rate"] = round(
            (old_rate * (video["views"] - 1) + watch_pct) / video["views"], 3
        )

        return {
            "success": True,
            "action_type": "watch",
            "video": video,
            "effect": f"观看了 {video['title'] or target_id}（完播{watch_pct:.0%}）",
        }

    def _action_like(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        video = self._find_video(target_id)
        if not video:
            return {"success": False, "error": f"视频 {target_id} 不存在"}
        if agent_id not in self.likes.get(target_id, set()):
            self.likes.setdefault(target_id, set()).add(agent_id)
            video["likes"] += 1
        return {"success": True, "action_type": "like", "target_id": target_id,
                "effect": f"点赞了 {target_id}"}

    def _action_comment(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        video = self._find_video(target_id)
        if not video:
            return {"success": False, "error": f"视频 {target_id} 不存在"}
        comment = {
            "comment_id": f"cmt_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "content": action.get("content", ""),
        }
        self.comments.setdefault(target_id, []).append(comment)
        video["comments_count"] += 1
        return {"success": True, "action_type": "comment",
                "comment_id": comment["comment_id"],
                "effect": f"在 {target_id} 下评论了"}

    def _action_share(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """分享/转发视频。"""
        target_id = action.get("target_id", "")
        video = self._find_video(target_id)
        if not video:
            return {"success": False, "error": f"视频 {target_id} 不存在"}
        record = {
            "share_id": f"sh_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "step": self.current_step,
        }
        self.shares.setdefault(target_id, []).append(record)
        video["shares"] += 1
        return {"success": True, "action_type": "share", "target_id": target_id,
                "effect": f"分享了 {target_id}"}

    def _action_search(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        query = action.get("query", "").lower()
        results = [
            v for v in self.videos
            if query in v["content"].lower() or query in v["title"].lower()
            or any(query in tag.lower() for tag in v.get("tags", []))
        ]
        results.sort(key=lambda v: self._recommend_score(v, agent_id, set()), reverse=True)
        return {
            "success": True,
            "action_type": "search",
            "query": query,
            "results": results[:10],
            "effect": f"搜索'{query}'，找到{len(results)}条视频",
        }

    def _action_follow(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action.get("target_id", "")
        self.following.setdefault(agent_id, set()).add(target_id)
        return {"success": True, "action_type": "follow", "target_id": target_id,
                "effect": f"关注了 {target_id}"}

    def _find_video(self, video_id: str) -> dict[str, Any] | None:
        for v in self.videos:
            if v["video_id"] == video_id:
                return v
        return None
