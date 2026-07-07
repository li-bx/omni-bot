"""
智能 AI 企业数字化系统 — 统一入口
启动：python -m system.main
访问：http://localhost:8000/docs

完整链路：
  用户上传数据 → 在线训练 → 模型加载 → 推理服务
  意图识别 → RAG检索 → Reranker重排 → LLM生成回答
"""

# ================================================================
# Section A: 所有导入
# ================================================================
import os
import sys
import time
import json
import hashlib
import secrets
import uuid
import requests
from typing import Optional

# 确保能导入同目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, UploadFile, File, Body, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from .config import (
    get_api_key, DEEPSEEK_API_URL, INTENT_MODEL_PATH,
    EMBEDDING_MODEL_PATH, UPLOAD_DIR, DATA_DIR,
)
from .data_manager import DataManager
from .trainer import TrainingManager
from .model_registry import ModelRegistry
from .tool_manager import ToolManager
from .mock_data import (
    MOCK_PRODUCTS, MOCK_PROJECTS, MOCK_TICKETS, MOCK_ORDERS,
    MOCK_SUPPLIERS, MOCK_INVOICES, MOCK_PAYMENTS, MOCK_CONTRACTS,
    MOCK_SALES, MOCK_SALES_BY_REGION, MOCK_SALES_BY_PRODUCT,
    MOCK_OA_TASKS, MOCK_LEAVE_BALANCE, MOCK_COMPANY_INFO,
)
from . import auth_db


# ================================================================
# Section B: 应用初始化
# ================================================================
app = FastAPI(title="AI 企业数字化系统", version="2.0.0")

# 静态文件服务（CSS / JS）
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

dm = DataManager()
tm = TrainingManager(dm)
registry = ModelRegistry()
tool_manager = ToolManager()

# ================================================================
# Section C: System Prompt 配置
# ================================================================
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

# 自动加载已有模型
registry.load_all()
registry.print_info()


# ================================================================
# Section D: 请求/响应模型
# ================================================================

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


# ================================================================
# Section E: 认证（SQLite RBAC）
# ================================================================
tokens: dict = {}  # {token: username}

def _extract_token(request: Request) -> str:
    """统一从请求中提取 token（Header > Cookie > Query）"""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("auth_token", "")
    if not token:
        token = request.query_params.get("token", "")
    return token or None

def check_auth(request: Request) -> bool:
    """验证请求是否已登录"""
    token = _extract_token(request)
    return bool(token and token in tokens)

def _get_user(request: Request) -> str:
    """从请求中提取当前用户名"""
    return tokens.get(_extract_token(request), "anonymous")

def _get_user_role(request: Request) -> str:
    """获取当前用户的角色名"""
    username = _get_user(request)
    if username == "anonymous":
        return None
    user = auth_db.get_user(username)
    return user["role_name"] if user else None


# ================================================================
# Section F: 会话管理
# ================================================================
sessions: dict = {}   # {"{username}:{session_id}": [{"role": ..., "content": ...}]}
MAX_HISTORY = 10      # 每次携带最近 N 轮对话

def _session_key(request: Request, session_id: str) -> str:
    """生成用户隔离的 session key"""
    return f"{_get_user(request)}:{session_id}"


# ================================================================
# Section G: LLM 调用函数（必须在 /chat 路由之前定义）
# ================================================================

def _deepseek_api_key_ok() -> bool:
    """检查 API Key 是否已配置"""
    key = get_api_key()
    return bool(key and key != "your-api-key")

def call_llm(system_prompt: str, user_prompt: str, history: list = None) -> str:
    """调用 DeepSeek API，支持对话历史"""
    if not _deepseek_api_key_ok():
        return "[API Key 未配置] 请配置 DEEPSEEK_API_KEY 环境变量。"

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-MAX_HISTORY * 2:])
    messages.append({"role": "user", "content": user_prompt})

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {get_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024,
            },
            timeout=15,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM 调用失败] {e}"


