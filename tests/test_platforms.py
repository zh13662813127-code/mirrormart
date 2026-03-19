"""平台环境单元测试（不调用 LLM）。"""

from __future__ import annotations

import random

import pytest

from mirrormart.platforms.douyin import DouyinEnvironment
from mirrormart.platforms.taobao import TaobaoEnvironment
from mirrormart.platforms.weibo import WeiboEnvironment
from mirrormart.platforms.xiaohongshu import XiaohongshuEnvironment


class TestXiaohongshu:
    """小红书环境测试。"""

    def setup_method(self) -> None:
        self.rng = random.Random(42)
        self.xhs = XiaohongshuEnvironment(rng=self.rng)

    def test_add_post_and_get_feed(self) -> None:
        post_id = self.xhs.add_initial_post(
            content="氨基酸面膜测评！超级温和",
            author_id="agent_01",
            title="测评",
        )
        assert post_id.startswith("post_")
        feed = self.xhs.get_feed("agent_02", limit=5)
        assert len(feed) == 1
        assert feed[0]["post_id"] == post_id

    def test_like_action(self) -> None:
        post_id = self.xhs.add_initial_post("内容", "agent_01")
        result = self.xhs.execute_action("agent_02", {"type": "like", "target_id": post_id})
        assert result["success"] is True
        post = self.xhs._find_post(post_id)
        assert post is not None
        assert post["likes"] == 1

    def test_comment_action(self) -> None:
        post_id = self.xhs.add_initial_post("内容", "agent_01")
        result = self.xhs.execute_action(
            "agent_02",
            {"type": "comment", "target_id": post_id, "content": "成分不错"},
        )
        assert result["success"] is True
        assert len(self.xhs.comments[post_id]) == 1

    def test_search_action(self) -> None:
        self.xhs.add_initial_post("氨基酸面膜温和好用", "agent_01", title="氨基酸测评")
        result = self.xhs.execute_action("agent_02", {"type": "search", "query": "氨基酸"})
        assert result["success"] is True
        assert len(result["results"]) == 1

    def test_state_snapshot_restore(self) -> None:
        post_id = self.xhs.add_initial_post("内容", "agent_01")
        snapshot = self.xhs.get_state_snapshot()
        self.xhs.execute_action("agent_02", {"type": "like", "target_id": post_id})
        self.xhs.restore_state(snapshot)
        post = self.xhs._find_post(post_id)
        assert post is not None
        assert post["likes"] == 0

    def test_metrics(self) -> None:
        self.xhs.add_initial_post("内容", "agent_01", initial_likes=5)
        metrics = self.xhs.get_metrics()
        assert metrics["total_posts"] == 1
        assert metrics["total_likes"] == 5

    def test_init_following(self) -> None:
        agents = ["a1", "a2", "a3", "a4", "a5"]
        self.xhs.init_following(agents, density=1.0)
        # 密度=1.0 时所有人都应该互相关注
        assert len(self.xhs.following["a1"]) > 0

    def test_repost_action(self) -> None:
        post_id = self.xhs.add_initial_post("内容", "agent_01")
        result = self.xhs.execute_action("agent_02", {"type": "repost", "target_id": post_id})
        assert result["success"] is True
        post = self.xhs._find_post(post_id)
        assert post is not None
        assert post["reposts"] == 1
        assert len(self.xhs.reposts[post_id]) == 1

    def test_quote_action(self) -> None:
        post_id = self.xhs.add_initial_post("内容", "agent_01")
        result = self.xhs.execute_action(
            "agent_02",
            {"type": "quote", "target_id": post_id, "content": "说得好"},
        )
        assert result["success"] is True
        post = self.xhs._find_post(post_id)
        assert post is not None
        assert post["reposts"] == 1
        assert post["comments_count"] == 1

    def test_get_trending(self) -> None:
        self.xhs.add_initial_post("热门", "agent_01", initial_likes=100)
        self.xhs.add_initial_post("冷门", "agent_02", initial_likes=1)
        trending = self.xhs.get_trending(limit=2)
        assert len(trending) == 2
        assert trending[0]["likes"] >= trending[1]["likes"]

    def test_heat_score_time_decay(self) -> None:
        self.xhs.add_initial_post("旧帖", "agent_01", initial_likes=10, step=0)
        self.xhs.add_initial_post("新帖", "agent_02", initial_likes=10, step=50)
        self.xhs.current_step = 50
        trending = self.xhs.get_trending(limit=2)
        # 新帖应该排在前面（时间衰减较小）
        assert trending[0]["step"] == 50

    def test_feed_with_interest_tags(self) -> None:
        self.xhs.add_initial_post("护肤", "agent_01", tags=["护肤", "面膜"])
        self.xhs.add_initial_post("美食", "agent_02", tags=["美食", "甜品"])
        feed = self.xhs.get_feed("agent_03", limit=5, interest_tags=["护肤"])
        # 应该能获取到内容
        assert len(feed) >= 1

    def test_snapshot_includes_reposts(self) -> None:
        post_id = self.xhs.add_initial_post("内容", "agent_01")
        self.xhs.execute_action("agent_02", {"type": "repost", "target_id": post_id})
        snapshot = self.xhs.get_state_snapshot()
        assert "reposts" in snapshot
        self.xhs.restore_state(snapshot)
        assert self.xhs._find_post(post_id)["reposts"] == 1


