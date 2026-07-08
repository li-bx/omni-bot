"""
在线训练 API
"""
from fastapi import APIRouter, HTTPException
from ..schemas import TrainingConfig
from ..shared import tm

router = APIRouter()


@router.post("/train/intent")
async def train_intent(config: TrainingConfig = None):
    """启动意图分类模型训练"""
    cfg = {}
    if config:
        cfg = {k: v for k, v in config.dict().items() if v is not None}
    return tm.train_intent(cfg)


@router.post("/train/embedding")
async def train_embedding():
    """启动 Embedding 模型微调"""
    return tm.train_embedding()


@router.get("/train/jobs")
async def list_training_jobs():
    """查看所有训练任务"""
    return tm.list_jobs()


@router.get("/train/jobs/{job_id}")
async def get_training_job(job_id: str):
    """查看训练任务状态"""
    result = tm.get_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


@router.post("/train/jobs/{job_id}/cancel")
async def cancel_training_job(job_id: str):
    """取消训练任务"""
    return tm.cancel_job(job_id)
