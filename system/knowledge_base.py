"""
知识库引擎：用微调后的Embedding模型 + ChromaDB 构建企业知识库

完整链路：
  文档 → 切段落 → Embedding编码 → 存入向量库 → 检索 → Reranker重排 → 返回结果
"""
import os
import json
import argparse
import logging
import numpy as np
from typing import List, Optional

# 限制 HF Hub 下载超时（避免启动时长时间卡住）
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "15")

# 屏蔽 bge 模型加载时的无关警告和 LOAD REPORT
logging.getLogger("transformers.modeling_utils").setLevel(logging.ERROR)
logging.getLogger("transformers.configuration_utils").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers.model_card").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

# ===== ChromaDB（轻量级向量库，零配置）=====
import chromadb
from chromadb.config import Settings

# ===== 模型 =====
from sentence_transformers import SentenceTransformer, CrossEncoder

# ===================================================================
# 配置（优先使用系统 config，降级为默认值）
# ===================================================================
try:
    from .config import EMBEDDING_MODEL_PATH as _EMBEDDING_PATH, CHROMA_DB_DIR
except ImportError:
    _EMBEDDING_PATH = os.path.join("models", "embedding_model")
    CHROMA_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db")

EMBEDDING_MODEL_PATH = _EMBEDDING_PATH
BASE_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
CHROMA_PERSIST_DIR = CHROMA_DB_DIR
COLLECTION_NAME = "enterprise_knowledge"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


