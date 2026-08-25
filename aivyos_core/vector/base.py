"""向量数据库基础抽象与 Mock 内存实现。"""

import hashlib
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class QueryResult:
    """向量查询结果。

    功能: 封装单条向量检索结果，包含文档 ID、原文、相似度得分与元数据。
    参数:
        id: 文档唯一标识符。
        text: 文档原始文本内容。
        score: 相似度得分，区间 [0, 1]，越接近 1 越相似。
        metadata: 文档关联的元数据字典。
    返回: 无（dataclass 实例）。
    异常: 无。
    """
    id: str
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


def _text_to_deterministic_vec(text: str, dim: int = 8) -> List[float]:
    """将文本转换为确定性向量（基于 SHA256 哈希，归一化到 [-1, 1]）。

    功能: 不依赖真实 LLM embedding，通过哈希生成固定维度的伪向量，
          保证相同文本始终得到相同向量，用于测试和降级场景。
    参数:
        text: 输入文本。
        dim: 向量维度，默认 8（轻量）。
    返回:
        List[float]: 长度为 dim 的向量，每个元素在 [-1.0, 1.0] 区间。
    异常: 无。
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    needed = dim * 4
    while len(digest) < needed:
        digest += hashlib.sha256(digest).digest()
    raw = digest[:needed]
    vec = []
    for i in range(dim):
        chunk = raw[i * 4 : (i + 1) * 4]
        u32 = int.from_bytes(chunk, "little", signed=False)
        normalized = (u32 / 0xFFFFFFFF) * 2.0 - 1.0
        vec.append(normalized)
    return vec


def _cosine(a: List[float], b: List[float]) -> float:
    """手写余弦相似度计算（零向量安全）。

    功能: 计算两个向量的余弦相似度，区间 [-1, 1]；零向量返回 0。
    参数:
        a: 向量 A。
        b: 向量 B。
    返回:
        float: 余弦相似度值。
    异常: 无。
    """
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(n):
        ai = a[i]
        bi = b[i]
        dot += ai * bi
        norm_a += ai * ai
        norm_b += bi * bi
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class VectorStore(ABC):
    """向量存储抽象基类（ABC）。

    功能: 定义向量数据库统一接口，支持 upsert、query、delete 及 embedding。
    参数: 无。
    返回: 无。
    异常: 无。
    """

    dim: int = 8

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """对文本列表生成嵌入向量。

        功能: 默认实现使用确定性哈希向量，避免依赖真实 LLM embedding。
              子类可覆盖以接入真实 embedding 模型。
        参数:
            texts: 待 embedding 的文本列表。
        返回:
            List[List[float]]: 与 texts 一一对应的向量列表。
        异常: 无。
        """
        return [_text_to_deterministic_vec(t, self.dim) for t in texts]

    @abstractmethod
    async def upsert_batch(self, items: List[Dict[str, Any]]) -> None:
        """批量 upsert（插入或覆盖）文档。

        功能: 将一批文档写入向量库，同 id 覆盖旧数据。
        参数:
            items: 文档列表，每个元素为 Dict，包含:
                - id (str): 文档唯一 ID。
                - text (str): 文档文本。
                - metadata (Dict[str, Any]): 元数据。
        返回: 无。
        异常:
            ValueError: 当 item 缺少必需字段时抛出。
        """
        ...

    @abstractmethod
    async def query(self, text: str, top_k: int = 5) -> List[QueryResult]:
        """按文本相似度查询。

        功能: 将 query 文本 embedding 后检索最相似的 top_k 条文档，
              按相似度降序排列，score 归一化到 [0, 1]。
        参数:
            text: 查询文本。
            top_k: 返回结果最大条数，默认 5。
        返回:
            List[QueryResult]: 相似度排序的查询结果列表。
        异常: 无。
        """
        ...

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """按 ID 删除文档。

        功能: 从向量库中删除指定 ID 的文档。
        参数:
            id: 文档 ID。
        返回:
            bool: True 表示成功删除，False 表示 ID 不存在。
        异常: 无。
        """
        ...


class MockInMemoryVectorStore(VectorStore):
    """内存 Mock 向量存储（纯 stdlib，无第三方依赖）。

    功能: 基于内存字典实现的轻量向量库，用于测试、离线降级或无 chroma 环境。
    参数: 无。
    返回: 无。
    异常: 无。
    """

    def __init__(self) -> None:
        """初始化 Mock 内存向量存储。

        功能: 创建三个内部字典分别保存向量、元数据与文本。
        参数: 无。
        返回: 无。
        异常: 无。
        """
        self.dim = 8
        self._embeds: Dict[str, List[float]] = {}
        self._metadatas: Dict[str, Dict[str, Any]] = {}
        self._texts: Dict[str, str] = {}

    async def upsert_batch(self, items: List[Dict[str, Any]]) -> None:
        """批量 upsert（插入或覆盖）文档。

        功能: 将文档写入/覆盖到三个内部字典中。
        参数:
            items: 文档列表，每项 {id, text, metadata}。
        返回: 无。
        异常:
            ValueError: 当 item 缺少 id 或 text 字段时抛出。
        """
        for item in items:
            if "id" not in item or "text" not in item:
                raise ValueError("upsert item 必须包含 'id' 和 'text' 字段")
            doc_id = str(item["id"])
            text = str(item["text"])
            meta = item.get("metadata", {}) or {}
            vec = _text_to_deterministic_vec(text, self.dim)
            self._embeds[doc_id] = vec
            self._texts[doc_id] = text
            self._metadatas[doc_id] = meta

    async def query(self, text: str, top_k: int = 5) -> List[QueryResult]:
        """按余弦相似度查询，返回 top_k。

        功能: 计算 query 文本向量，遍历所有文档算余弦相似度，
              归一到 [0,1] 后排序取前 top_k。
        参数:
            text: 查询文本。
            top_k: 返回条数上限，默认 5。
        返回:
            List[QueryResult]: 按 score 降序的结果列表，空库返回 []。
        异常: 无。
        """
        if not self._embeds:
            return []
        q_vec = _text_to_deterministic_vec(text, self.dim)
        scored = []
        for doc_id, doc_vec in self._embeds.items():
            cos = _cosine(q_vec, doc_vec)
            score = (cos + 1.0) / 2.0
            scored.append((doc_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]
        results = []
        for doc_id, score in top:
            results.append(QueryResult(
                id=doc_id,
                text=self._texts[doc_id],
                score=score,
                metadata=self._metadatas.get(doc_id, {}),
            ))
        return results

    async def delete(self, id: str) -> bool:
        """按 ID 删除文档。

        功能: 从三个内部字典中 pop 指定 ID。
        参数:
            id: 文档 ID。
        返回:
            bool: True 成功删除，False ID 不存在。
        异常: 无。
        """
        if id not in self._embeds:
            return False
        self._embeds.pop(id, None)
        self._texts.pop(id, None)
        self._metadatas.pop(id, None)
        return True
