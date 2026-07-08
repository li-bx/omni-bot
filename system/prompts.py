"""
System Prompt 配置管理
"""
import os
import json
from .config import DATA_DIR


PROMPTS_FILE = os.path.join(DATA_DIR, "configs", "system_prompts.json")

DEFAULT_PROMPTS = {
    "闲聊": "你是友善的助手，保持亲切自然的对话。",
    "未分类": "你是企业数字化助手，根据知识库帮助用户解答问题。如果知识库中找不到信息，如实告知。",
}


def _auto_prompt(intent: str) -> str:
    """根据意图名自动生成 System Prompt"""
    return (
        f"你是企业「{intent}」领域的专家，基于知识库和工具调用结果准确回答相关问题。"
        f"回答要求：使用 Markdown 格式，包含适当的标题、列表、表格、加粗等排版。专业、清晰、简洁。"
    )


def load_prompts() -> dict:
    """加载 prompts，文件不存在则用默认值"""
    if os.path.exists(PROMPTS_FILE):
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            return {**DEFAULT_PROMPTS, **json.load(f)}
    return dict(DEFAULT_PROMPTS)


def save_prompts(prompts: dict):
    """保存 prompts"""
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)


def get_prompt(intent: str) -> str:
    """获取某个意图的 System Prompt，不存在则自动生成"""
    prompts = load_prompts()
    if intent in prompts:
        return prompts[intent]
    return _auto_prompt(intent)
