"""淘宝平台环境（增强版）。

核心规则:
- 搜索结果 = 关键词匹配 × 销量权重 × 评分权重 × 用户偏好权重
- 推荐 = 基于购买+收藏历史的品类偏好
- 新增: 收藏夹(wishlist)、问答(ask_question)
"""

from __future__ import annotations

import math
import random
import uuid
from typing import Any

from mirrormart.platforms.base import PlatformBase


class TaobaoEnvironment(PlatformBase):
    """淘宝环境（增强版）。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        """初始化淘宝环境。

        Args:
            rng: 随机数生成器
        """
        self.rng = rng or random.Random()
        self.products: list[dict[str, Any]] = []
        self.reviews: dict[str, list[dict]] = {}     # product_id → reviews
        self.purchases: dict[str, list[dict]] = {}   # agent_id → [purchase_records]
        self.carts: dict[str, list[str]] = {}        # agent_id → [product_ids]
        self.view_history: dict[str, list[str]] = {} # agent_id → [product_ids]
        self.wishlists: dict[str, set[str]] = {}     # agent_id → {product_ids}
        self.questions: dict[str, list[dict]] = {}   # product_id → [questions]

    # ──────────────── 初始化方法 ────────────────

    def add_product(
        self,
        product_id: str,
        name: str,
        price: float,
        category: str,
        description: str = "",
        key_ingredients: list[str] | None = None,
        selling_points: list[str] | None = None,
        initial_sales: int = 0,
        initial_rating: float = 4.5,
        initial_reviews: int = 0,
    ) -> None:
        """添加商品（用于场景初始化）。"""
        self.products.append({
            "product_id": product_id,
            "name": name,
            "price": price,
            "category": category,
            "description": description,
            "key_ingredients": key_ingredients or [],
            "selling_points": selling_points or [],
            "sales": initial_sales,
            "rating": initial_rating,
            "review_count": initial_reviews,
        })
        self.reviews[product_id] = []
        self.questions[product_id] = []

    # ──────────────── PlatformBase 实现 ────────────────

    def get_feed(
        self,
        agent_id: str,
        query: str | None = None,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """获取商品列表。

        有 query 时为搜索结果（关键词匹配 × 销量 × 评分 × 用户偏好排序）；
        无 query 时基于购买+收藏历史推荐。
        """
        if query:
            return self._search(query, limit, agent_id=agent_id)
        return self._recommend(agent_id, limit)

    def execute_action(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """执行 Agent 行为。

        支持: search, view, add_cart, purchase, review, compare, wishlist, ask_question
        """
        t = action.get("type", "")
        handlers: dict[str, Any] = {
            "search": lambda: self._action_search(agent_id, action),
            "view": lambda: self._action_view(agent_id, action),
            "add_cart": lambda: self._action_add_cart(agent_id, action),
            "purchase": lambda: self._action_purchase(agent_id, action),
            "review": lambda: self._action_review(agent_id, action),
            "compare": lambda: self._action_compare(action),
            "wishlist": lambda: self._action_wishlist(agent_id, action),
            "ask_question": lambda: self._action_ask_question(agent_id, action),
        }
        handler = handlers.get(t)
        if handler:
            return handler()
        if t in ("browse", "skip"):
            return {"success": True, "action_type": t, "effect": "无"}
        return {"success": False, "error": f"未知行为类型: {t}"}

    def get_state_snapshot(self) -> dict[str, Any]:
        """获取平台状态快照。"""
        import copy
        return {
            "products": copy.deepcopy(self.products),
            "reviews": copy.deepcopy(self.reviews),
            "purchases": copy.deepcopy(self.purchases),
            "carts": copy.deepcopy(self.carts),
            "view_history": copy.deepcopy(self.view_history),
            "wishlists": {k: set(v) for k, v in self.wishlists.items()},
            "questions": copy.deepcopy(self.questions),
        }

    def restore_state(self, snapshot: dict[str, Any]) -> None:
        """从快照恢复状态。"""
        import copy
        self.products = copy.deepcopy(snapshot["products"])
        self.reviews = copy.deepcopy(snapshot["reviews"])
        self.purchases = copy.deepcopy(snapshot["purchases"])
        self.carts = copy.deepcopy(snapshot["carts"])
        self.view_history = copy.deepcopy(snapshot["view_history"])
        self.wishlists = {k: set(v) for k, v in snapshot.get("wishlists", {}).items()}
        self.questions = copy.deepcopy(snapshot.get("questions", {}))

    def get_metrics(self) -> dict[str, Any]:
        """返回平台关键指标。"""
        total_purchases = sum(len(v) for v in self.purchases.values())
        total_revenue = sum(
            r["price"] for records in self.purchases.values() for r in records
        )
        conversion_by_product: dict[str, int] = {}
        for records in self.purchases.values():
            for r in records:
                pid = r["product_id"]
                conversion_by_product[pid] = conversion_by_product.get(pid, 0) + 1
        total_wishlist = sum(len(v) for v in self.wishlists.values())
        total_questions = sum(len(v) for v in self.questions.values())
        return {
            "total_purchases": total_purchases,
            "total_revenue": total_revenue,
            "conversion_by_product": conversion_by_product,
            "cart_count": sum(len(v) for v in self.carts.values()),
            "total_wishlist": total_wishlist,
            "total_questions": total_questions,
        }

    # ──────────────── 私有辅助方法 ────────────────

    def _get_category_preferences(self, agent_id: str) -> dict[str, float]:
        """基于购买+收藏历史计算品类偏好权重。"""
        prefs: dict[str, float] = {}
        # 购买记录权重 = 2
        for record in self.purchases.get(agent_id, []):
            product = self._find_product(record["product_id"])
            if product:
                cat = product["category"]
                prefs[cat] = prefs.get(cat, 0) + 2.0
        # 收藏权重 = 1
        for pid in self.wishlists.get(agent_id, set()):
            product = self._find_product(pid)
            if product:
                cat = product["category"]
                prefs[cat] = prefs.get(cat, 0) + 1.0
        # 浏览权重 = 0.3
        for pid in self.view_history.get(agent_id, []):
            product = self._find_product(pid)
            if product:
                cat = product["category"]
                prefs[cat] = prefs.get(cat, 0) + 0.3
        return prefs

    def _search_score(
        self,
        product: dict[str, Any],
        query: str,
        prefs: dict[str, float] | None = None,
    ) -> float:
        """计算搜索综合得分 = 相关性 × 销量 × 评分 × 用户偏好。"""
        q = query.lower()
        text = (
            product["name"].lower()
            + " " + product.get("description", "").lower()
            + " " + " ".join(product.get("key_ingredients", [])).lower()
            + " " + product.get("category", "").lower()
        )
        relevance = 1.0 if q in text else 0.3

        # log 压缩销量（避免大销量商品碾压一切）
        sales_weight = math.log1p(product.get("sales", 0)) / 10.0
        rating_weight = product.get("rating", 4.0) / 5.0

        # 用户偏好加成
        pref_boost = 1.0
        if prefs:
            cat = product.get("category", "")
            pref_boost = 1.0 + min(prefs.get(cat, 0) * 0.1, 0.5)

        return relevance * (1 + sales_weight) * rating_weight * pref_boost

    def _search(
        self,
        query: str,
        limit: int = 10,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.products:
            return []
        prefs = self._get_category_preferences(agent_id) if agent_id else None
        scored = [(p, self._search_score(p, query, prefs)) for p in self.products]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in scored[:limit]]

    def _recommend(self, agent_id: str, limit: int) -> list[dict[str, Any]]:
        """基于购买+收藏历史推荐，未有历史时返回销量榜。"""
        prefs = self._get_category_preferences(agent_id)
        if not prefs:
            return sorted(self.products, key=lambda p: p["sales"], reverse=True)[:limit]

        # 按品类偏好加权排序，已看过的排后面
        viewed_ids = set(self.view_history.get(agent_id, []))

        def _score(p: dict[str, Any]) -> float:
            cat_weight = prefs.get(p["category"], 0)
            seen_penalty = 0.5 if p["product_id"] in viewed_ids else 1.0
            return (1.0 + cat_weight * 0.2) * seen_penalty * math.log1p(p["sales"])

        return sorted(self.products, key=_score, reverse=True)[:limit]

    def _action_search(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        results = self._search(action.get("query", ""), agent_id=agent_id)
        return {"success": True, "action_type": "search",
                "results": results,
                "effect": f"搜索'{action.get('query', '')}',找到{len(results)}件商品"}

    def _action_view(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        product_id = action.get("target_id", "")
        product = self._find_product(product_id)
        if not product:
            return {"success": False, "error": f"商品 {product_id} 不存在"}
        self.view_history.setdefault(agent_id, []).append(product_id)
        return {
            "success": True,
            "action_type": "view",
            "product": {
                **product,
                "reviews": self.reviews.get(product_id, [])[:5],
                "questions": self.questions.get(product_id, [])[:5],
            },
            "effect": f"查看了商品 {product['name']}",
        }

    def _action_add_cart(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        product_id = action.get("target_id", "")
        product = self._find_product(product_id)
        if not product:
            return {"success": False, "error": f"商品 {product_id} 不存在"}
        self.carts.setdefault(agent_id, []).append(product_id)
        return {"success": True, "action_type": "add_cart", "target_id": product_id,
                "effect": f"加购了 {product['name']}"}

    def _action_purchase(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        product_id = action.get("target_id", "")
        product = self._find_product(product_id)
        if not product:
            return {"success": False, "error": f"商品 {product_id} 不存在"}
        record = {
            "order_id": f"order_{uuid.uuid4().hex[:8]}",
            "product_id": product_id,
            "product_name": product["name"],
            "price": product["price"],
        }
        self.purchases.setdefault(agent_id, []).append(record)
        product["sales"] += 1
        # 从购物车移除
        cart = self.carts.get(agent_id, [])
        if product_id in cart:
            cart.remove(product_id)
        return {"success": True, "action_type": "purchase",
                "order_id": record["order_id"],
                "effect": f"购买了 {product['name']}（¥{product['price']}）"}

    def _action_review(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        product_id = action.get("target_id", "")
        product = self._find_product(product_id)
        if not product:
            return {"success": False, "error": f"商品 {product_id} 不存在"}
        rating = max(1, min(5, action.get("rating", 5)))
        review = {
            "review_id": f"rev_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "content": action.get("content", ""),
            "rating": rating,
        }
        self.reviews.setdefault(product_id, []).append(review)
        product["review_count"] += 1
        # 重新计算平均评分
        all_ratings = [r["rating"] for r in self.reviews[product_id]]
        product["rating"] = round(sum(all_ratings) / len(all_ratings), 1)
        return {"success": True, "action_type": "review",
                "effect": f"给 {product['name']} 写了{rating}星评价"}

    def _action_compare(self, action: dict[str, Any]) -> dict[str, Any]:
        product_ids: list[str] = action.get("product_ids", [])
        products = [p for p in self.products if p["product_id"] in product_ids]
        return {
            "success": True,
            "action_type": "compare",
            "products": products,
            "effect": f"比较了{len(products)}件商品",
        }

    def _action_wishlist(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """收藏商品到收藏夹。"""
        product_id = action.get("target_id", "")
        product = self._find_product(product_id)
        if not product:
            return {"success": False, "error": f"商品 {product_id} 不存在"}
        self.wishlists.setdefault(agent_id, set()).add(product_id)
        return {"success": True, "action_type": "wishlist", "target_id": product_id,
                "effect": f"收藏了 {product['name']}"}

    def _action_ask_question(self, agent_id: str, action: dict[str, Any]) -> dict[str, Any]:
        """向商品提问。"""
        product_id = action.get("target_id", "")
        product = self._find_product(product_id)
        if not product:
            return {"success": False, "error": f"商品 {product_id} 不存在"}
        question = {
            "question_id": f"q_{uuid.uuid4().hex[:8]}",
            "author_id": agent_id,
            "content": action.get("content", ""),
        }
        self.questions.setdefault(product_id, []).append(question)
        return {"success": True, "action_type": "ask_question",
                "question_id": question["question_id"],
                "effect": f"向 {product['name']} 提问: {action.get('content', '')[:30]}"}

    def _find_product(self, product_id: str) -> dict[str, Any] | None:
        for p in self.products:
            if p["product_id"] == product_id:
                return p
        return None
