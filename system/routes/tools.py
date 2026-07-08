"""
Function Calling 工具管理 API
"""
from fastapi import APIRouter, HTTPException, Body
from ..shared import tool_manager

router = APIRouter()


@router.get("/tools")
async def list_tools():
    """列出所有已配置的工具"""
    return {"tools": tool_manager.list_tools()}


@router.get("/tools/{name}")
async def get_tool(name: str):
    """获取单个工具定义"""
    tool = tool_manager.get_tool(name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"工具 '{name}' 不存在")
    return tool


@router.post("/tools")
async def add_tool(body: dict = Body(...)):
    """添加新工具"""
    result = tool_manager.add_tool(body)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.put("/tools/{name}")
async def update_tool(name: str, body: dict = Body(...)):
    """更新工具定义"""
    result = tool_manager.update_tool(name, body)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/tools/{name}")
async def delete_tool(name: str):
    """删除工具"""
    result = tool_manager.delete_tool(name)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/tools/intent/{intent}")
async def get_tools_for_intent(intent: str):
    """获取指定意图可用的工具列表"""
    tools = tool_manager.get_tools_for_intent(intent)
    return {"intent": intent, "tools": tools}


@router.post("/tools/reload")
async def reload_tools():
    """从磁盘重新加载工具配置"""
    return tool_manager.reload()
