"""
共享状态：单例、全局变量、认证/会话辅助函数
"""
import os
from .data_manager import DataManager
from .trainer import TrainingManager
from .model_registry import ModelRegistry
from .tool_manager import ToolManager
from . import auth_db

# ---- 单例 ----
dm = DataManager()
tm = TrainingManager(dm)
registry = ModelRegistry()
tool_manager = ToolManager()

# ---- 模板引擎（由 main.py 初始化）----
jinja = None  # type: Jinja2Templates | None

# ---- 全局状态 ----
tokens: dict = {}       # {token: username}
sessions: dict = {}     # {"{username}:{session_id}": [{role, content}, ...]}
MAX_HISTORY = 10        # 每次携带最近 N 轮对话


# ---- 认证辅助 ----

def _extract_token(request) -> str:
    """统一从请求中提取 token（Header > Cookie > Query）"""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("auth_token", "")
    if not token:
        token = request.query_params.get("token", "")
    return token or None


def check_auth(request) -> bool:
    """验证请求是否已登录"""
    token = _extract_token(request)
    return bool(token and token in tokens)


def _get_user(request) -> str:
    """从请求中提取当前用户名"""
    return tokens.get(_extract_token(request), "anonymous")


def _get_user_role(request) -> str:
    """获取当前用户的角色名"""
    username = _get_user(request)
    if username == "anonymous":
        return None
    user = auth_db.get_user(username)
    return user["role_name"] if user else None


# ---- 会话辅助 ----

def _session_key(request, session_id: str) -> str:
    """生成用户隔离的 session key"""
    return f"{_get_user(request)}:{session_id}"


# ---- 模型懒加载 ----
# 意图分类模型 & Embedding 模型在首次使用时自动加载（通过 property 触发）
# 显式重载请调用 POST /models/reload
