"""
智能 AI 企业数智化系统 — 统一入口
启动：python -m system.main
访问：http://localhost:8000/docs

完整链路：
  用户上传数据 → 在线训练 → 模型加载 → 推理服务
  意图识别 → RAG检索 → Reranker重排 → LLM生成回答
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
import uvicorn

# ---- 共享状态（单例在此创建）----
from . import shared
from .shared import dm, tm, registry, tool_manager
from . import auth_db

# ---- 应用初始化 ----
app = FastAPI(title="AI 企业数智化系统", version="2.0.0")

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR))

# 将模板引擎注入共享模块，供各路由使用
shared.jinja = _jinja_env

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# ---- 注册路由模块 ----
from .routes.auth import router as auth_router
from .routes.users import router as users_router
from .routes.chat import router as chat_router
from .routes.data import router as data_router
from .routes.documents import router as documents_router
from .routes.training import router as training_router
from .routes.models import router as models_router
from .routes.tools import router as tools_router
from .routes.mock import router as mock_router
from .routes.ui import router as ui_router

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(chat_router)
app.include_router(data_router)
app.include_router(documents_router)
app.include_router(training_router)
app.include_router(models_router)
app.include_router(tools_router)
app.include_router(mock_router)
app.include_router(ui_router)


# ---- UI 路由 ----

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """登录页面"""
    login_path = os.path.join(os.path.dirname(__file__), "static", "login.html")
    with open(login_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/", response_class=HTMLResponse)
async def ui():
    """管理控制台（需登录）— 动态组装面板片段"""
    ui_path = os.path.join(os.path.dirname(__file__), "static", "ui.html")
    panels_dir = os.path.join(os.path.dirname(__file__), "static", "panels")

    with open(ui_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 按顺序组装所有面板
    panel_names = ["chat", "data", "docs", "train", "tools", "system", "users"]
    panel_html_parts = []
    for name in panel_names:
        panel_path = os.path.join(panels_dir, f"{name}.html")
        if os.path.isfile(panel_path):
            with open(panel_path, "r", encoding="utf-8") as f:
                panel_html_parts.append(f.read())

    html = html.replace("<!-- PANELS -->", "\n".join(panel_html_parts))
    return html


# ---- 健康检查 ----

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


# ---- 启动 ----

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
