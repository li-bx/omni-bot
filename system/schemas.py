"""
请求/响应 Pydantic 模型
"""
from typing import Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    text: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    session_id: str
    intent: str
    confidence: float
    reply: str
    source: str        # "knowledge_base" | "direct" | "tool_calling"
    latency_ms: float
    tool_calls: list = []  # [{tool, arguments}, ...]


class IntentSample(BaseModel):
    texts: list


class TrainingConfig(BaseModel):
    batch_size: Optional[int] = None
    epochs: Optional[int] = None
    learning_rate: Optional[float] = None
