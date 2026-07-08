"""
模型管理 API
"""
from fastapi import APIRouter, Body
from ..shared import registry

router = APIRouter()


@router.get("/models/status")
async def model_status():
    """查看模型加载状态"""
    return registry.status


@router.post("/models/reload")
async def reload_models():
    """重新加载所有模型（训练完成后调用）"""
    return registry.load_all()


@router.post("/models/rebuild-kb")
async def rebuild_knowledge_base():
    """重建知识库索引（全量）"""
    return registry.rebuild_kb()


@router.post("/models/add-to-kb")
async def add_to_knowledge_base(body: dict = Body(...)):
    """增量添加指定文档到知识库"""
    filenames = body.get("filenames", [])
    return registry.add_docs_to_kb(filenames)


@router.get("/models/indexed-docs")
async def get_indexed_docs():
    """获取已索引的文档列表"""
    return {"indexed": list(registry.get_indexed_doc_ids())}