def call_llm_with_tools(
    system_prompt: str,
    user_prompt: str,
    tools: list,
    knowledge_texts: list = None,
    history: list = None,
    max_turns: int = 5,
    user_account: str = "",
) -> tuple:
    """
    带 Function Calling 的 LLM 调用，支持对话历史

    返回: (最终回复文本, 工具调用记录列表)
    """
    if not _deepseek_api_key_ok():
        return ("[API Key 未配置] 请配置 DEEPSEEK_API_KEY 环境变量。", [])

    # 构建消息：system + 历史 + 当前用户问题
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-MAX_HISTORY * 2:])

    if knowledge_texts:
        context = "\n---\n".join(knowledge_texts)
        user_content = (
            f"请参考以下知识库内容帮助用户。如果需要查询实时数据"
            f"（如订单状态、产品库存、维修进度等），请使用可用工具。\n\n"
            f"知识库内容：\n{context}\n\n用户问题：{user_prompt}"
        )
    else:
        user_content = (
            f"如果需要查询实时数据，请使用可用工具。\n\n用户问题：{user_prompt}"
        )

    messages.append({"role": "user", "content": user_content})

    tools_openai = ToolManager.to_openai_format(tools)
    tool_call_log = []

    for turn in range(max_turns):
        try:
            resp = requests.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {get_api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": messages,
                    "tools": tools_openai,
                    "tool_choice": "auto",
                    "temperature": 0.3,
                    "max_tokens": 1024,
                },
                timeout=30,
            )
            data = resp.json()

            if "choices" not in data:
                print(f"[FC] API 异常响应: {data}")
                return (f"[LLM 响应异常] {str(data)}", tool_call_log)

            msg = data["choices"][0]["message"]

        except requests.Timeout:
            return ("[请求超时] LLM 响应超时，请稍后重试。", tool_call_log)
        except Exception as e:
            return (f"[LLM 调用失败] {e}", tool_call_log)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return (msg.get("content", ""), tool_call_log)

        # 记录并执行工具调用
        print(f"\n[FC] 第 {turn + 1} 轮工具调用:")
        for tc in tool_calls:
            print(f"  → {tc['function']['name']}({tc['function']['arguments']})")
            tool_call_log.append({
                "tool": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
            })

        assistant_msg = {
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": tool_calls,
        }
        messages.append(assistant_msg)

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}
            result = tool_manager.execute(func_name, func_args, user_account=user_account)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    # 超出最大轮次，请求最终总结
    print(f"[FC] 达到最大轮次 {max_turns}，请求最终总结...")
    messages.append({
        "role": "user",
        "content": "请基于以上获取的所有信息，给用户一个完整、专业的回复。",
    })

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {get_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024,
            },
            timeout=30,
        )
        data = resp.json()
        return (data["choices"][0]["message"]["content"], tool_call_log)
    except Exception as e:
        return ("已获取相关信息，但生成回复时遇到问题，请稍后重试。", tool_call_log)


# ================================================================
# Section H: 认证 API
# ================================================================

@app.post("/login")
async def login(body: dict = Body(...)):
    """登录验证"""
    username = body.get("username", "")
    password = body.get("password", "")
    user = auth_db.get_user(username)
    if user and auth_db.verify_password(password, user["password_hash"]):
        token = secrets.token_hex(32)
        tokens[token] = username
        return {
            "ok": True, "token": token,
            "name": user["display_name"],
            "role": user["role_name"],
        }
    raise HTTPException(status_code=401, detail="账户或密码错误")


@app.post("/logout")
async def logout(request: Request):
    """退出登录"""
    token = _extract_token(request)
    tokens.pop(token, None)
    return {"ok": True}


@app.get("/user/info")
async def user_info(request: Request):
    """获取当前登录用户信息"""
    token = _extract_token(request)
    username = tokens.get(token)
    if username:
        user = auth_db.get_user(username)
        if user:
            return {
                "ok": True, "username": username,
                "name": user["display_name"],
                "role": user["role_name"],
            }
    raise HTTPException(status_code=401)


