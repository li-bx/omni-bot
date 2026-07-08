"""
模型注册中心：统一管理模型加载/卸载/热切换
"""
import os
import json
import threading
import numpy as np
from typing import Optional
from .config import INTENT_MODEL_PATH, EMBEDDING_MODEL_PATH, TRAINING_DATA_DIR, UPLOAD_DIR


class EmbeddingIntentClassifier:
    """基于 Embedding 相似度的意图分类器（无需训练，作为降级方案）"""

    def __init__(self, embed_model, intent_data_path: str):
        self.embed_model = embed_model
        self.samples = []     # [(embedding, intent)]
        self.intents = set()
        self._load(intent_data_path)

    def _load(self, path: str):
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        texts = []
        labels = []
        for intent, samples in data.items():
            if not samples:
                continue
            for text in samples:
                texts.append(text)
                labels.append(intent)
                self.intents.add(intent)

        if texts:
            embeds = self.embed_model.encode(
                texts, normalize_embeddings=True, show_progress_bar=False,
            )
            self.samples = list(zip(embeds, labels))
            print(f"Embedding意图分类就绪: {len(self.samples)} 条样本, {len(self.intents)} 个类别")

    def predict(self, text: str, return_probs: bool = False):
        """返回 (intent, confidence, all_probs_dict)，兼容 BERT 接口"""
        if not self.samples:
            return ("未分类", 0.0, {})

        query_emb = self.embed_model.encode(
            [text], normalize_embeddings=True,
        )[0]

        # 找最近邻
        best_sim = -1
        best_intent = "未分类"
        intent_scores = {i: 0.0 for i in self.intents}
        intent_counts = {i: 0 for i in self.intents}

        for emb, intent in self.samples:
            sim = float(query_emb @ emb)  # 已归一化，内积就是余弦相似度
            intent_scores[intent] = max(intent_scores[intent], sim)
            intent_counts[intent] += 1
            if sim > best_sim:
                best_sim = sim
                best_intent = intent

        # 归一化为概率分布（softmax over scores）
        scores = np.array(list(intent_scores.values()))
        exps = np.exp((scores - scores.max()) * 5)  # x5 放大差异
        probs = exps / exps.sum()
        all_probs = {k: float(v) for k, v in zip(intent_scores.keys(), probs)}

        return (best_intent, best_sim, all_probs)


