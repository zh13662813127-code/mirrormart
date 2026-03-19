"""Chroma 向量数据库 — Agent 语义记忆存储。

功能:
- 将 Agent 记忆 embedding 存入 Chroma
- 语义检索: 给定当前感知内容，找到最相关的历史记忆
- 分支隔离: 每个分支使用独立的 collection（branch_{id}_{agent_id}）
- 优雅降级: 如果 Chroma 不可用，自动退回到列表记忆
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Chroma 是可选依赖，优雅降级
try:
    import chromadb
    from chromadb.config import Settings
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False
    logger.warning("chromadb 未安装，记忆检索将使用简单列表")


class ChromaMemoryStore:
    """基于 Chroma 的 Agent 语义记忆存储。

    每个 (branch_id, agent_id) 对应独立的 collection，确保分支隔离。
    """

    def __init__(
        self,
        persist_dir: str = ".chroma_data",
        branch_id: int = 0,
        agent_id: str = "",
    ) -> None:
        """初始化 Chroma 存储。

        Args:
            persist_dir: Chroma 数据持久化目录
            branch_id: 分支 ID（用于 collection 隔离）
            agent_id: Agent ID
        """
        self.available = _CHROMA_AVAILABLE
        self.branch_id = branch_id
        self.agent_id = agent_id
        self._collection_name = f"branch{branch_id}_{agent_id}".replace("-", "_")[:63]
        self._client: Any = None
        self._collection: Any = None

        if self.available:
            try:
                self._client = chromadb.PersistentClient(
                    path=persist_dir,
                    settings=Settings(anonymized_telemetry=False),
                )
                self._collection = self._client.get_or_create_collection(
                    name=self._collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.debug(
                    "ChromaMemoryStore 初始化: collection=%s", self._collection_name
                )
            except Exception as e:
                logger.warning("Chroma 初始化失败，降级到列表记忆: %s", e)
                self.available = False

    def add(self, memory: dict[str, Any], memory_id: str) -> None:
        """将记忆存入 Chroma。

        Args:
            memory: 记忆字典，必须包含 'summary' 字段
            memory_id: 记忆的唯一 ID（如 f"{agent_id}_{step}"）
        """
        if not self.available or self._collection is None:
            return

        text = memory.get("summary", str(memory))
        metadata = {
            "step": str(memory.get("step", 0)),
            "action_type": memory.get("action_type", ""),
            "platform": memory.get("platform", ""),
            "importance": str(memory.get("importance", 0.1)),
        }

        try:
            self._collection.upsert(
                ids=[memory_id],
                documents=[text],
                metadatas=[metadata],
            )
        except Exception as e:
            logger.warning("Chroma 写入失败: %s", e)

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """语义检索最相关记忆。

        Args:
            query: 查询文本（当前感知内容）
            n_results: 返回条数

        Returns:
            相关记忆文档列表，降级时返回空列表
        """
        if not self.available or self._collection is None:
            return []

        try:
            count = self._collection.count()
            if count == 0:
                return []

            results = self._collection.query(
                query_texts=[query],
                n_results=min(n_results, count),
                include=["documents", "metadatas", "distances"],
            )
            memories = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]

            for doc, meta, dist in zip(docs, metas, dists):
                memories.append({
                    "summary": doc,
                    "step": int(meta.get("step", 0)),
                    "action_type": meta.get("action_type", ""),
                    "platform": meta.get("platform", ""),
                    "importance": float(meta.get("importance", 0.1)),
                    "relevance": round(1.0 - float(dist), 3),
                })
            return memories

        except Exception as e:
            logger.warning("Chroma 检索失败: %s", e)
            return []

    def delete_collection(self) -> None:
        """删除当前 collection（分支结束时清理）。"""
        if not self.available or self._client is None:
            return
        try:
            self._client.delete_collection(self._collection_name)
        except Exception as e:
            logger.debug("Chroma collection 删除失败（可能已不存在）: %s", e)

    @staticmethod
    def is_available() -> bool:
        """检查 Chroma 是否可用。"""
        return _CHROMA_AVAILABLE
