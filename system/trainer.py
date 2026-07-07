"""
在线训练管理：启动训练、监控进度、模型管理
支持后台异步训练，不阻塞 API 服务
"""
import os

# 禁用 torch.compile — PyTorch 2.12 在 Blackwell 上首次编译 >2 分钟
os.environ["TORCH_COMPILE_DISABLE"] = "1"

import json
import threading
import time
from typing import Optional, Callable, Dict
from .config import (
    INTENT_MODEL_PATH, EMBEDDING_MODEL_PATH, DATA_DIR, MODEL_DIR,
    INTENT_TRAIN_CONFIG, EMBEDDING_TRAIN_CONFIG, UPLOAD_DIR,
    TRAINING_DATA_DIR, split_document_chunks, scan_upload_documents,
)
from .data_manager import DataManager


class TrainingJob:
    """单个训练任务的状态"""

    def __init__(self, job_id: str, job_type: str, config: dict):
        self.job_id = job_id
        self.type = job_type  # "intent" or "embedding"
        self.config = config
        self.status = "queued"  # queued | running | completed | failed
        self.progress = 0.0
        self.message = ""
        self.metrics: dict = {}
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.thread: threading.Thread | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "type": self.type,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "metrics": self.metrics,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class TrainingManager:
    """训练任务调度器"""

    def __init__(self, data_manager: DataManager):
        self.dm = data_manager
        self.jobs: Dict[str, TrainingJob] = {}

    # ================================================================
    # 意图分类训练
    # ================================================================

    def train_intent(self, config: dict = None) -> dict:
        """
        启动意图分类模型训练
        先导出训练数据，再调用 train.py 的逻辑
        """
        job_id = f"intent_{int(time.time())}"

        # 先导出数据
        export_result = self.dm.export_as_training_data()
        if not export_result["ok"]:
            return {"ok": False, "error": export_result["error"]}

        cfg = {**INTENT_TRAIN_CONFIG, **(config or {})}
        job = TrainingJob(job_id, "intent", cfg)

        def run():
            job.status = "running"
            job.started_at = time.time()
            job.message = "开始训练意图分类模型..."
            job.progress = 0.05

            try:
                import torch
                import numpy as np
                from torch.utils.data import Dataset
                from transformers import (
                    BertTokenizer, BertForSequenceClassification,
                    TrainingArguments, Trainer, EarlyStoppingCallback,
                )
                from sklearn.metrics import accuracy_score, f1_score

                # 加载数据
                with open(os.path.join(DATA_DIR, "label_map.json"), "r",
                          encoding="utf-8") as f:
                    mapping = json.load(f)
                    label2id = mapping["label2id"]
                    id2label = mapping["id2label"]

                tokenizer = BertTokenizer.from_pretrained(cfg["model_name"])
                job.progress = 0.15
                job.message = "加载数据..."

                class IntentDataset(Dataset):
                    def __init__(self, path):
                        with open(path, "r", encoding="utf-8") as f:
                            self.data = json.load(f)

                    def __len__(self):
                        return len(self.data)

                    def __getitem__(self, idx):
                        item = self.data[idx]
                        enc = tokenizer(
                            item["text"], truncation=True, padding="max_length",
                            max_length=cfg["max_length"], return_tensors="pt",
                        )
                        return {
                            "input_ids": enc["input_ids"].squeeze(0),
                            "attention_mask": enc["attention_mask"].squeeze(0),
                            "labels": torch.tensor(label2id[item["label"]],
                                                    dtype=torch.long),
                        }

                train_ds = IntentDataset(os.path.join(DATA_DIR, "train.json"))
                val_ds = IntentDataset(os.path.join(DATA_DIR, "val.json"))
                test_ds = IntentDataset(os.path.join(DATA_DIR, "test.json"))

                job.progress = 0.20
                job.message = "加载模型..."

                # 检查是否有上次训练的最佳模型 → 增量训练
                checkpoint_path = os.path.join(INTENT_MODEL_PATH, "config.json")
                if os.path.exists(checkpoint_path):
                    model = BertForSequenceClassification.from_pretrained(
                        INTENT_MODEL_PATH, num_labels=len(label2id),
                        id2label=id2label, label2id=label2id,
                        ignore_mismatched_sizes=True,
                    )
                    model_source = f"增量 ({INTENT_MODEL_PATH})"
                else:
                    model = BertForSequenceClassification.from_pretrained(
                        cfg["model_name"], num_labels=len(label2id),
                        id2label=id2label, label2id=label2id,
                    )
                    model_source = f"基座 ({cfg['model_name']})"

                job.message = f"加载模型: {model_source}"

                def compute_metrics(eval_pred):
                    logits, labels = eval_pred
                    preds = np.argmax(logits, axis=-1)
                    return {
                        "accuracy": accuracy_score(labels, preds),
                        "f1": f1_score(labels, preds, average="macro"),
                    }

                training_args = TrainingArguments(
                    output_dir=INTENT_MODEL_PATH,
                    eval_strategy="epoch",
                    save_strategy="epoch",
                    logging_steps=10,
                    learning_rate=cfg["learning_rate"],
                    per_device_train_batch_size=cfg["batch_size"],
                    per_device_eval_batch_size=cfg["batch_size"] * 2,
                    num_train_epochs=cfg["epochs"],
                    weight_decay=0.01,
                    warmup_ratio=0.1,
                    load_best_model_at_end=True,
                    metric_for_best_model="f1",
                    save_total_limit=2,
                    fp16=torch.cuda.is_available(),
                    report_to="none",
                )

                trainer = Trainer(
                    model=model, args=training_args,
                    train_dataset=train_ds, eval_dataset=val_ds,
                    compute_metrics=compute_metrics,
                    callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
                )

                job.message = "训练中..."
                trainer.train()

                job.progress = 0.85
                job.message = "验证集评估..."
                eval_result = trainer.evaluate(val_ds)
                for k, v in eval_result.items():
                    # trainer 返回 eval_accuracy → 替换前缀为 val_
                    key = k.replace("eval_", "val_") if k.startswith("eval_") else k
                    job.metrics[key] = round(float(v), 4)

                # ---- 测试集评估 ----
                job.progress = 0.88
                job.message = "测试集评估..."
                test_result = trainer.evaluate(test_ds)
                for k, v in test_result.items():
                    key = k.replace("eval_", "test_") if k.startswith("eval_") else k
                    job.metrics[key] = round(float(v), 4)

                # ---- 保存模型（带版本历史，避免覆盖好结果）----
                acc = job.metrics.get("val_accuracy", 0)
                f1 = job.metrics.get("val_f1", 0)
                test_acc = job.metrics.get("test_accuracy", 0)
                test_f1 = job.metrics.get("test_f1", 0)
                version_dir = os.path.join(
                    os.path.dirname(INTENT_MODEL_PATH),
                    f"intent_model_val{acc:.4f}_test{test_acc:.4f}_ts{int(time.time())}",
                )

                # 保存到版本目录
                model.save_pretrained(version_dir, safe_serialization=True)
                tokenizer.save_pretrained(version_dir)

                # 更新历史记录
                history_path = os.path.join(MODEL_DIR, "intent_history.json")
                history = []
                if os.path.exists(history_path):
                    try:
                        with open(history_path, "r", encoding="utf-8") as f:
                            history = json.load(f)
                    except Exception:
                        pass
                history.append({
                    "path": os.path.basename(version_dir),
                    "val_accuracy": round(acc, 4),
                    "val_f1": round(f1, 4),
                    "test_accuracy": round(test_acc, 4),
                    "test_f1": round(test_f1, 4),
                    "timestamp": int(time.time()),
                    "model_source": model_source,
                    "intents": len(label2id),
                })
                # 只保留最近 10 条
                history = history[-10:]
                with open(history_path, "w", encoding="utf-8") as f:
                    json.dump(history, f, ensure_ascii=False, indent=2)

                # 找出历史最佳（按验证集准确率）
                best = max(history, key=lambda h: h["val_accuracy"])
                best_acc = best["val_accuracy"]

                # 如果当前就是最佳或首次训练，设为活跃模型
                if acc >= best_acc:
                    model.save_pretrained(INTENT_MODEL_PATH, safe_serialization=True)
                    tokenizer.save_pretrained(INTENT_MODEL_PATH)

                job.progress = 1.0
                if acc >= best_acc and len(history) > 1:
                    job.message = (
                        f"训练完成！val_acc={acc:.4f} test_acc={test_acc:.4f} (新高! 上次最佳val={best_acc:.4f})"
                    )
                elif len(history) > 1:
                    job.message = (
                        f"训练完成！val_acc={acc:.4f} test_acc={test_acc:.4f} (未超过历史最佳val={best_acc:.4f}，活跃模型不变)"
                    )
                else:
                    job.message = f"训练完成！val_acc={acc:.4f} test_acc={test_acc:.4f}"
                job.metrics["model_source"] = model_source
                job.metrics["best_val_accuracy"] = best_acc
                job.metrics["is_new_best"] = acc >= best_acc
                job.status = "completed"

            except Exception as e:
                job.status = "failed"
                job.message = str(e)
                import traceback
                traceback.print_exc()

            job.finished_at = time.time()

        job.thread = threading.Thread(target=run, daemon=True)
        self.jobs[job_id] = job
        job.thread.start()

        return {"ok": True, "job_id": job_id, "data_info": export_result}

    # ================================================================
    # Embedding 训练
    # ================================================================

    def train_embedding(self, doc_ids: list = None, config: dict = None) -> dict:
        """
        启动 Embedding 模型微调
        流程：
          上传文档 → 切段落 → LLM为每段生成问题 → 构造三元组 → 微调
        支持增量训练：已有模型则加载继续微调
        """
        job_id = f"embed_{int(time.time())}"
        cfg = {**EMBEDDING_TRAIN_CONFIG, **(config or {})}
        job = TrainingJob(job_id, "embedding", cfg)

        def run():
            job.status = "running"
            job.started_at = time.time()
            job.progress = 0.05
            job.message = "从上传文档构造训练数据..."

            try:
                import random

                triplets_path = os.path.join(TRAINING_DATA_DIR, "embedding_triplets.jsonl")
                samples = []        # 原始三元组数据 [[q, p, n1, ...], ...]
                all_docs = []       # 文档段落（LLM生成路径使用）
                questions_map = {}  # {doc_id: [questions]}

                # ---- 0. 检查缓存：已有三元组则跳过 LLM 生成 ----
                if os.path.exists(triplets_path) and os.path.getsize(triplets_path) > 0:
                    job.message = "发现三元组缓存，跳过LLM生成，直接加载..."
                    with open(triplets_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                samples.append(json.loads(line))
                    if samples:
                        job.progress = 0.30
                        job.message = f"从缓存加载 {len(samples)} 条样本，跳过LLM生成"
                    else:
                        job.status = "failed"
                        job.message = "三元组缓存文件为空，请删除后重新训练"
                        return

                # ---- 如果无缓存，走完整流程：提取段落 → LLM生成 → 构造三元组 ----
                if not samples:
                    # ---- 1. 从上传文档提取段落（支持领域子文件夹）----
                    domain_docs = {}  # {domain: [{id, content}, ...]}
                    file_entries = scan_upload_documents(UPLOAD_DIR)
                    for entry in file_entries:
                        try:
                            with open(entry["path"], "r", encoding="utf-8") as f:
                                content = f.read()
                        except Exception:
                            continue
                        chunks = split_document_chunks(content)
                        domain = entry["domain"]
                        if domain not in domain_docs:
                            domain_docs[domain] = []
                        for i, chunk in enumerate(chunks):
                            domain_docs[domain].append({
                                "id": f"{entry['filename']}_chunk_{i}",
                                "content": chunk,
                                "domain": domain,
                            })

                    if not domain_docs:
                        job.status = "failed"
                        job.message = "知识库没有文档，请先上传（支持按领域子文件夹组织，如 产品/、销售/）"
                        return

                    domains = list(domain_docs.keys())
                    domain_counts = {d: len(docs) for d, docs in domain_docs.items()}
                    job.message = f"已提取 {sum(domain_counts.values())} 个段落，{len(domains)} 个领域: {domain_counts}"

                    # ---- 均衡采样 ----
                    max_chunks = cfg.get("max_train_chunks", 200)
                    quota_per_domain = max(5, max_chunks // len(domains)) if domains else max_chunks

                    all_docs = []
                    for domain, docs in domain_docs.items():
                        random.shuffle(docs)
                        sampled = docs[:quota_per_domain]
                        all_docs.extend(sampled)

                    # 控制总量
                    if len(all_docs) > max_chunks:
                        random.shuffle(all_docs)
                        all_docs = all_docs[:max_chunks]

                    final_domain_counts = {}
                    for d in all_docs:
                        final_domain_counts[d["domain"]] = final_domain_counts.get(d["domain"], 0) + 1
                    job.message = f"采样 {len(all_docs)} 个段落 ({max_chunks}上限): {final_domain_counts}"

                    job.progress = 0.10

                    # ---- 2. 用 LLM 为每个段落生成问题 ----
                    import requests

                    for idx, doc in enumerate(all_docs):
                        job.progress = 0.10 + 0.20 * (idx / len(all_docs))
                        if idx % 5 == 0:
                            job.message = f"LLM生成问题中 ({idx}/{len(all_docs)})..."

                        questions = self._generate_questions_for_paragraph(doc["content"])
                        if questions:
                            questions_map[doc["id"]] = questions
                        else:
                            first = doc["content"].split("。")[0][:80]
                            questions_map[doc["id"]] = [first] if len(first) >= 5 else [doc["content"][:50]]

                    job.progress = 0.30
                    job.message = "构造训练三元组..."

                    # ---- 3. 构造三元组（跨领域硬负样本）----
                    # 策略：2个同领域负样本 + 2个跨领域负样本
                    # 跨领域负样本更难区分 → 更强训练信号
                    docs_by_domain = {}
                    for doc in all_docs:
                        d = doc["domain"]
                        if d not in docs_by_domain:
                            docs_by_domain[d] = []
                        docs_by_domain[d].append(doc)

                    for doc in all_docs:
                        positive = doc["content"]
                        my_domain = doc["domain"]
                        questions = questions_map.get(doc["id"], [])

                        # 同领域负样本（内容相近，难区分）
                        same_domain = [
                            d["content"] for d in docs_by_domain.get(my_domain, [])
                            if d["content"] != positive
                        ]
                        # 跨领域负样本（不同领域的文档）
                        cross_domain = [
                            d["content"] for d in all_docs
                            if d["domain"] != my_domain
                        ]

                        negatives = []
                        # 2 个同领域
                        if len(same_domain) >= 2:
                            negatives.extend(random.sample(same_domain, 2))
                        else:
                            negatives.extend(same_domain)
                        # 2 个跨领域
                        need = 4 - len(negatives)
                        if len(cross_domain) >= need:
                            negatives.extend(random.sample(cross_domain, need))
                        else:
                            negatives.extend(cross_domain)

                        # 不够 4 个时从全部文档补
                        if len(negatives) < 4:
                            all_others = [
                                d["content"] for d in all_docs
                                if d["content"] != positive and d["content"] not in negatives
                            ]
                            need = 4 - len(negatives)
                            if len(all_others) >= need:
                                negatives.extend(random.sample(all_others, need))
                            else:
                                negatives.extend(all_others)

                        for q in questions:
                            if len(q) < 4:
                                continue
                            samples.append([q, positive] + negatives)

                    if not samples:
                        job.status = "failed"
                        job.message = "未能生成有效训练样本，请检查文档内容"
                        return

                    # ---- 3.5: 保存三元组到磁盘 ----
                    with open(triplets_path, "w", encoding="utf-8") as f:
                        for s in samples:
                            f.write(json.dumps(s, ensure_ascii=False) + "\n")
                    job.message = f"共 {len(samples)} 条训练样本（已保存）"

                job.progress = 0.35
                job.message = f"共 {len(samples)} 条训练样本，开始微调..."

                # ---- 4. 训练（纯 PyTorch + HuggingFace，绕过 sentence-transformers compile 问题）----
                import torch
                import torch.nn.functional as F
                from torch.utils.data import DataLoader, Dataset
                from transformers import AutoTokenizer, AutoModel

                class TripletDataset(Dataset):
                    def __init__(self, data):
                        self.data = data
                    def __len__(self):
                        return len(self.data)
                    def __getitem__(self, idx):
                        return self.data[idx]

                def collate_fn(batch):
                    texts, labels = [], []
                    n = len(batch[0])
                    for i, s in enumerate(batch):
                        labels.append(i * n + 1)
                        texts.extend(s)
                    return texts, torch.tensor(labels)

                dataset = TripletDataset(samples)
                dataloader = DataLoader(
                    dataset, batch_size=cfg["batch_size"], shuffle=True,
                    collate_fn=collate_fn, num_workers=0,
                )

                device = "cuda" if torch.cuda.is_available() else "cpu"
                model, tokenizer, model_source = self._load_embedding_model(
                    cfg["model_name"], EMBEDDING_MODEL_PATH, device,
                )
                job.message = f"模型: {model_source}"

                steps_per_epoch = len(dataloader)
                total_steps = steps_per_epoch * cfg["epochs"]
                temperature = cfg.get("temperature", 0.05)

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    free, total_vram = torch.cuda.mem_get_info()
                    job.message += f" | 显存: {free/1024**3:.1f}GB | batch={cfg['batch_size']}, epochs={cfg['epochs']}, steps/epoch={steps_per_epoch}"

                optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"])

                best_loss = float("inf")
                best_state_dict = None

                for epoch in range(cfg["epochs"]):
                    model.train()
                    epoch_loss = 0.0
                    for step, (texts, labels) in enumerate(dataloader):
                        labels = labels.to(device)

                        tok = tokenizer(
                            texts, padding=True, truncation=True,
                            max_length=cfg["max_length"], return_tensors="pt",
                        )
                        tok = {k: v.to(device) for k, v in tok.items()}

                        out = model(**tok)
                        emb = self._mean_pooling(out.last_hidden_state, tok["attention_mask"])

                        N = len(labels)
                        q = F.normalize(emb[labels - 1], dim=-1)
                        v = F.normalize(emb, dim=-1)
                        sim = q @ v.T / temperature
                        loss = F.cross_entropy(sim, labels)

                        optimizer.zero_grad()
                        loss.backward()
                        optimizer.step()

                        epoch_loss += loss.item()

                        # 更新进度
                        global_step = epoch * steps_per_epoch + step
                        pct = 0.35 + 0.60 * (global_step / total_steps)
                        job.progress = min(pct, 0.95)
                        if step % 5 == 0 or step == steps_per_epoch - 1:
                            avg = epoch_loss / (step + 1)
                            job.message = (
                                f"Embedding训练: epoch {epoch+1}/{cfg['epochs']} "
                                f"step {step+1}/{steps_per_epoch} loss={avg:.4f}"
                            )

                    # ---- 每个 epoch 结束：记录最优 state_dict ----
                    epoch_avg_loss = epoch_loss / steps_per_epoch
                    if epoch_avg_loss < best_loss:
                        best_loss = epoch_avg_loss
                        best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                        job.message = (
                            f"Embedding训练: epoch {epoch+1}/{cfg['epochs']} "
                            f"loss={epoch_avg_loss:.4f} (新最优!)"
                        )

                # ---- 5. 用最优模型（每 epoch 选最优）----
                job.progress = 0.96
                job.message = "保存模型..."
                from_cache = len(all_docs) == 0

                # 恢复到训练过程中 loss 最低的那个 epoch 的参数
                if best_state_dict is not None:
                    model.load_state_dict(best_state_dict)

                final_loss = round(best_loss if best_loss < float("inf") else (epoch_loss / steps_per_epoch), 4)
                version_dir = os.path.join(
                    os.path.dirname(EMBEDDING_MODEL_PATH),
                    f"embedding_model_loss{final_loss:.4f}_ts{int(time.time())}",
                )

                # 保存到版本目录
                self._save_embedding_model(model, tokenizer, version_dir)

                # 更新历史
                history_path = os.path.join(MODEL_DIR, "embedding_history.json")
                history = []
                if os.path.exists(history_path):
                    try:
                        with open(history_path, "r", encoding="utf-8") as f:
                            history = json.load(f)
                    except Exception:
                        pass
                history.append({
                    "path": os.path.basename(version_dir),
                    "loss": final_loss,
                    "samples": len(samples),
                    "timestamp": int(time.time()),
                    "model_source": model_source,
                    "from_cache": from_cache,
                })
                history = history[-10:]
                with open(history_path, "w", encoding="utf-8") as f:
                    json.dump(history, f, ensure_ascii=False, indent=2)

                # 找出历史最低 loss
                best = min(history, key=lambda h: h["loss"])
                best_loss = best["loss"]

                # 当前就是最佳或首次 → 设为活跃模型
                if final_loss <= best_loss:
                    self._save_embedding_model(model, tokenizer, EMBEDDING_MODEL_PATH)

                del model
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                job.progress = 1.0
                base_msg = f"Embedding微调完成！loss={final_loss:.4f} 样本={len(samples)}"
                if final_loss <= best_loss and len(history) > 1:
                    job.message = f"{base_msg} (新低! 上次最佳loss={best_loss:.4f})"
                elif len(history) > 1:
                    job.message = f"{base_msg} (未超过历史最佳loss={best_loss:.4f}，活跃模型不变)"
                else:
                    job.message = base_msg
                job.metrics = {
                    "samples": len(samples),
                    "final_loss": final_loss,
                    "best_loss": best_loss,
                    "is_new_best": final_loss <= best_loss,
                    "from_cache": from_cache,
                    "model_source": model_source,
                }
                job.status = "completed"

            except Exception as e:
                job.status = "failed"
                job.message = str(e)
                import traceback
                traceback.print_exc()

            job.finished_at = time.time()

        job.thread = threading.Thread(target=run, daemon=True)
        self.jobs[job_id] = job
        job.thread.start()

        return {"ok": True, "job_id": job_id}

    # ================================================================
    # Embedding 模型加载/保存辅助方法
    # ================================================================

    @staticmethod
    def _mean_pooling(last_hidden_state, attention_mask):
        """BGE 模型的 mean pooling"""
        mask = attention_mask.unsqueeze(-1).float()
        return (last_hidden_state * mask).sum(1) / mask.sum(1)

    @staticmethod
    def _load_embedding_model(base_model_name: str, output_dir: str, device: str):
        """
        加载 Embedding 模型：已有微调模型则增量训练，否则从基座开始。
        返回 (HuggingFace model, tokenizer, 来源描述)
        """
        from transformers import AutoTokenizer, AutoModel

        config_path = os.path.join(output_dir, "config.json")
        if os.path.exists(config_path):
            model = AutoModel.from_pretrained(output_dir).to(device)
            tokenizer = AutoTokenizer.from_pretrained(output_dir)
            source = f"增量 ({output_dir})"
        else:
            model = AutoModel.from_pretrained(base_model_name).to(device)
            tokenizer = AutoTokenizer.from_pretrained(base_model_name)
            source = f"基座 ({base_model_name})"
        return model, tokenizer, source

    @staticmethod
    def _save_embedding_model(hf_model, tokenizer, output_dir: str):
        """保存 HuggingFace 格式 + sentence-transformers 兼容格式"""
        from sentence_transformers import SentenceTransformer

        hf_model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)

        # sentence-transformers 格式，供 KnowledgeBase 加载
        st_model = SentenceTransformer(
            output_dir, device=str(hf_model.device),
            model_kwargs={"ignore_mismatched_sizes": True},
        )
        st_model.save(output_dir)

    def _generate_questions_for_paragraph(self, text: str) -> list:
        """用 DeepSeek 为一个段落生成 3-5 个相关问题"""
        import requests

        prompt = f"""为以下技术文档段落生成5个用户可能会问的问题。
要求：
- 问题要像真实用户的口吻（口语化、长短不一）
- 覆盖段落中的关键信息点
- 每行一个问题，不要编号
- 如果段落太短或没实质信息，只生成1-2个问题

段落内容：
{text[:800]}

请输出问题："""

        try:
            resp = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY', '')}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 512,
                },
                timeout=30,
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            questions = [q.strip() for q in content.split("\n") if q.strip()]
            return questions[:5]  # 最多5个
        except Exception as e:
            print(f"LLM生成问题失败: {e}")
            return []

    # ================================================================
    # 通用接口
    # ================================================================

    def get_job(self, job_id: str) -> Optional[dict]:
        job = self.jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(self) -> list:
        return [j.to_dict() for j in self.jobs.values()]

    def cancel_job(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            return {"ok": False, "error": "任务不存在"}
        if job.status not in ("queued", "running"):
            return {"ok": False, "error": f"任务状态 {job.status}，无法取消"}
        job.status = "cancelled"
        job.message = "用户取消"
        return {"ok": True}
