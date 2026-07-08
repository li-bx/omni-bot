"""
DeepSeek LLM 调用函数
"""
import json
import requests
from .config import get_api_key, DEEPSEEK_API_URL
from .tool_manager import ToolManager
from .shared import tool_manager, MAX_HISTORY


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
