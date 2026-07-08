"""
认证 & 会话 API：登录、登出、用户信息、会话管理
"""
import secrets
from fastapi import APIRouter, HTTPException, Request, Body
from ..shared import tokens, _extract_token, _session_key, sessions
from .. import auth_db

router = APIRouter()


@router.post("/login")
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


@router.post("/logout")
async def logout(request: Request):
    """退出登录"""
    token = _extract_token(request)
    tokens.pop(token, None)
    return {"ok": True}


@router.get("/user/info")
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


@router.delete("/session/{session_id}")
async def clear_session(session_id: str, request: Request):
    """清除指定会话的历史"""
    key = _session_key(request, session_id)
    if key in sessions:
        del sessions[key]
        return {"ok": True, "message": f"会话 {session_id} 已清除"}
    return {"ok": False, "message": "会话不存在"}