# ================================================================
# Section I: 会话管理 API
# ================================================================

@app.delete("/session/{session_id}")
async def clear_session(session_id: str, request: Request):
    """清除指定会话的历史"""
    key = _session_key(request, session_id)
    if key in sessions:
        del sessions[key]
        return {"ok": True, "message": f"会话 {session_id} 已清除"}
    return {"ok": False, "message": "会话不存在"}


# ================================================================
# Section I-2: 用户 & 角色管理 API（RBAC）
# ================================================================

@app.get("/users")
async def list_users(request: Request):
    """列出所有用户（需管理员权限）"""
    if not check_auth(request):
        raise HTTPException(status_code=401)
    return {"users": auth_db.list_users()}


@app.post("/users")
async def create_user(body: dict = Body(...), request: Request = None):
    """创建用户"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.create_user(
        username=body.get("username", ""),
        password=body.get("password", ""),
        display_name=body.get("display_name", body.get("username", "")),
        role_name=body.get("role_name", "管理员"),
    )


@app.put("/users/{username}")
async def update_user(username: str, body: dict = Body(...), request: Request = None):
    """更新用户"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.update_user(username, **body)


@app.delete("/users/{username}")
async def delete_user(username: str, request: Request = None):
    """删除用户"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.delete_user(username)


@app.get("/roles")
async def list_roles(request: Request):
    """列出所有角色"""
    if not check_auth(request):
        raise HTTPException(status_code=401)
    roles = auth_db.list_roles()
    # 附加每个角色的工具权限
    for r in roles:
        r["permissions"] = list(auth_db.get_role_tool_permissions(r["name"]))
    return {"roles": roles}


@app.post("/roles")
async def create_role(body: dict = Body(...), request: Request = None):
    """创建角色"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.create_role(
        name=body.get("name", ""),
        description=body.get("description", ""),
    )


@app.delete("/roles/{name}")
async def delete_role(name: str, request: Request = None):
    """删除角色"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.delete_role(name)


@app.get("/roles/{name}/permissions")
async def get_role_permissions(name: str, request: Request = None):
    """获取角色的工具权限"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return {
        "role": name,
        "tools": list(auth_db.get_role_tool_permissions(name)),
        "all_tools": [t["name"] for t in tool_manager.list_tools()],
    }


@app.put("/roles/{name}/permissions")
async def set_role_permissions(name: str, body: dict = Body(...), request: Request = None):
    """设置角色的工具权限"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.set_role_tool_permissions(name, body.get("tools", []))


# ================================================================
# Section J: 数据管理 API
# ================================================================

@app.get("/data/intents")
async def list_intents():
    """列出所有意图类别"""
    return dm.list_intents()


@app.post("/data/intents/{name}")
async def add_intent(name: str):
    """新增意图类别"""
    return dm.add_intent(name)


@app.delete("/data/intents/{name}")
async def delete_intent(name: str):
    """删除意图类别"""
    return dm.delete_intent(name)


@app.get("/data/samples/{intent}")
async def get_samples(intent: str, offset: int = 0, limit: int = 50):
    """获取某意图的样本"""
    return dm.get_samples(intent, offset, limit)


@app.post("/data/samples/{intent}")
async def add_samples(intent: str, body: IntentSample):
    """批量添加样本"""
    return dm.add_samples(intent, body.texts)


@app.delete("/data/samples/{intent}")
async def delete_samples(intent: str, indices: str = ""):
    """删除样本 indices=0,2,5"""
    idx_list = [int(i) for i in indices.split(",") if i.strip().isdigit()]
    return dm.delete_samples(intent, idx_list)


@app.get("/data/prompts")
async def get_prompts():
    """获取所有意图的 System Prompt 配置"""
    return {"prompts": load_prompts()}


@app.put("/data/prompts/{intent}")
async def set_prompt(intent: str, body: dict = Body(...)):
    """设置某个意图的 System Prompt"""
    prompts = load_prompts()
    prompts[intent] = body.get("prompt", "")
    save_prompts(prompts)
    return {"ok": True, "intent": intent}


@app.post("/data/reload")
async def reload_intent_data():
    """从磁盘重新加载意图数据（手动改文件后调用）"""
    dm._load_intent_data()
    return {"ok": True, "intents": len(dm.list_intents())}


@app.post("/data/export")
async def export_training_data():
    """导出训练集/验证集/测试集"""
    return dm.export_as_training_data()


@app.post("/data/generate/{intent}")
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


# ================================================================
# Section K: 文档上传 API（知识库）
# ================================================================

@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...), domain: str = "通用", request: Request = None):
    """上传知识库文档，可指定领域分类"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401, detail="请先登录")
    content = await file.read()
    return dm.upload_document(file.filename, content, domain=domain)