class ModelRegistry:
    """管理所有已加载模型的单例"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._intent_classifier = None       # 微调后的 BERT 分类器
        self._embed_intent_classifier = None # 降级：Embedding 相似度分类器
        self._knowledge_base = None          # KnowledgeBase
        self._models_ready = False
        self._status = {
            "intent_loaded": False,
            "embedding_loaded": False,
            "kb_chunks": 0,
            "kb_rebuilding": False,
        }

    # ================================================================
    # 加载/卸载
    # ================================================================

    def load_intent_model(self, model_path: str = None) -> dict:
        """加载意图分类模型（优先BERT，否则用Embedding降级）"""
        # 已加载则跳过
        if self._intent_classifier:
            print(f"意图分类模型已加载，跳过重复加载")
            return {"ok": True, "path": "cached", "type": "cached"}

        path = model_path or INTENT_MODEL_PATH

        # 优先加载微调后的 BERT 模型
        if os.path.exists(path):
            try:
                from .infer import IntentClassifier
                self._intent_classifier = IntentClassifier(path)
                self._status["intent_loaded"] = True
                print(f"意图分类模型(BERT): 已加载 {path}")
                return {"ok": True, "path": path, "type": "bert"}
            except Exception as e:
                print(f"BERT 加载失败: {e}，降级为 Embedding 分类")

        # 降级：用 Embedding 模型做分类
        if self.knowledge_base:
            intent_file = os.path.join(TRAINING_DATA_DIR, "intent_data.json")
            self._embed_intent_classifier = EmbeddingIntentClassifier(
                self._knowledge_base.embed_model, intent_file,
            )
            self._status["intent_loaded"] = bool(self._embed_intent_classifier.samples)
            if self._status["intent_loaded"]:
                print(f"意图分类模型(Embedding降级): 已就绪")
                return {"ok": True, "path": "embedding-fallback", "type": "embedding"}

        return {"ok": False, "error": "意图模型不存在，且无Embedding模型可用"}

    def load_embedding_model(self, model_path: str = None, force_reload: bool = False) -> dict:
        """加载 Embedding 模型 + 知识库（已加载则跳过，除非 force_reload）"""
        if self._knowledge_base and not force_reload:
            self._status["embedding_loaded"] = True
            self._status["kb_chunks"] = self._knowledge_base.collection.count()
            print(f"Embedding模型已加载，跳过重复加载 ({self._status['kb_chunks']} 段落)")
            return {"ok": True, "chunks": self._status["kb_chunks"], "cached": True}

        from .knowledge_base import KnowledgeBase
        try:
            self._knowledge_base = KnowledgeBase(
                embedding_model_path=model_path
            )
            self._status["embedding_loaded"] = True
            self._status["kb_chunks"] = self._knowledge_base.collection.count()

            # Embedding 加载成功后，顺手初始化降级意图分类器
            self._init_embed_intent_fallback()

            return {
                "ok": True,
                "chunks": self._status["kb_chunks"],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _init_embed_intent_fallback(self):
        """如果 BERT 没加载，用 Embedding 做意图分类的降级方案"""
        intent_file = os.path.join(TRAINING_DATA_DIR, "intent_data.json")
        if os.path.exists(intent_file):
            self._embed_intent_classifier = EmbeddingIntentClassifier(
                self._knowledge_base.embed_model, intent_file,
            )

    def load_all(self) -> dict:
        """加载或重载所有模型"""
        results = {}
        results["intent"] = self.load_intent_model()
        results["embedding"] = self.load_embedding_model()

        self._models_ready = all(
            r.get("ok") for r in results.values()
        )
        return {
            "ok": self._models_ready,
            "results": results,
            "status": self._status,
        }

    def print_info(self):
        """打印所有已加载模型的详细信息"""
        print()
        print("=" * 60)
        print("  Model Loading Report")
        print("=" * 60)

        # ---- Intent Classifier ----
        print()
        print("[1] Intent Classifier")
        if self._intent_classifier:
            cls = self._intent_classifier
            cls_type = type(cls).__name__
            if cls_type == "IntentClassifier":
                model = cls.model
                model_name = getattr(model.config, '_name_or_path', 'bert-base-chinese')
                param_count = sum(p.numel() for p in model.parameters()) / 1e6
                print(f"    Model:    {model_name}")
                print(f"    Type:     BERT fine-tuned")
                print(f"    Path:     {INTENT_MODEL_PATH}")
                print(f"    Device:   {cls.device}")
                print(f"    Params:   {param_count:.1f}M")
                num_labels = len(cls.label2id)
                print(f"    Labels:   {num_labels}")
                print(f"    Classes:  {list(cls.label2id.values())}")
            elif isinstance(cls, EmbeddingIntentClassifier):
                emb_name = getattr(cls.embed_model, '_embedding_model_name',
                                   'bge-small-zh-v1.5') if hasattr(cls, 'embed_model') else 'bge-small-zh-v1.5'
                print(f"    Model:    {emb_name} (via Embedding)")
                print(f"    Type:     Embedding fallback")
                print(f"    Samples:  {len(cls.samples)}")
                print(f"    Intents:  {len(cls.intents)}")
        elif self._embed_intent_classifier:
            cls = self._embed_intent_classifier
            print(f"    Model:    bge-small-zh-v1.5 (via Embedding)")
            print(f"    Type:     Embedding fallback")
            print(f"    Samples:  {len(cls.samples)}")
            print(f"    Intents:  {len(cls.intents)}")
        else:
            print(f"    Status:   NOT LOADED")

        # ---- Embedding Model ----
        print()
        print("[2] Embedding & Retrieval")
        if self._knowledge_base:
            kb = self._knowledge_base
            emb_model = kb.embed_model

            # 嵌入模型名称
            emb_name = getattr(kb, '_embedding_model_name', 'unknown')
            print(f"    Model:    {emb_name}")

            try:
                inner = emb_model[0]
                if hasattr(inner, 'auto_model'):
                    inner_model = inner.auto_model
                    backbone_name = getattr(inner_model.config, '_name_or_path', type(inner_model).__name__)
                    param_count = sum(p.numel() for p in inner_model.parameters()) / 1e6
                    print(f"    Backbone: {backbone_name}")
                    print(f"    Params:   {param_count:.1f}M")
                else:
                    print(f"    Backbone: {type(inner).__name__}")
            except Exception:
                pass
            try:
                dim = emb_model.get_embedding_dimension() if hasattr(emb_model, 'get_embedding_dimension') else emb_model.get_sentence_embedding_dimension()
                print(f"    Dim:      {dim}")
            except Exception:
                pass
            try:
                dev = emb_model.device if hasattr(emb_model, 'device') else 'N/A'
                print(f"    Device:   {dev}")
            except Exception:
                pass

            # 重排序模型名称
            reranker_name = getattr(kb, '_reranker_model_name', 'unknown')
            reranker = kb._reranker
            if reranker and reranker is not False:
                print(f"    Reranker: {reranker_name} (loaded)")
            elif reranker is False:
                print(f"    Reranker: {reranker_name} (FAILED)")
            else:
                print(f"    Reranker: {reranker_name} (lazy-load)")

            print(f"    VectorDB: ChromaDB")
            print(f"    Collection: {kb.collection.name}")
            print(f"    Chunks:  {kb.collection.count()}")
        else:
            print(f"    Status:    NOT LOADED")

        # ---- Function Calling Tools ----
        print()
        print("[3] Function Calling Tools")
        try:
            from .tool_manager import ToolManager
            tm = ToolManager()
            tools = tm.list_tools()
            print(f"    Total:     {len(tools)}")
            if tools:
                intent_map = {}
                for t in tools:
                    for it in t.get("intents", []):
                        if it not in intent_map:
                            intent_map[it] = []
                        intent_map[it].append(t["name"])
                for intent, names in intent_map.items():
                    print(f"    [{intent}] -> {', '.join(names)}")
        except Exception as e:
            print(f"    Status:    ERROR: {e}")

        print()
        print("=" * 60)
        print("  Ready")
        print("=" * 60)
        print()

    @property
    def intent_classifier(self):
        """意图分类器：优先BERT，没有则用Embedding降级。首次访问时自动加载"""
        if self._intent_classifier is None and self._embed_intent_classifier is None:
            self.load_intent_model()
        return self._intent_classifier or self._embed_intent_classifier

    @property
    def knowledge_base(self):
        """知识库。首次访问时自动加载 Embedding 模型"""
        if self._knowledge_base is None:
            self.load_embedding_model()
        return self._knowledge_base

    @property
    def status(self) -> dict:
        return dict(self._status)

    @property
    def ready(self) -> bool:
        return self._models_ready

    # ================================================================
    # 知识库操作（委托给 KnowledgeBase）
    # ================================================================

    def rebuild_kb(self, model_path: str = None) -> dict:
        """重建知识库索引（同步执行，CUDA 不支持跨线程 encode）"""
        # 如果还没加载 embedding 模型，先加载
        if not self._knowledge_base:
            result = self.load_embedding_model(model_path)
            if not result["ok"]:
                return result

        self._status["kb_rebuilding"] = True
        try:
            self._knowledge_base.clear_all()
            from .config import UPLOAD_DIR, split_document_chunks, scan_upload_documents
            entries = scan_upload_documents(UPLOAD_DIR)
            if entries:
                docs = []
                for entry in entries:
                    try:
                        with open(entry["path"], "r", encoding="utf-8") as f:
                            content = f.read()
                    except Exception:
                        continue
                    chunks = split_document_chunks(content)
                    for i, chunk in enumerate(chunks):
                        docs.append({
                            "id": f"{entry['filename']}_{i}",
                            "title": entry["filename"],
                            "content": chunk,
                            "domain": entry["domain"],
                            "source_file": entry["filename"],
                        })
                self._knowledge_base.add_documents(docs, source_name="uploaded")
            else:
                print("没有上传文档，跳过索引重建")
            self._status["kb_chunks"] = self._knowledge_base.collection.count()
            return {"ok": True, "chunks": self._status["kb_chunks"]}
        except Exception as e:
            print(f"重建知识库失败: {e}")
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(e)}
        finally:
            self._status["kb_rebuilding"] = False

    def add_docs_to_kb(self, filenames: list) -> dict:
        """增量添加指定文档到知识库（不清除已有索引）"""
        if not self._knowledge_base:
            result = self.load_embedding_model()
            if not result["ok"]:
                return result

        from .config import UPLOAD_DIR, split_document_chunks, scan_upload_documents
        entries = scan_upload_documents(UPLOAD_DIR)
        added = 0
        skipped = 0

        for entry in entries:
            if entry["filename"] not in filenames:
                continue
            # 检查是否已索引
            existing = self._knowledge_base.collection.get(
                where={"source_file": entry["filename"]},
                limit=1,
            )
            if existing["ids"]:
                skipped += 1
                continue

            try:
                with open(entry["path"], "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue

            chunks = split_document_chunks(content)
            docs = []
            for i, chunk in enumerate(chunks):
                docs.append({
                    "id": f"{entry['filename']}_{i}",
                    "title": entry["filename"],
                    "content": chunk,
                    "domain": entry["domain"],
                    "source_file": entry["filename"],
                })
            self._knowledge_base.add_documents(docs, source_name="uploaded")
            added += 1
            print(f"[增量索引] {entry['filename']} ({len(chunks)} 段)")

        self._status["kb_chunks"] = self._knowledge_base.collection.count()
        return {"ok": True, "added": added, "skipped": skipped,
                "total_chunks": self._status["kb_chunks"]}

    def get_indexed_doc_ids(self) -> set:
        """获取已索引的文档文件名集合（从 source_file 字段读取）"""
        if not self._knowledge_base:
            return set()
        try:
            result = self._knowledge_base.collection.get(include=["metadatas"])
            ids = set()
            for m in result.get("metadatas", []):
                if m and "source_file" in m:
                    ids.add(m["source_file"])
            return ids
        except Exception:
            return set()

    def search_kb(self, query: str, top_k: int = 3) -> list:
        """检索知识库"""
        if not self._knowledge_base:
            return []
        return self._knowledge_base.search(query, top_k=top_k)
