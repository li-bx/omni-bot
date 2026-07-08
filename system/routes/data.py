"""
训练数据管理 API — 意图、样本、Prompts、生成、导出
"""
import json
import requests
from fastapi import APIRouter, Body
from ..schemas import IntentSample
from ..prompts import load_prompts, save_prompts
from ..shared import dm
from ..config import get_api_key, DEEPSEEK_API_URL

router = APIRouter()


@router.get("/data/intents")
async def list_intents():
    """列出所有意图类别"""
    return dm.list_intents()


@router.post("/data/intents/{name}")
async def add_intent(name: str):
    """新增意图类别"""
    return dm.add_intent(name)


@router.delete("/data/intents/{name}")
async def delete_intent(name: str):
    """删除意图类别"""
    return dm.delete_intent(name)


@router.get("/data/samples/{intent}")
async def get_samples(intent: str, offset: int = 0, limit: int = 50):
    """获取某意图的样本"""
    return dm.get_samples(intent, offset, limit)


@router.post("/data/samples/{intent}")
async def add_samples(intent: str, body: IntentSample):
    """批量添加样本"""
    return dm.add_samples(intent, body.texts)


@router.delete("/data/samples/{intent}")
async def delete_samples(intent: str, indices: str = ""):
    """删除样本 indices=0,2,5"""
    idx_list = [int(i) for i in indices.split(",") if i.strip().isdigit()]
    return dm.delete_samples(intent, idx_list)


@router.get("/data/prompts")
async def get_prompts():
    """获取所有意图的 System Prompt 配置"""
    return {"prompts": load_prompts()}


@router.put("/data/prompts/{intent}")
async def set_prompt(intent: str, body: dict = Body(...)):
    """设置某个意图的 System Prompt"""
    prompts = load_prompts()
    prompts[intent] = body.get("prompt", "")
    save_prompts(prompts)
    return {"ok": True, "intent": intent}


@router.post("/data/reload")
async def reload_intent_data():
    """从磁盘重新加载意图数据（手动改文件后调用）"""
    dm._load_intent_data()
    return {"ok": True, "intents": len(dm.list_intents())}


@router.post("/data/export")
async def export_training_data():
    """导出训练集/验证集/测试集"""
    return dm.export_as_training_data()


@router.post("/data/generate/{intent}")
async def auto_generate_samples(intent: str, count: int = 30):
    """用 LLM 为指定意图自动生成更多样本"""
    existing = dm.get_samples(intent, limit=1000)
    existing_texts = [s["text"] for s in existing.get("samples", [])]

    if not existing_texts:
        return {"ok": False, "error": f"意图 '{intent}' 还没有样本，请先手动添加 5-10 条种子"}

    seeds_str = "\n".join(f"- {t}" for t in existing_texts[:10])
    prompt = f"""以下是一些 AI 企业数字化"{intent}"意图的问句示例：

{seeds_str}

请生成 {count} 个全新的、不同于以上任何一条的"{intent}"意图问句。
要求：
- 涵盖该意图下的不同子场景
- 模拟真实用户的表达方式（不要太标准）
- 长度从3个字到30个字不等
- 每行一个，不要编号"""

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {get_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.9,
                "max_tokens": 2048,
            },
            timeout=30,
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        new_texts = [
            t.strip() for t in content.split("\n")
            if t.strip() and not t.startswith("-") and not t.startswith(("1.", "2."))
        ]

        result = dm.add_samples(intent, new_texts)
        return {"ok": True, "generated": len(new_texts), "added": result["added"],
                "total": result["total"]}

    except Exception as e:
        return {"ok": False, "error": str(e)}