class KnowledgeBase:
    """企业知识库：文档管理 + 向量检索 + 重排序"""

    def __init__(self, embedding_model_path: str = None):
        # ----- 加载Embedding模型 -----
        model_path = embedding_model_path or EMBEDDING_MODEL_PATH
        if os.path.exists(model_path):
            print(f"加载微调模型: {model_path}")
            self.embed_model = SentenceTransformer(model_path)
            self._embedding_model_name = os.path.abspath(model_path)
        else:
            print(f"微调模型不存在，使用通用模型: {BASE_EMBEDDING_MODEL}")
            self.embed_model = SentenceTransformer(BASE_EMBEDDING_MODEL)
            self._embedding_model_name = BASE_EMBEDDING_MODEL

        # ----- 加载 Reranker（启动时加载，优先用本地缓存）-----
        self._reranker = None
        self._reranker_model_name = RERANKER_MODEL
        try:
            # 先尝试只使用本地文件（避免网络下载超时阻塞启动）
            self._reranker = CrossEncoder(RERANKER_MODEL, local_files_only=True)
            print(f"Reranker加载成功(本地): {RERANKER_MODEL}")
        except Exception:
            try:
                # 本地没有则尝试网络下载
                print(f"Reranker本地缓存未找到，尝试下载: {RERANKER_MODEL}")
                self._reranker = CrossEncoder(RERANKER_MODEL)
                print(f"Reranker加载成功(下载): {RERANKER_MODEL}")
            except Exception as e:
                print(f"Reranker加载失败({e})，检索降级为仅Embedding排序")
                self._reranker = False  # 标记已尝试，不再重试

        # ----- 初始化ChromaDB -----
        self.client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},  # 余弦相似度
        )
        print(f"向量库就绪，当前文档数: {self.collection.count()}")

    @property
    def reranker(self):
        """返回已加载的 Reranker 模型（启动时加载）"""
        return self._reranker if self._reranker is not False else None

    # ===================================================================
    # 第一步：文档解析 + 段落切分
    # ===================================================================
    def chunk_text(self, text: str, chunk_size: int = CHUNK_SIZE,
                   overlap: int = CHUNK_OVERLAP) -> List[dict]:
        """
        将长文本切成有重叠的段落
        重叠的目的是防止关键信息刚好卡在段落边界被切断
        """
        chunks = []
        start = 0
        chunk_id = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk_content = text[start:end]
            chunks.append({
                "id": chunk_id,
                "content": chunk_content.strip(),
                "start": start,
                "end": end,
            })
            chunk_id += 1
            if end >= len(text):
                break
            start = end - overlap  # 重叠区域

        return chunks

    # ===================================================================
    # 第二步：从文件批量导入文档
    # ===================================================================
    def add_documents(self, documents: List[dict], source_name: str = ""):
        """
        批量添加文档到知识库

        documents = [
            {"id": "doc_001", "title": "Q345B参数", "content": "..."},
            ...
        ]
        """
        all_chunks = []
        all_embeddings = []
        all_metadatas = []
        all_ids = []

        for doc in documents:
            doc_id = doc["id"]
            title = doc.get("title", "")
            content = doc["content"]

            # 切段落
            chunks = self.chunk_text(content)
            if not chunks:
                continue

            # 批量编码
            chunk_texts = [c["content"] for c in chunks]

            # BGE v1.5: 文档编码不加前缀，查询时才加
            embeddings = self.embed_model.encode(
                chunk_texts,
                normalize_embeddings=True,    # 归一化，余弦相似度=内积
                show_progress_bar=False,
            )

            for i, chunk in enumerate(chunks):
                all_chunks.append(chunk["content"])
                all_embeddings.append(embeddings[i].tolist())
                all_metadatas.append({
                    "doc_id": doc_id,
                    "title": title,
                    "source_file": doc.get("source_file", doc_id),  # 原始文件名（不含分段编号）
                    "chunk_index": i,
                    "source": source_name,
                    "domain": doc.get("domain", "通用"),
                })
                all_ids.append(f"{doc_id}_chunk_{i}")

        if all_ids:
            self.collection.add(
                ids=all_ids,
                embeddings=all_embeddings,
                documents=all_chunks,
                metadatas=all_metadatas,
            )
            print(f"已添加 {len(all_ids)} 个段落 (来自 {len(documents)} 篇文档)")

    # ===================================================================
    # 第三步：检索 — 粗排（Embedding召回）
    # ===================================================================
    def search_rough(self, query: str, top_k: int = 20, domain: str = None) -> List[dict]:
        """
        用Embedding模型从向量库召回top_k个候选段落
        这一步追求召回率（宁可多招，不能漏）
        domain: 可选，限定检索领域
        """
        # query编码需要用query前缀
        query_embedding = self.embed_model.encode(
            [f"为这个句子生成表示以用于检索相关文章：{query}"],
            normalize_embeddings=True,
        )[0].tolist()

        where_filter = {"domain": domain} if domain else None
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
            where=where_filter,
        )

        hits = []
        for i in range(len(results["ids"][0])):
            hits.append({
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "score": 1 - results["distances"][0][i],   # 距离转相似度
            })
        return hits

    # ===================================================================
    # 第四步：检索 — 精排（Reranker）
    # ===================================================================
    def rerank(self, query: str, candidates: List[dict], top_k: int = 5) -> List[dict]:
        """
        用CrossEncoder对Embedding召回的候选做精排
        这一步追求准确率（排在最前面的必须最相关）

        Embedding是双塔模型（query和doc独立编码，速度快但不精确）
        Reranker是交叉编码器（query和doc拼一起进模型，精确但慢）
        所以先Embedding粗排top20，再Reranker精排top5
        """
        if not self.reranker or len(candidates) <= top_k:
            # 没有reranker或候选太少，直接返回
            return candidates[:top_k]

        # 构造 (query, doc) 对
        pairs = [(query, c["content"]) for c in candidates]

        # 交叉编码打分
        scores = self.reranker.predict(pairs)

        # 按新分数排序
        for i, c in enumerate(candidates):
            c["rerank_score"] = float(scores[i])

        candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        return candidates[:top_k]

    # ===================================================================
    # 对外接口：完整检索
    # ===================================================================
    def search(self, query: str, top_k: int = 3, domain: str = None) -> List[dict]:
        """
        完整检索链路：Embedding粗排 → Reranker精排 → 返回top_k

        domain: 可选，限定检索的领域（如 "产品"、"售后"）。不传则检索全部。
        """
        if self.collection.count() == 0:
            return []

        # 粗排召回（支持领域过滤）
        rough_hits = self.search_rough(query, top_k=max(top_k * 4, 10), domain=domain)

        if not rough_hits:
            return []

        # 精排
        final_hits = self.rerank(query, rough_hits, top_k=top_k)

        return final_hits

    # ===================================================================
    # 管理接口
    # ===================================================================
    def get_stats(self) -> dict:
        return {
            "total_chunks": self.collection.count(),
            "collection_name": COLLECTION_NAME,
            "embedding_model": str(self.embed_model),
        }

    def delete_document(self, doc_id: str):
        """删除某篇文档的所有段落"""
        results = self.collection.get(where={"doc_id": doc_id})
        if results["ids"]:
            self.collection.delete(ids=results["ids"])
            print(f"已删除文档 {doc_id} ({len(results['ids'])} 个段落)")

    def clear_all(self):
        """清空知识库"""
        count = self.collection.count()
        if count > 0:
            # ChromaDB没有直接清空，删除重建
            self.client.delete_collection(COLLECTION_NAME)
            self.collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            print(f"已清空知识库 (原 {count} 个段落)")


# ===================================================================
# 命令行入口
# ===================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="企业知识库引擎")
    parser.add_argument("--build", action="store_true", help="构建知识库索引")
    parser.add_argument("--search", type=str, help="检索测试")
    parser.add_argument("--stats", action="store_true", help="查看统计")
    parser.add_argument("--clear", action="store_true", help="清空知识库")
    args = parser.parse_args()

    kb = KnowledgeBase()

    if args.build:
        print("请通过 Web UI (系统状态 → 重建知识库索引) 或 API (POST /models/rebuild-kb) 构建索引。")
        print("确保已上传文档到 uploads/ 目录。")

    if args.search:
        print(f"\n检索: {args.search}")
        print("-" * 60)
        results = kb.search(args.search, top_k=3)

        if not results:
            print("未找到相关结果")
        else:
            for i, hit in enumerate(results):
                print(f"\n#{i+1} [相似度: {hit.get('score', 0):.3f}]"
                      f" [精排分: {hit.get('rerank_score', 0):.3f}]")
                print(f"   来源: {hit['metadata'].get('title', '未知')}")
                print(f"   内容: {hit['content'][:120]}...")

    if args.stats:
        stats = kb.get_stats()
        print(f"知识库统计: {json.dumps(stats, ensure_ascii=False, indent=2)}")

    if args.clear:
        kb.clear_all()
