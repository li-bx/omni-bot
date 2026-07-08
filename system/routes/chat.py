"""
对话 API — 薄封装层，委托给共享管线
"""
from fastapi import APIRouter, HTTPException, Request
from ..schemas import ChatRequest, ChatResponse
from ..chat_pipeline import run_chat_pipeline

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    """
    对话接口 — 完整链路：
    意图识别 → RAG检索 → [Function Calling] → LLM生成

    如果当前意图配置了工具，自动启用 Function Calling 模式
    """
    result = await run_chat_pipeline(request, req.text, req.session_id)
    return ChatResponse(
        session_id=result.session_id,
        intent=result.intent,
        confidence=result.confidence,
        reply=result.reply,
        source=result.source,
        latency_ms=result.latency_ms,
        tool_calls=result.tool_call_log,
    )


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式对话（SSE）- TODO"""
    pass