@app.get("/documents")
async def list_documents():
    """列出已上传文档"""
    return dm.list_documents()


@app.get("/documents/domains")
async def list_domains():
    """列出所有文档领域"""
    from .config import scan_upload_documents
    entries = scan_upload_documents()
    domains = sorted(set(e["domain"] for e in entries))
    return {"domains": domains}


@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档"""
    return dm.delete_document(doc_id)


@app.post("/documents/{doc_id}/parse")
async def parse_document(doc_id: str):
    """解析文档为段落"""
    return dm.parse_document_to_chunks(doc_id)


# ================================================================
# Section L: 在线训练 API
# ================================================================

@app.post("/train/intent")
async def train_intent(config: TrainingConfig = None):
    """启动意图分类模型训练"""
    cfg = {}
    if config:
        cfg = {k: v for k, v in config.dict().items() if v is not None}
    return tm.train_intent(cfg)


@app.post("/train/embedding")
async def train_embedding():
    """启动 Embedding 模型微调"""
    return tm.train_embedding()


@app.get("/train/jobs")
async def list_training_jobs():
    """查看所有训练任务"""
    return tm.list_jobs()


@app.get("/train/jobs/{job_id}")
async def get_training_job(job_id: str):
    """查看训练任务状态"""
    result = tm.get_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


@app.post("/train/jobs/{job_id}/cancel")
async def cancel_training_job(job_id: str):
    """取消训练任务"""
    return tm.cancel_job(job_id)


# ================================================================
# Section M: 模型管理 API
# ================================================================

@app.get("/models/status")
async def model_status():
    """查看模型加载状态"""
    return registry.status


@app.post("/models/reload")
async def reload_models():
    """重新加载所有模型（训练完成后调用）"""
    return registry.load_all()


@app.post("/models/rebuild-kb")
async def rebuild_knowledge_base():
    """重建知识库索引（全量）"""
    return registry.rebuild_kb()


@app.post("/models/add-to-kb")
async def add_to_knowledge_base(body: dict = Body(...)):
    """增量添加指定文档到知识库"""
    filenames = body.get("filenames", [])
    return registry.add_docs_to_kb(filenames)


@app.get("/models/indexed-docs")
async def get_indexed_docs():
    """获取已索引的文档列表"""
    return {"indexed": list(registry.get_indexed_doc_ids())}


# ================================================================
# Section N: Function Calling 工具管理 API
# ================================================================

@app.get("/tools")
async def list_tools():
    """列出所有已配置的工具"""
    return {"tools": tool_manager.list_tools()}


@app.get("/tools/{name}")
async def get_tool(name: str):
    """获取单个工具定义"""
    tool = tool_manager.get_tool(name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"工具 '{name}' 不存在")
    return tool


@app.post("/tools")
async def add_tool(body: dict = Body(...)):
    """添加新工具"""
    result = tool_manager.add_tool(body)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.put("/tools/{name}")
async def update_tool(name: str, body: dict = Body(...)):
    """更新工具定义"""
    result = tool_manager.update_tool(name, body)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.delete("/tools/{name}")
async def delete_tool(name: str):
    """删除工具"""
    result = tool_manager.delete_tool(name)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/tools/intent/{intent}")
async def get_tools_for_intent(intent: str):
    """获取指定意图可用的工具列表"""
    tools = tool_manager.get_tools_for_intent(intent)
    return {"intent": intent, "tools": tools}


@app.post("/tools/reload")
async def reload_tools():
    """从磁盘重新加载工具配置"""
    return tool_manager.reload()


# ================================================================
# Section O: 推理 API（核心）
# ================================================================

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    """
    对话接口 — 完整链路：
    意图识别 → RAG检索 → [Function Calling] → LLM生成

    如果当前意图配置了工具，自动启用 Function Calling 模式
    """
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="请先登录")
    t0 = time.perf_counter()

    # ---- Step 0: 加载会话历史（用户隔离）----
    skey = _session_key(request, req.session_id)
    history = sessions.get(skey, [])

    # ---- Step 1: 意图识别（拼接上下文，处理追问和省略指代）----
    if registry.intent_classifier:
        context_parts = []
        for msg in history[-6:]:
            if msg["role"] == "user":
                context_parts.append(msg["content"])
        if context_parts:
            context_text = req.text + "（上文：" + "；".join(context_parts[-2:]) + "）"
        else:
            context_text = req.text
        intent, confidence, all_probs = registry.intent_classifier.predict(
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
        hits = registry.search_kb(req.text, top_k=3)
        knowledge_texts = [h["content"] for h in hits]

        print(f"\n{'='*60}")
        print(f"[RAG检索] 用户: {req.text}")
        print(f"[RAG检索] 意图: {intent} (置信度: {confidence:.3f})")
        if hits:
            for i, h in enumerate(hits):
                score = h.get('score', 0)
                rerank = h.get('rerank_score', 'N/A')
                title = h.get('metadata', {}).get('title', '?')
                print(f"  #{i+1} score={score:.3f} rerank={rerank} [{title}]")
                print(f"     {h['content'][:120]}...")
        else:
            print(f"  (未检索到相关内容)")
        print(f"{'='*60}\n")

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
            system_prompt, req.text, tools, knowledge_texts, history,
            user_account=_get_user(request),
        )
        source = "tool_calling"
    else:
        if intent == "闲聊":
            user_prompt = req.text
        elif knowledge_texts:
            context = "\n---\n".join(knowledge_texts)
            user_prompt = f"参考以下知识库内容回答用户问题：\n\n{context}\n\n用户问题：{req.text}"
        else:
            user_prompt = req.text

        reply = call_llm(system_prompt, user_prompt, history)
        source = "knowledge_base" if knowledge_texts else "direct"

    latency = (time.perf_counter() - t0) * 1000

    # ---- 保存到会话历史 ----
    if skey not in sessions:
        sessions[skey] = []
    sessions[skey].append({"role": "user", "content": req.text})
    sessions[skey].append({"role": "assistant", "content": reply})
    if len(sessions[skey]) > MAX_HISTORY * 2:
        sessions[skey] = sessions[skey][-MAX_HISTORY * 2:]

    return ChatResponse(
        session_id=req.session_id,
        intent=intent,
        confidence=round(float(confidence), 4),
        reply=reply,
        source=source,
        latency_ms=round(latency, 2),
        tool_calls=tool_call_log,
    )


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式对话（SSE）- TODO"""
    pass


