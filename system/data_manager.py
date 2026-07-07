"""
训练数据管理：上传、生成、增删改查
支持意图分类数据 + Embedding训练数据 + 知识库文档
"""
import json
import os
import uuid
import time
import shutil
from typing import Optional
from datetime import datetime
from .config import TRAINING_DATA_DIR, UPLOAD_DIR, DATA_DIR, split_document_chunks


class DataManager:
    """统一管理所有训练数据"""

    def __init__(self):
        self._intent_data = {}   # {intent_name: [texts]}
        self._load_intent_data()

    # ================================================================
    # 意图分类数据管理
    # ================================================================

    def _intent_file(self) -> str:
        return os.path.join(TRAINING_DATA_DIR, "intent_data.json")

    def _load_intent_data(self):
        path = self._intent_file()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self._intent_data = json.load(f)

    def _save_intent_data(self):
        with open(self._intent_file(), "w", encoding="utf-8") as f:
            json.dump(self._intent_data, f, ensure_ascii=False, indent=2)

    def list_intents(self) -> list:
        """列出所有意图类别"""
        return [
            {"name": name, "count": len(texts)}
            for name, texts in self._intent_data.items()
        ]

    def add_intent(self, name: str) -> dict:
        """新增意图类别"""
        if name in self._intent_data:
            return {"ok": False, "error": f"意图 '{name}' 已存在"}
        self._intent_data[name] = []
        self._save_intent_data()
        return {"ok": True, "name": name, "count": 0}

    def delete_intent(self, name: str) -> dict:
        """删除意图类别"""
        if name not in self._intent_data:
            return {"ok": False, "error": f"意图 '{name}' 不存在"}
        count = len(self._intent_data[name])
        del self._intent_data[name]
        self._save_intent_data()
        return {"ok": True, "deleted": name, "removed_samples": count}

    def add_samples(self, intent: str, texts: list) -> dict:
        """批量添加样本"""
        if intent not in self._intent_data:
            self._intent_data[intent] = []
        added = 0
        for t in texts:
            t = t.strip()
            if t and t not in self._intent_data[intent] and len(t) >= 2:
                self._intent_data[intent].append(t)
                added += 1
        self._save_intent_data()
        return {"ok": True, "added": added, "total": len(self._intent_data[intent])}

    def delete_samples(self, intent: str, indices: list) -> dict:
        """删除指定样本"""
        if intent not in self._intent_data:
            return {"ok": False, "error": f"意图 '{intent}' 不存在"}
        existing = self._intent_data[intent]
        self._intent_data[intent] = [
            t for i, t in enumerate(existing) if i not in indices
        ]
        removed = len(existing) - len(self._intent_data[intent])
        self._save_intent_data()
        return {"ok": True, "removed": removed}

    def get_samples(self, intent: str, offset: int = 0, limit: int = 50) -> dict:
        """分页获取样本"""
        if intent not in self._intent_data:
            return {"ok": False, "error": f"意图 '{intent}' 不存在"}
        texts = self._intent_data[intent]
        page = texts[offset:offset + limit]
        return {
            "ok": True,
            "intent": intent,
            "total": len(texts),
            "offset": offset,
            "samples": [{"index": offset + i, "text": t}
                         for i, t in enumerate(page)],
        }

    def export_as_training_data(self, train_ratio: float = 0.7,
                                val_ratio: float = 0.15) -> dict:
        """导出为标准训练/验证/测试集"""
        from sklearn.model_selection import train_test_split

        data = []
        for intent, texts in self._intent_data.items():
            for text in texts:
                data.append({"text": text, "label": intent})

        if not data:
            return {"ok": False, "error": "没有数据"}

        labels = [d["label"] for d in data]
        train, temp = train_test_split(data, test_size=1 - train_ratio,
                                       random_state=42, stratify=labels)
        labels_temp = [d["label"] for d in temp]
        val_ratio_adjusted = val_ratio / (1 - train_ratio) if train_ratio < 1 else 0.5
        val, test = train_test_split(temp, test_size=1 - val_ratio_adjusted,
                                     random_state=42, stratify=labels_temp)

        for name, dataset in [("train.json", train), ("val.json", val),
                              ("test.json", test)]:
            path = os.path.join(DATA_DIR, name)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dataset, f, ensure_ascii=False, indent=2)

        # 标签映射
        label2id = {intent: i for i, intent in enumerate(self._intent_data.keys())}
        id2label = {str(i): label for label, i in label2id.items()}
        with open(os.path.join(DATA_DIR, "label_map.json"), "w", encoding="utf-8") as f:
            json.dump({"label2id": label2id, "id2label": id2label},
                      f, ensure_ascii=False, indent=2)

        return {
            "ok": True,
            "train": len(train),
            "val": len(val),
            "test": len(test),
            "intents": len(label2id),
        }

    # ================================================================
    # 知识库文档管理
    # ================================================================

    def upload_document(self, filename: str, content: bytes, domain: str = "通用") -> dict:
        """上传文档到知识库，支持领域分类"""
        ext = os.path.splitext(filename)[1]
        doc_id = f"doc_{uuid.uuid4().hex[:8]}_{int(time.time())}"

        # 按领域存放
        domain_dir = os.path.join(UPLOAD_DIR, domain)
        os.makedirs(domain_dir, exist_ok=True)
        save_path = os.path.join(domain_dir, f"{doc_id}{ext}")

        with open(save_path, "wb") as f:
            f.write(content)

        return {
            "ok": True,
            "doc_id": doc_id,
            "filename": filename,
            "domain": domain,
            "path": save_path,
            "size": len(content),
        }

    def list_documents(self) -> list:
        """列出已上传的文档（含领域信息）"""
        docs = []
        for entry in sorted(os.listdir(UPLOAD_DIR)):
            full = os.path.join(UPLOAD_DIR, entry)
            if os.path.isdir(full):
                # 子文件夹 → 遍历领域内文档
                domain = entry
                for fname in sorted(os.listdir(full)):
                    fpath = os.path.join(full, fname)
                    if os.path.isfile(fpath):
                        docs.append({
                            "id": os.path.splitext(fname)[0],
                            "name": f"{domain}/{fname}",
                            "domain": domain,
                            "size": os.path.getsize(fpath),
                            "uploaded_at": datetime.fromtimestamp(
                                os.path.getmtime(fpath)
                            ).isoformat(),
                        })
            elif os.path.isfile(full):
                docs.append({
                    "id": os.path.splitext(entry)[0],
                    "name": entry,
                    "domain": "通用",
                    "size": os.path.getsize(full),
                    "uploaded_at": datetime.fromtimestamp(
                        os.path.getmtime(full)
                    ).isoformat(),
                })
        return docs

    def delete_document(self, doc_id: str) -> dict:
        """删除文档（支持领域子文件夹）"""
        for entry in sorted(os.listdir(UPLOAD_DIR)):
            full = os.path.join(UPLOAD_DIR, entry)
            if os.path.isdir(full):
                for fname in os.listdir(full):
                    if fname.startswith(doc_id):
                        os.remove(os.path.join(full, fname))
                        return {"ok": True, "deleted": f"{entry}/{fname}"}
            elif os.path.isfile(full) and entry.startswith(doc_id):
                os.remove(full)
                return {"ok": True, "deleted": entry}
        return {"ok": False, "error": "文档不存在"}

    def parse_document_to_chunks(self, doc_id: str, chunk_size: int = 500) -> dict:
        """
        解析文档为段落，用于后续 Embedding 训练
        支持 .txt，后续可扩展 PDF/Word
        """
        for f in os.listdir(UPLOAD_DIR):
            if f.startswith(doc_id):
                path = os.path.join(UPLOAD_DIR, f)
                with open(path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                break
        else:
            return {"ok": False, "error": "文档不存在"}

        # 按段落切分（自动过滤无意义的章节分隔符）
        paragraphs = split_document_chunks(content)
        chunks = []

        for i, para in enumerate(paragraphs):
            # 如果段落太长，进一步切分
            if len(para) <= chunk_size:
                chunks.append({
                    "id": f"{doc_id}_chunk_{i}",
                    "title": f"段落{i+1}",
                    "content": para,
                })
            else:
                # 按句号切
                sub_id = 0
                start = 0
                while start < len(para):
                    end = min(start + chunk_size, len(para))
                    chunk_text = para[start:end]
                    chunks.append({
                        "id": f"{doc_id}_chunk_{i}_{sub_id}",
                        "title": f"段落{i+1}-{sub_id+1}",
                        "content": chunk_text.strip(),
                    })
                    sub_id += 1
                    start = end - 50  # overlap

        return {"ok": True, "doc_id": doc_id, "chunks": chunks,
                "total": len(chunks)}
