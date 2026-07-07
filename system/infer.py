"""
BERT意图分类器推理类 + 测试
用法：python infer.py
"""
import torch
import json
from transformers import BertTokenizer, BertForSequenceClassification


class IntentClassifier:
    """轻量级意图分类器，基于微调后的BERT"""

    def __init__(self, model_path="./intent_model", device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = BertTokenizer.from_pretrained(model_path)
        self.model = BertForSequenceClassification.from_pretrained(model_path)
        self.model.to(self.device)
        self.model.eval()

        # 从模型配置读取标签映射
        self.id2label = self.model.config.id2label
        self.label2id = self.model.config.label2id

    @torch.no_grad()
    def predict(self, text, return_probs=False):
        """单条预测，可选择返回所有类别的概率"""
        inputs = self.tokenizer(
            text,
            truncation=True,
            padding=True,
            max_length=64,
            return_tensors="pt",
        ).to(self.device)

        outputs = self.model(**inputs)
        logits = outputs.logits
        probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]
        pred_id = int(torch.argmax(logits, dim=-1).cpu().item())
        # id2label 的键可能是 int 或 str，兼容两种
        intent = self.id2label.get(pred_id) or self.id2label.get(str(pred_id)) or f"unknown_{pred_id}"

        if return_probs:
            return intent, float(probs[pred_id]), {
                self.id2label.get(i) or self.id2label.get(str(i)) or str(i): float(p)
                for i, p in enumerate(probs)
            }
        return intent

    def predict_batch(self, texts, threshold=0.6):
        """批量预测，低置信度自动标记为'其他'"""
        results = []
        for text in texts:
            intent, confidence, all_probs = self.predict(text, return_probs=True)
            if confidence < threshold:
                intent = "其他"
                confidence = 0.0
            results.append({
                "text": text,
                "intent": intent,
                "confidence": round(confidence, 4),
            })
        return results


# ===== 测试 =====
if __name__ == "__main__":
    clf = IntentClassifier("./intent_model")

    tests = [
        "设备的最大功率是多少瓦",
        "机器坏了开不了机怎么办",
        "我的订单发到哪了",
        "今天天气真不错啊",
        "这个参数在哪里配置",
    ]

    for text in tests:
        intent, conf, probs = clf.predict(text, return_probs=True)
        print(f"[{intent}] (置信度:{conf:.3f}) → {text}")

        top3 = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:3]
        print(f"  Top3: {[(label, f'{prob:.2%}') for label, prob in top3]}")
        print()