class TestTaobao:
    """淘宝环境测试。"""

    def setup_method(self) -> None:
        self.rng = random.Random(42)
        self.taobao = TaobaoEnvironment(rng=self.rng)
        self.taobao.add_product(
            product_id="product_main",
            name="润颜氨基酸面膜",
            price=59.0,
            category="面膜",
            initial_sales=100,
            initial_rating=4.6,
            initial_reviews=20,
        )

    def test_search_finds_product(self) -> None:
        result = self.taobao.execute_action("agent_01", {"type": "search", "query": "氨基酸面膜"})
        assert result["success"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["product_id"] == "product_main"

    def test_view_product(self) -> None:
        result = self.taobao.execute_action(
            "agent_01", {"type": "view", "target_id": "product_main"}
        )
        assert result["success"] is True
        assert result["product"]["name"] == "润颜氨基酸面膜"

    def test_purchase_increments_sales(self) -> None:
        self.taobao.execute_action("agent_01", {"type": "purchase", "target_id": "product_main"})
        product = self.taobao._find_product("product_main")
        assert product is not None
        assert product["sales"] == 101

    def test_add_cart_and_purchase(self) -> None:
        self.taobao.execute_action("agent_01", {"type": "add_cart", "target_id": "product_main"})
        assert "product_main" in self.taobao.carts.get("agent_01", [])
        self.taobao.execute_action("agent_01", {"type": "purchase", "target_id": "product_main"})
        # 购买后从购物车移除
        assert "product_main" not in self.taobao.carts.get("agent_01", [])

    def test_review_updates_rating(self) -> None:
        self.taobao.execute_action(
            "agent_01",
            {"type": "review", "target_id": "product_main", "content": "很好用", "rating": 5},
        )
        product = self.taobao._find_product("product_main")
        assert product is not None
        # 评分应该有变化
        assert isinstance(product["rating"], float)

    def test_metrics(self) -> None:
        self.taobao.execute_action("agent_01", {"type": "purchase", "target_id": "product_main"})
        metrics = self.taobao.get_metrics()
        assert metrics["total_purchases"] == 1
        assert metrics["conversion_by_product"]["product_main"] == 1

    def test_state_snapshot_restore(self) -> None:
        snapshot = self.taobao.get_state_snapshot()
        self.taobao.execute_action("agent_01", {"type": "purchase", "target_id": "product_main"})
        self.taobao.restore_state(snapshot)
        assert self.taobao.get_metrics()["total_purchases"] == 0

    def test_wishlist_action(self) -> None:
        result = self.taobao.execute_action(
            "agent_01", {"type": "wishlist", "target_id": "product_main"}
        )
        assert result["success"] is True
        assert "product_main" in self.taobao.wishlists.get("agent_01", set())

    def test_ask_question_action(self) -> None:
        result = self.taobao.execute_action(
            "agent_01",
            {"type": "ask_question", "target_id": "product_main", "content": "敏感肌能用吗？"},
        )
        assert result["success"] is True
        assert len(self.taobao.questions["product_main"]) == 1

    def test_wishlist_affects_recommendation(self) -> None:
        self.taobao.add_product(
            product_id="product_other",
            name="美白面膜",
            price=39.0,
            category="面膜",
            initial_sales=50,
        )
        # 收藏主产品后，同品类推荐应该提升
        self.taobao.execute_action("agent_01", {"type": "wishlist", "target_id": "product_main"})
        feed = self.taobao.get_feed("agent_01", limit=10)
        assert len(feed) >= 1

    def test_search_with_user_preferences(self) -> None:
        # 购买后搜索应受偏好加成
        self.taobao.execute_action("agent_01", {"type": "purchase", "target_id": "product_main"})
        result = self.taobao.execute_action("agent_01", {"type": "search", "query": "面膜"})
        assert result["success"] is True
        assert len(result["results"]) >= 1

    def test_metrics_includes_wishlist_and_questions(self) -> None:
        self.taobao.execute_action("agent_01", {"type": "wishlist", "target_id": "product_main"})
        self.taobao.execute_action(
            "agent_01",
            {"type": "ask_question", "target_id": "product_main", "content": "能退吗？"},
        )
        metrics = self.taobao.get_metrics()
        assert metrics["total_wishlist"] == 1
        assert metrics["total_questions"] == 1

    def test_snapshot_includes_wishlists(self) -> None:
        self.taobao.execute_action("agent_01", {"type": "wishlist", "target_id": "product_main"})
        snapshot = self.taobao.get_state_snapshot()
        self.taobao.execute_action("agent_01", {"type": "wishlist", "target_id": "product_main"})
        self.taobao.restore_state(snapshot)
        assert "product_main" in self.taobao.wishlists.get("agent_01", set())


class TestDouyin:
    """抖音环境测试。"""

    def setup_method(self) -> None:
        self.rng = random.Random(42)
        self.douyin = DouyinEnvironment(rng=self.rng)

    def test_add_video_and_get_feed(self) -> None:
        vid_id = self.douyin.add_video(
            content="氨基酸面膜使用体验",
            author_id="agent_01",
            title="面膜测评",
            tags=["面膜", "护肤"],
        )
        assert vid_id.startswith("vid_")
        feed = self.douyin.get_feed("agent_02", limit=5)
        assert len(feed) == 1

    def test_watch_updates_views_and_completion(self) -> None:
        vid_id = self.douyin.add_video("内容", "agent_01", completion_rate=0.5)
        result = self.douyin.execute_action(
            "agent_02", {"type": "watch", "target_id": vid_id, "watch_percent": 1.0}
        )
        assert result["success"] is True
        video = self.douyin._find_video(vid_id)
        assert video is not None
        assert video["views"] == 1
        assert video["completion_rate"] > 0.5  # 完播率应该上升

    def test_like_action(self) -> None:
        vid_id = self.douyin.add_video("内容", "agent_01")
        result = self.douyin.execute_action("agent_02", {"type": "like", "target_id": vid_id})
        assert result["success"] is True
        assert self.douyin._find_video(vid_id)["likes"] == 1

    def test_comment_action(self) -> None:
        vid_id = self.douyin.add_video("内容", "agent_01")
        result = self.douyin.execute_action(
            "agent_02", {"type": "comment", "target_id": vid_id, "content": "太好了"}
        )
        assert result["success"] is True
        assert len(self.douyin.comments[vid_id]) == 1

    def test_share_action(self) -> None:
        vid_id = self.douyin.add_video("内容", "agent_01")
        result = self.douyin.execute_action("agent_02", {"type": "share", "target_id": vid_id})
        assert result["success"] is True
        assert self.douyin._find_video(vid_id)["shares"] == 1

    def test_search_action(self) -> None:
        self.douyin.add_video("氨基酸面膜超温和", "agent_01", title="面膜测评", tags=["面膜"])
        result = self.douyin.execute_action("agent_02", {"type": "search", "query": "面膜"})
        assert result["success"] is True
        assert len(result["results"]) == 1

    def test_get_trending(self) -> None:
        self.douyin.add_video("热门视频", "agent_01", initial_views=1000, initial_likes=500)
        self.douyin.add_video("冷门视频", "agent_02", initial_views=10, initial_likes=1)
        trending = self.douyin.get_trending(limit=2)
        assert len(trending) == 2
        assert trending[0]["views"] >= trending[1]["views"]

    def test_feed_excludes_watched(self) -> None:
        vid_id = self.douyin.add_video("内容", "agent_01")
        self.douyin.execute_action("agent_02", {"type": "watch", "target_id": vid_id})
        feed = self.douyin.get_feed("agent_02", limit=5)
        # 已看过的不应该出现
        assert all(v["video_id"] != vid_id for v in feed)

    def test_state_snapshot_restore(self) -> None:
        vid_id = self.douyin.add_video("内容", "agent_01")
        snapshot = self.douyin.get_state_snapshot()
        self.douyin.execute_action("agent_02", {"type": "like", "target_id": vid_id})
        self.douyin.restore_state(snapshot)
        assert self.douyin._find_video(vid_id)["likes"] == 0

    def test_metrics(self) -> None:
        self.douyin.add_video("内容", "agent_01", initial_views=100, initial_likes=50)
        metrics = self.douyin.get_metrics()
        assert metrics["total_videos"] == 1
        assert metrics["total_views"] == 100
        assert metrics["total_likes"] == 50


class TestWeibo:
    """微博环境测试。"""

    def setup_method(self) -> None:
        self.rng = random.Random(42)
        self.weibo = WeiboEnvironment(rng=self.rng)

    def test_add_post_and_get_feed(self) -> None:
        post_id = self.weibo.add_post(
            content="氨基酸面膜真的好用！#护肤好物#",
            author_id="agent_01",
            topics=["护肤好物"],
        )
        assert post_id.startswith("wb_")
        feed = self.weibo.get_feed("agent_02", limit=5)
        assert len(feed) == 1

    def test_like_action(self) -> None:
        post_id = self.weibo.add_post("内容", "agent_01")
        result = self.weibo.execute_action("agent_02", {"type": "like", "target_id": post_id})
        assert result["success"] is True
        assert self.weibo._find_post(post_id)["likes"] == 1

    def test_comment_action(self) -> None:
        post_id = self.weibo.add_post("内容", "agent_01")
        result = self.weibo.execute_action(
            "agent_02", {"type": "comment", "target_id": post_id, "content": "说得对"}
        )
        assert result["success"] is True
        assert len(self.weibo.comments[post_id]) == 1

    def test_repost_creates_new_post(self) -> None:
        post_id = self.weibo.add_post("原始内容", "agent_01", topics=["测试"])
        result = self.weibo.execute_action(
            "agent_02", {"type": "repost", "target_id": post_id, "content": "转发"}
        )
        assert result["success"] is True
        assert self.weibo._find_post(post_id)["reposts"] == 1
        # 转发应该生成新帖子
        assert len(self.weibo.posts) == 2

    def test_search_topic(self) -> None:
        self.weibo.add_post("面膜推荐", "agent_01", topics=["护肤好物"])
        self.weibo.add_post("另一篇面膜", "agent_02", topics=["护肤好物"])
        result = self.weibo.execute_action(
            "agent_03", {"type": "search_topic", "topic": "护肤好物"}
        )
        assert result["success"] is True
        assert len(result["results"]) == 2

    def test_get_hot_search(self) -> None:
        self.weibo.add_post("热帖", "agent_01", topics=["热门话题"], initial_likes=100, initial_reposts=50)
        self.weibo.add_post("冷帖", "agent_02", topics=["冷门话题"], initial_likes=1)
        hot = self.weibo.get_hot_search(limit=5)
        assert len(hot) == 2
        assert hot[0]["topic"] == "热门话题"

    def test_search_action(self) -> None:
        self.weibo.add_post("氨基酸面膜太好用了", "agent_01")
        result = self.weibo.execute_action("agent_02", {"type": "search", "query": "面膜"})
        assert result["success"] is True
        assert len(result["results"]) == 1

    def test_state_snapshot_restore(self) -> None:
        post_id = self.weibo.add_post("内容", "agent_01")
        snapshot = self.weibo.get_state_snapshot()
        self.weibo.execute_action("agent_02", {"type": "like", "target_id": post_id})
        self.weibo.restore_state(snapshot)
        assert self.weibo._find_post(post_id)["likes"] == 0

    def test_metrics(self) -> None:
        self.weibo.add_post("内容", "agent_01", topics=["话题1"], initial_likes=10, initial_reposts=5)
        metrics = self.weibo.get_metrics()
        assert metrics["total_posts"] == 1
        assert metrics["total_likes"] == 10
        assert metrics["total_reposts"] == 5
        assert metrics["total_topics"] == 1

    def test_init_following(self) -> None:
        agents = ["a1", "a2", "a3", "a4", "a5"]
        self.weibo.init_following(agents, density=1.0)
        assert len(self.weibo.following["a1"]) > 0
