"""
共享聊天管线 — 意图识别 → RAG检索 → Function Calling → LLM生成 → 会话保存
供 /chat (JSON API) 和 /ui/chat (HTML 端点) 复用

用法：
    from .chat_pipeline import run_chat_pipeline, ChatPipelineResult

    result = await run_chat_pipeline(request, text, session_id)
    # result.reply     → LLM 回复文本
    # result.intent    → 意图分类
    # result.source    → "knowledge_base" | "direct" | "tool_calling"
"""
import time
from dataclasses import dataclass, field
from fastapi import Request, HTTPException

from .shared import (
    registry, tool_manager, sessions, MAX_HISTORY,
    check_auth, _get_user, _get_user_role, _session_key,
)
from . import auth_db
from .prompts import get_prompt
from .llm import call_llm, call_llm_with_tools


@dataclass
class ChatPipelineResult:
    """管线执行结果"""
    session_id: str
    text: str               # 原始用户输入
    reply: str              # LLM 回复文本
    intent: str             # 意图分类
    confidence: float       # 意图置信度
    source: str             # "knowledge_base" | "direct" | "tool_calling"
    latency_ms: float       # 响应耗时（毫秒）
    tool_call_log: list = field(default_factory=list)  # [{tool, arguments}, ...]


async def run_chat_pipeline(
    request: Request, text: str, session_id: str
) -> ChatPipelineResult:
    """
    执行完整聊天管线。

    调用方只需要格式化返回 — JSON (ChatResponse) 或 HTML (TemplateResponse)。
    未认证时抛出 HTTPException(401)；调用方可根据需要自行处理 HX-Redirect。
    """
    # ---- Auth ----
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="请先登录")
    t0 = time.perf_counter()

    # ---- Step 0: 加载会话历史（用户隔离）----
    skey = _session_key(request, session_id)
    history = sessions.get(skey, [])

    # ---- Step 1: 意图识别（拼接上下文，处理追问和省略指代）----
    if registry.intent_classifier:
        context_parts = []
        for msg in history[-6:]:
            if msg["role"] == "user":
                context_parts.append(msg["content"])
        if context_parts:
            context_text = text + "（上文：" + "；".join(context_parts[-2:]) + "）"
        else:
            context_text = text
        intent, confidence, _ = registry.intent_classifier.predict(
            context_text, return_probs=True
        )
        use_kb = intent not in {"闲聊", "未分类"}
    else:
        intent = "未分类"
        confidence = 0.0
        use_kb = True

    # ---- Step 2: RAG 检索 ----
    knowledge_texts = []
    if use_kb and registry.knowledge_base:
        hits = registry.search_kb(text, top_k=3)
        knowledge_texts = [h["content"] for h in hits]

    # ---- Step 3: System Prompt ----
    system_prompt = get_prompt(intent)

    # ---- Step 4: Function Calling 或传统 RAG + LLM ----
    tools = tool_manager.get_tools_for_intent(intent)
    # 按用户角色过滤工具权限
    user_role = _get_user_role(request)
    if tools and user_role:
        allowed = auth_db.get_role_tool_permissions(user_role)
        filtered = [t for t in tools if t["name"] in allowed]
        if len(filtered) < len(tools):
            print(f"[RBAC] 角色 '{user_role}' 过滤工具: {len(tools)} → {len(filtered)}")
        tools = filtered
    tool_call_log = []

    if tools:
        print(f"[Function Calling] 意图 '{intent}' 匹配到 {len(tools)} 个工具: "
              f"{[t['name'] for t in tools]}")
        reply, tool_call_log = call_llm_with_tools(
            system_prompt, text, tools, knowledge_texts, history,
            user_account=_get_user(request),
        )
        source = "tool_calling"
    else:
        if intent == "闲聊":
            user_prompt = text
        elif knowledge_texts:
            context = "\n---\n".join(knowledge_texts)
            user_prompt = f"参考以下知识库内容回答用户问题：\n\n{context}\n\n用户问题：{text}"
        else:
            user_prompt = text

        reply = call_llm(system_prompt, user_prompt, history)
        source = "knowledge_base" if knowledge_texts else "direct"

    latency = (time.perf_counter() - t0) * 1000

    # ---- 保存到会话历史 ----
    if skey not in sessions:
        sessions[skey] = []
    sessions[skey].append({"role": "user", "content": text})
    sessions[skey].append({"role": "assistant", "content": reply})
    if len(sessions[skey]) > MAX_HISTORY * 2:
        sessions[skey] = sessions[skey][-MAX_HISTORY * 2:]

    return ChatPipelineResult(
        session_id=session_id,
        text=text,
        reply=reply,
        intent=intent,
        confidence=round(float(confidence), 4),
        source=source,
        latency_ms=round(latency, 2),
        tool_call_log=tool_call_log,
    )
