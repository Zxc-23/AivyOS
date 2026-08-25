"""ChromaDB 向量存储实现（可选依赖，未安装时降级）。"""

from typing import Any, Dict, List, Optional

try:
    import chromadb  # type: ignore
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False

from .base import QueryResult, VectorStore, _text_to_deterministic_vec


class ChromaVectorStore(VectorStore):
    """基于 ChromaDB 的向量存储实现。

    功能: 封装 ChromaDB 客户端，支持内存模式与持久化模式，
          embedding 默认用确定性哈希（mock），避免强依赖 LLM。
    参数:
        collection_name: Chroma collection 名称，默认 "aivyos_knowledge"。
        in_memory: 是否使用内存模式（EphemeralClient），默认 True。
        persist_dir: 持久化目录，仅 in_memory=False 时生效，默认 None。
    返回: 无。
    异常:
        RuntimeError: 当 chromadb 未安装时抛出。
    """

    def __init__(
        self,
        collection_name: str = "aivyos_knowledge",
        in_memory: bool = True,
        persist_dir: Optional[str] = None,
    ) -> None:
        """初始化 Chroma 向量存储。

        功能: 创建 Chroma 客户端并获取或创建 collection。
        参数:
            collection_name: collection 名称，默认 "aivyos_knowledge"。
            in_memory: True 用 EphemeralClient，False 用 PersistentClient。
            persist_dir: PersistentClient 的数据目录路径。
        返回: 无。
        异常:
            RuntimeError: chromadb 未安装。
        """
        if not _CHROMA_AVAILABLE:
            raise RuntimeError("chroma 未安装")
        self.dim = 8
        self._collection_name = collection_name
        self._in_memory = in_memory
        self._persist_dir = persist_dir
        if in_memory:
            self._client = chromadb.EphemeralClient()
        else:
            self._client = chromadb.PersistentClient(path=persist_dir)
        self.col = self._client.get_or_create_collection(name=collection_name)

    async def upsert_batch(self, items: List[Dict[str, Any]]) -> None:
        """批量 upsert 文档到 Chroma。

        功能: 对每个文本生成确定性哈希向量，调用 col.add 写入 Chroma。
        参数:
            items: 文档列表 {id:str, text:str, metadata:Dict}。
        返回: 无。
        异常:
            ValueError: item 缺少 id 或 text。
        """
        if not items:
            return
        ids: List[str] = []
        texts: List[str] = []
        metas: List[Dict[str, Any]] = []
        embs: List[List[float]] = []
        for item in items:
            if "id" not in item or "text" not in item:
                raise ValueError("upsert item 必须包含 'id' 和 'text' 字段")
            doc_id = str(item["id"])
            text = str(item["text"])
            meta = item.get("metadata", {}) or {}
            vec = _text_to_deterministic_vec(text, self.dim)
            ids.append(doc_id)
            texts.append(text)
            metas.append(meta)
            embs.append(vec)
        self.col.add(
            ids=ids,
            embeddings=embs,
            documents=texts,
            metadatas=metas,
        )

    async def query(self, text: str, top_k: int = 5) -> List[QueryResult]:
        """按文本相似度查询 Chroma。

        功能: 将 query 转向量后 col.query，Chroma 返回 L2 distance，
              通过 1/(1+d) 归一化到 [0,1] 作为 score。
        参数:
            text: 查询文本。
            top_k: 返回条数上限，默认 5。
        返回:
            List[QueryResult]: 排序后的结果列表。
        异常: 无。
        """
        vec = _text_to_deterministic_vec(text, self.dim)
        result = self.col.query(
            query_embeddings=[vec],
            n_results=top_k,
        )
        ids_list = result.get("ids", [[]])[0] if result.get("ids") else []
        dists_list = result.get("distances", [[]])[0] if result.get("distances") else []
        docs_list = result.get("documents", [[]])[0] if result.get("documents") else []
        metas_list = result.get("metadatas", [[]])[0] if result.get("metadatas") else []
        out: List[QueryResult] = []
        for i, doc_id in enumerate(ids_list):
            dist = float(dists_list[i]) if i < len(dists_list) else 0.0
            score = 1.0 / (1.0 + dist)
            doc_text = docs_list[i] if i < len(docs_list) else ""
            doc_meta = metas_list[i] if i < len(metas_list) else {}
            out.append(QueryResult(
                id=str(doc_id),
                text=str(doc_text),
                score=score,
                metadata=doc_meta or {},
            ))
        return out

    async def delete(self, id: str) -> bool:
        """按 ID 从 Chroma 删除文档。

        功能: 先检查 ID 是否存在于 collection 中，存在则 delete 并返回 True。
        参数:
            id: 文档 ID。
        返回:
            bool: True 删除成功，False ID 不存在。
        异常: 无。
        """
        try:
            get_res = self.col.get(ids=[id], include=[])
            existing = get_res.get("ids", [])
            if not existing:
                return False
            self.col.delete(ids=[id])
            return True
        except Exception:
            return False
