"""
用户 & 角色管理 API（RBAC）
"""
from fastapi import APIRouter, HTTPException, Request, Body
from ..shared import check_auth, tool_manager
from .. import auth_db

router = APIRouter()


@router.get("/users")
async def list_users(request: Request):
    """列出所有用户（需管理员权限）"""
    if not check_auth(request):
        raise HTTPException(status_code=401)
    return {"users": auth_db.list_users()}


@router.post("/users")
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


@router.put("/users/{username}")
async def update_user(username: str, body: dict = Body(...), request: Request = None):
    """更新用户"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.update_user(username, **body)


@router.delete("/users/{username}")
async def delete_user(username: str, request: Request = None):
    """删除用户"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.delete_user(username)


@router.get("/roles")
async def list_roles(request: Request):
    """列出所有角色"""
    if not check_auth(request):
        raise HTTPException(status_code=401)
    roles = auth_db.list_roles()
    # 附加每个角色的工具权限
    for r in roles:
        r["permissions"] = list(auth_db.get_role_tool_permissions(r["name"]))
    return {"roles": roles}


@router.post("/roles")
async def create_role(body: dict = Body(...), request: Request = None):
    """创建角色"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.create_role(
        name=body.get("name", ""),
        description=body.get("description", ""),
    )


@router.delete("/roles/{name}")
async def delete_role(name: str, request: Request = None):
    """删除角色"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.delete_role(name)


@router.get("/roles/{name}/permissions")
async def get_role_permissions(name: str, request: Request = None):
    """获取角色的工具权限"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return {
        "role": name,
        "tools": list(auth_db.get_role_tool_permissions(name)),
        "all_tools": [t["name"] for t in tool_manager.list_tools()],
    }


@router.put("/roles/{name}/permissions")
async def set_role_permissions(name: str, body: dict = Body(...), request: Request = None):
    """设置角色的工具权限"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401)
    return auth_db.set_role_tool_permissions(name, body.get("tools", []))