# ================================================================
# Section P: UI 路由
# ================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """登录页面"""
    login_path = os.path.join(os.path.dirname(__file__), "static", "login.html")
    with open(login_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/", response_class=HTMLResponse)
async def ui():
    """管理控制台（需登录）"""
    ui_path = os.path.join(os.path.dirname(__file__), "static", "ui.html")
    with open(ui_path, "r", encoding="utf-8") as f:
        return f.read()


# ================================================================
# Section Q: Mock API（模拟后端接口，供 Function Calling 演示）
# ================================================================

@app.get("/mock/api/products")
@app.get("/mock/api/products/{model}")
async def mock_product(model: str = None):
    """查询产品规格（无参数返回全部）"""
    if model:
        p = MOCK_PRODUCTS.get(model)
        if p:
            return {"code": 0, "data": p}
        for k, v in MOCK_PRODUCTS.items():
            if model.lower() in k.lower():
                return {"code": 0, "data": v}
        return {"code": 404, "message": f"未找到产品型号: {model}"}
    return {"code": 0, "data": list(MOCK_PRODUCTS.values()), "total": len(MOCK_PRODUCTS)}


@app.get("/mock/api/pricing/{model}")
async def mock_pricing(model: str, quantity: int = 1):
    """查询报价"""
    p = MOCK_PRODUCTS.get(model)
    if not p:
        return {"code": 404, "message": f"未找到产品: {model}"}
    base = p["price"]
    if quantity >= 100: discount, rate = 0.85, "8.5折(100台+)"
    elif quantity >= 50: discount, rate = 0.90, "9折(50-99台)"
    elif quantity >= 10: discount, rate = 0.95, "9.5折(10-49台)"
    else: discount, rate = 1.0, "标准价"
    unit_price = round(base * discount, 2)
    return {"code": 0, "data": {
        "model": model, "quantity": quantity, "unit_price": unit_price,
        "total": round(unit_price * quantity, 2), "discount": rate,
    }}


@app.get("/mock/api/projects")
@app.get("/mock/api/projects/{project_id}/progress")
async def mock_project_progress(project_id: str = None):
    """查询项目进度（无参数返回全部）"""
    if project_id:
        p = MOCK_PROJECTS.get(project_id.upper())
        if p:
            return {"code": 0, "data": p}
        return {"code": 404, "message": f"未找到项目: {project_id}"}
    return {"code": 0, "data": list(MOCK_PROJECTS.values()), "total": len(MOCK_PROJECTS)}


@app.post("/mock/api/tickets")
async def mock_create_ticket(body: dict = Body(...)):
    """创建维修工单"""
    ticket_id = "TK" + uuid.uuid4().hex[:8].upper()
    ticket = {
        "ticket_id": ticket_id,
        "device_sn": body.get("device_sn", ""),
        "fault_description": body.get("fault_description", ""),
        "customer_name": body.get("customer_name", ""),
        "contact_phone": body.get("contact_phone", ""),
        "status": "已受理",
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
        "estimate": "工程师24小时内联系您",
    }
    MOCK_TICKETS.append(ticket)
    return {"code": 0, "data": ticket, "message": "工单创建成功"}


@app.get("/mock/api/invoices")
@app.get("/mock/api/invoices/{invoice_id}")
async def mock_invoice(invoice_id: str = None):
    """查询发票状态（无参数返回全部）"""
    if invoice_id:
        inv = MOCK_INVOICES.get(invoice_id.upper())
        if inv:
            return {"code": 0, "data": inv}
        return {"code": 404, "message": f"未找到发票: {invoice_id}"}
    return {"code": 0, "data": list(MOCK_INVOICES.values()), "total": len(MOCK_INVOICES)}


@app.get("/mock/api/payments/{reference_no}")
async def mock_payment(reference_no: str):
    """查询付款状态"""
    pay = MOCK_PAYMENTS.get(reference_no.upper())
    if pay:
        return {"code": 0, "data": pay}
    return {"code": 404, "message": f"未找到付款记录: {reference_no}"}


@app.get("/mock/api/orders/{order_id}")
async def mock_order(order_id: str):
    """查询采购订单"""
    o = MOCK_ORDERS.get(order_id.upper())
    if o:
        return {"code": 0, "data": o}
    return {"code": 404, "message": f"未找到订单: {order_id}"}


@app.get("/mock/api/sales/monthly")
async def mock_sales_monthly(year: str = "2026", months: int = 6):
    """查询各月销售额"""
    data = []
    for m in range(1, months + 1):
        key = f"{year}-{m:02d}"
        amount = MOCK_SALES.get(key, 0)
        if amount > 0:
            data.append({"month": key, "amount": amount})
        else:
            data.append({"month": key, "amount": round(350000 + m * 45000 + (m % 3) * 80000, -3)})
    total = sum(d["amount"] for d in data)
    return {"code": 0, "data": {"year": year, "monthly": data, "total": total}}


@app.get("/mock/api/sales/breakdown")
async def mock_sales_breakdown(by: str = "region"):
    """查询销售分布（按区域/产品）"""
    if by == "product":
        data = [{"name": k, "amount": v} for k, v in MOCK_SALES_BY_PRODUCT.items()]
    else:
        data = [{"name": k, "amount": v} for k, v in MOCK_SALES_BY_REGION.items()]
    total = sum(d["amount"] for d in data)
    for d in data:
        d["percent"] = round(d["amount"] / total * 100, 1)
    return {"code": 0, "data": data, "total": total}


@app.get("/mock/api/contracts")
@app.get("/mock/api/contracts/{contract_id}")
async def mock_contract(contract_id: str = None):
    """查询合同（无参数返回全部）"""
    if contract_id:
        c = MOCK_CONTRACTS.get(contract_id.upper())
        if c:
            return {"code": 0, "data": c}
        return {"code": 404, "message": f"未找到合同: {contract_id}"}
    return {"code": 0, "data": list(MOCK_CONTRACTS.values()), "total": len(MOCK_CONTRACTS)}


# ── OA办公 ──
@app.get("/mock/api/oa/tasks")
async def mock_oa_tasks():
    """查询我的待办任务"""
    return {"code": 0, "data": MOCK_OA_TASKS, "total": len(MOCK_OA_TASKS)}


@app.get("/mock/api/oa/leave-balance")
async def mock_leave_balance(username: str = "admin"):
    """查询假期余额"""
    data = MOCK_LEAVE_BALANCE.get(username, {"name": username, "annual_leave_remain": 10, "sick_leave_remain": 5, "personal_leave_remain": 3})
    return {"code": 0, "data": data}


# ── 企业知识 ──
@app.get("/mock/api/company/org")
async def mock_org_structure():
    """查询组织架构"""
    return {"code": 0, "data": MOCK_COMPANY_INFO["organization"]}


@app.get("/mock/api/company/policies")
@app.get("/mock/api/company/policies/{name}")
async def mock_policy(name: str = None):
    """查询企业制度（无参数返回全部）"""
    if name:
        for p in MOCK_COMPANY_INFO["policies"]:
            if name in p["name"]:
                return {"code": 0, "data": p}
        return {"code": 404, "message": f"未找到制度: {name}"}
    return {"code": 0, "data": MOCK_COMPANY_INFO["policies"], "total": len(MOCK_COMPANY_INFO["policies"])}


@app.get("/mock/api/suppliers")
async def mock_suppliers(category: str = None, grade: str = None):
    """查询供应商"""
    result = MOCK_SUPPLIERS
    if category:
        result = [s for s in result if category in s["category"]]
    if grade:
        result = [s for s in result if s["grade"] == grade.upper()]
    return {"code": 0, "data": result, "total": len(result)}


# ================================================================
# Section R: 健康检查
# ================================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "intent_model": registry.status["intent_loaded"],
        "embedding_model": registry.status["embedding_loaded"],
        "kb_chunks": registry.status["kb_chunks"],
        "intent_categories": len(dm.list_intents()),
        "uploaded_docs": len(dm.list_documents()),
        "tool_count": len(tool_manager.list_tools()),
        "user_count": len(auth_db.list_users()),
        "role_count": len(auth_db.list_roles()),
    }


# ================================================================
# Section S: 启动
# ================================================================

# 初始化数据库并同步管理员权限
auth_db.init_db()
auth_db.grant_all_tools_to_admin([t["name"] for t in tool_manager.list_tools()])

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
