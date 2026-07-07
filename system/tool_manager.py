"""
工具管理器：配置和管理 API 调用工具
支持为不同意图配置不同的 API 工具，集成 DeepSeek Function Calling

核心功能：
  1. 工具配置的增删改查（持久化到 JSON）
  2. 意图 → 工具的映射（不同意图可使用不同的 API）
  3. 将工具定义转为 OpenAI/DeepSeek Function Calling 格式
  4. 执行 API 工具调用（URL 参数替换、请求构造、结果返回）
"""
import json
import os
import requests
from typing import Optional, List, Dict
from .config import DATA_DIR
from .mock_data import (
    MOCK_PRODUCTS, MOCK_PROJECTS, MOCK_ORDERS,
    MOCK_SUPPLIERS, MOCK_INVOICES, MOCK_PAYMENTS, MOCK_CONTRACTS,
    MOCK_SALES, MOCK_SALES_BY_REGION, MOCK_SALES_BY_PRODUCT,
    MOCK_OA_TASKS, MOCK_LEAVE_BALANCE, MOCK_COMPANY_INFO,
)

TOOLS_FILE = os.path.join(DATA_DIR, "configs", "tools.json")

# ================================================================
# 默认示例工具（新项目首次启动时自动创建）
# ================================================================
DEFAULT_TOOLS = [
    {
        "name": "query_order_status",
        "description": "根据订单号查询订单的当前状态、物流进度和预计送达时间",
        "intents": ["订单进度查询"],
        "type": "api",
        "api_config": {
            "method": "GET",
            "url_template": "https://your-api.example.com/api/orders/{order_id}",
            "headers": {"Authorization": "Bearer YOUR_TOKEN_HERE", "Content-Type": "application/json"},
            "query_params": [],
            "body_fields": [],
        },
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "订单号，格式如 ORD20240101001",
                }
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "query_product_spec",
        "description": "根据产品型号查询产品的详细技术参数、规格和价格",
        "intents": ["产品参数查询"],
        "type": "api",
        "api_config": {
            "method": "GET",
            "url_template": "https://your-api.example.com/api/products/{model}",
            "headers": {"Authorization": "Bearer YOUR_TOKEN_HERE", "Content-Type": "application/json"},
            "query_params": [],
            "body_fields": [],
        },
        "parameters": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "产品型号，如 X2000-Pro 或 K-500",
                }
            },
            "required": ["model"],
        },
    },
    {
        "name": "create_repair_ticket",
        "description": "为创建设备维修工单",
        "intents": ["故障报修"],
        "type": "api",
        "api_config": {
            "method": "POST",
            "url_template": "https://your-api.example.com/api/tickets",
            "headers": {"Authorization": "Bearer YOUR_TOKEN_HERE", "Content-Type": "application/json"},
            "query_params": [],
            "body_fields": ["device_sn", "fault_description", "customer_name", "contact_phone"],
        },
        "parameters": {
            "type": "object",
            "properties": {
                "device_sn": {
                    "type": "string",
                    "description": "设备序列号(SN码)",
                },
                "fault_description": {
                    "type": "string",
                    "description": "故障现象描述",
                },
                "customer_name": {
                    "type": "string",
                    "description": "姓名",
                },
                "contact_phone": {
                    "type": "string",
                    "description": "联系电话",
                },
            },
            "required": ["device_sn", "fault_description"],
        },
    },
    {
        "name": "query_return_policy",
        "description": "查询产品的退换货政策和条件",
        "intents": ["售后与退换"],
        "type": "api",
        "api_config": {
            "method": "GET",
            "url_template": "https://your-api.example.com/api/return-policy",
            "headers": {"Authorization": "Bearer YOUR_TOKEN_HERE", "Content-Type": "application/json"},
            "query_params": ["product_category"],
            "body_fields": [],
        },
        "parameters": {
            "type": "object",
            "properties": {
                "product_category": {
                    "type": "string",
                    "description": "产品类别，如 传感器/控制器/显示屏",
                }
            },
            "required": [],
        },
    },
]


class ToolManager:
    """工具管理器：配置加载、CRUD、OpenAI格式转换、执行"""

    def __init__(self):
        self._tools: Dict[str, dict] = {}
        self._load()

    # ================================================================
    # 持久化
    # ================================================================

    def _load(self):
        """加载工具配置，文件不存在则用默认配置创建"""
        if os.path.exists(TOOLS_FILE):
            try:
                with open(TOOLS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for tool in data:
                        self._tools[tool["name"]] = tool
                print(f"[ToolManager] 已加载 {len(self._tools)} 个工具")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[ToolManager] 配置加载失败: {e}，使用默认配置")
                self._load_defaults()
        else:
            self._load_defaults()

    def _load_defaults(self):
        """加载默认示例工具"""
        for tool in DEFAULT_TOOLS:
            self._tools[tool["name"]] = tool
        self._save()
        print(f"[ToolManager] 已创建默认配置 ({len(self._tools)} 个示例工具，请修改 API 地址和 Token)")

    def _save(self):
        """保存工具配置到磁盘"""
        os.makedirs(os.path.dirname(TOOLS_FILE), exist_ok=True)
        with open(TOOLS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(self._tools.values()), f, ensure_ascii=False, indent=2)

    def reload(self) -> dict:
        """从磁盘重新加载配置"""
        self._tools.clear()
        self._load()
        return {"ok": True, "count": len(self._tools)}

    # ================================================================
    # CRUD
    # ================================================================

    def list_tools(self) -> list:
        """列出所有工具"""
        return list(self._tools.values())

    def get_tool(self, name: str) -> Optional[dict]:
        """获取单个工具定义"""
        return self._tools.get(name)

    def get_tools_for_intent(self, intent: str) -> list:
        """获取某个意图可用的工具列表"""
        return [
            t for t in self._tools.values()
            if intent in t.get("intents", [])
        ]

    def get_tools_for_intent_and_role(self, intent: str, role_name: str) -> list:
        """获取某个意图可用且该角色有权使用的工具列表（RBAC 过滤）"""
        from . import auth_db
        allowed = auth_db.get_role_tool_permissions(role_name)
        return [
            t for t in self._tools.values()
            if intent in t.get("intents", []) and t["name"] in allowed
        ]

    def get_tools_for_intents(self, intents: list) -> list:
        """获取多个意图可用的工具（去重）"""
        seen = set()
        result = []
        for t in self._tools.values():
            tool_intents = set(t.get("intents", []))
            if tool_intents & set(intents) and t["name"] not in seen:
                seen.add(t["name"])
                result.append(t)
        return result

    def add_tool(self, tool_def: dict) -> dict:
        """添加工具"""
        name = tool_def.get("name", "").strip()
        if not name:
            return {"ok": False, "error": "工具名称不能为空"}
        if name in self._tools:
            return {"ok": False, "error": f"工具 '{name}' 已存在"}

        # 填充默认字段
        self._normalize_tool(tool_def)
        self._tools[name] = tool_def
        self._save()
        print(f"[ToolManager] 工具已添加: {name}")
        return {"ok": True, "name": name}

    def update_tool(self, name: str, tool_def: dict) -> dict:
        """更新工具定义"""
        if name not in self._tools:
            return {"ok": False, "error": f"工具 '{name}' 不存在"}

        tool_def["name"] = name
        self._normalize_tool(tool_def)
        self._tools[name] = tool_def
        self._save()
        print(f"[ToolManager] 工具已更新: {name}")
        return {"ok": True, "name": name}

    def delete_tool(self, name: str) -> dict:
        """删除工具"""
        if name not in self._tools:
            return {"ok": False, "error": f"工具 '{name}' 不存在"}
        del self._tools[name]
        self._save()
        print(f"[ToolManager] 工具已删除: {name}")
        return {"ok": True, "name": name}

    @staticmethod
    def _call_mock(url: str, method: str, params: dict, body: dict) -> str:
        """直接调用 mock 数据，不经过 HTTP（避免服务器自调用死锁）"""
        from urllib.parse import urlparse, parse_qs
        import time as _time
        import uuid as _uuid

        parsed = urlparse(url)
        path = parsed.path
        # 合并 URL 上的 query 参数
        if parsed.query:
            for k, v in parse_qs(parsed.query).items():
                params[k] = v[0]

        try:
            # ── 产品查询 ──
            if path.startswith("/mock/api/products"):
                part = path[len("/mock/api/products"):].strip("/")
                # 空值 或 未替换的占位符 → 返回全部
                if not part or part.startswith("{"):
                    return json.dumps({"code": 0, "data": list(MOCK_PRODUCTS.values()), "total": len(MOCK_PRODUCTS)}, ensure_ascii=False)
                p = MOCK_PRODUCTS.get(part)
                if not p:
                    for k, v in MOCK_PRODUCTS.items():
                        if part.lower() in k.lower():
                            p = v; break
                return json.dumps({"code": 0, "data": p} if p else {"code": 404, "message": f"未找到: {part}"}, ensure_ascii=False)

            # ── 报价查询 ──
            if path.startswith("/mock/api/pricing/"):
                model = path.rsplit("/", 1)[-1]
                qty = int(params.get("quantity", 1))
                product = MOCK_PRODUCTS.get(model)
                base = product["price"] if product else 5000
                if qty >= 100: discount, rate = 0.85, "8.5折(100台+)"
                elif qty >= 50: discount, rate = 0.90, "9折(50-99台)"
                elif qty >= 10: discount, rate = 0.95, "9.5折(10-49台)"
                else: discount, rate = 1.0, "标准价"
                up = round(base * discount, 2)
                return json.dumps({"code": 0, "data": {"model": model, "quantity": qty, "unit_price": up, "total": round(up * qty, 2), "discount": rate}}, ensure_ascii=False)

            # ── 项目进度 ──
            if "/mock/api/projects" in path:
                rest = path.split("/mock/api/projects")[1].strip("/")
                # 空值/占位符/仅progress → 返回全部
                if not rest or rest == "progress" or rest.startswith("{"):
                    return json.dumps({"code": 0, "data": list(MOCK_PROJECTS.values()), "total": len(MOCK_PROJECTS)}, ensure_ascii=False)
                if "/progress" in rest:
                    pid = rest.split("/")[0]
                    if pid.startswith("{"):
                        return json.dumps({"code": 0, "data": list(MOCK_PROJECTS.values()), "total": len(MOCK_PROJECTS)}, ensure_ascii=False)
                    p = MOCK_PROJECTS.get(pid.upper(), {"id": pid, "progress": "未找到", "percent": 0})
                    return json.dumps({"code": 0, "data": p}, ensure_ascii=False)

            # ── 创建工单 ──
            if path == "/mock/api/tickets" and method == "POST":
                tid = "TK" + _uuid.uuid4().hex[:8].upper()
                return json.dumps({"code": 0, "data": {"ticket_id": tid, "status": "已受理", "created_at": _time.strftime("%Y-%m-%d %H:%M"), "estimate": "工程师24小时内联系您"}}, ensure_ascii=False)

            # ── 发票查询 ──
            if path.startswith("/mock/api/invoices"):
                part = path[len("/mock/api/invoices"):].strip("/")
                if not part or part.startswith("{"):
                    return json.dumps({"code": 0, "data": list(MOCK_INVOICES.values()), "total": len(MOCK_INVOICES)}, ensure_ascii=False)
                iid = part.upper()
                inv = MOCK_INVOICES.get(iid, {"id": iid, "status": "未找到"})
                return json.dumps({"code": 0, "data": inv}, ensure_ascii=False)

            # ── 付款查询 ──
            if path.startswith("/mock/api/payments/"):
                rid = path.rsplit("/", 1)[-1].upper()
                pay = MOCK_PAYMENTS.get(rid, {"id": rid, "status": "未找到"})
                return json.dumps({"code": 0, "data": pay}, ensure_ascii=False)

            # ── 采购订单 ──
            if path.startswith("/mock/api/orders/"):
                oid = path.rsplit("/", 1)[-1].upper()
                o = MOCK_ORDERS.get(oid, {"id": oid, "status": "未找到"})
                return json.dumps({"code": 0, "data": o}, ensure_ascii=False)

            # ── OA办公 ──
            if path == "/mock/api/oa/tasks":
                return json.dumps({"code": 0, "data": MOCK_OA_TASKS, "total": len(MOCK_OA_TASKS)}, ensure_ascii=False)
            if path == "/mock/api/oa/leave-balance":
                username = params.get("username", "admin")
                data = MOCK_LEAVE_BALANCE.get(username, {"name": username, "annual_leave_remain": 10, "sick_leave_remain": 5, "personal_leave_remain": 3})
                return json.dumps({"code": 0, "data": data}, ensure_ascii=False)

            # ── 企业知识 ──
            if path == "/mock/api/company/org":
                return json.dumps({"code": 0, "data": MOCK_COMPANY_INFO["organization"]}, ensure_ascii=False)
            if path.startswith("/mock/api/company/policies"):
                part = path[len("/mock/api/company/policies"):].strip("/")
                if not part or part.startswith("{"):
                    return json.dumps({"code": 0, "data": MOCK_COMPANY_INFO["policies"], "total": len(MOCK_COMPANY_INFO["policies"])}, ensure_ascii=False)
                for p in MOCK_COMPANY_INFO["policies"]:
                    if part in p["name"]:
                        return json.dumps({"code": 0, "data": p}, ensure_ascii=False)
                return json.dumps({"code": 404, "message": f"未找到制度: {part}"}, ensure_ascii=False)

            # ── 合同查询 ──
            if path.startswith("/mock/api/contracts"):
                part = path[len("/mock/api/contracts"):].strip("/")
                if not part or part.startswith("{"):
                    return json.dumps({"code": 0, "data": list(MOCK_CONTRACTS.values()), "total": len(MOCK_CONTRACTS)}, ensure_ascii=False)
                cid = part.upper()
                c = MOCK_CONTRACTS.get(cid, {"id": cid, "status": "未找到"})
                return json.dumps({"code": 0, "data": c}, ensure_ascii=False)

            # ── 供应商 ──
            if path == "/mock/api/suppliers":
                result = list(MOCK_SUPPLIERS)
                if params.get("category"):
                    result = [s for s in result if params["category"] in s["category"]]
                if params.get("grade"):
                    result = [s for s in result if s["grade"] == params["grade"].upper()]
                return json.dumps({"code": 0, "data": result, "total": len(result)}, ensure_ascii=False)

            # ── 销售月度 ──
            if path == "/mock/api/sales/monthly":
                year = params.get("year", "2026")
                months = int(params.get("months", 6))
                data = []
                for m in range(1, months + 1):
                    key = f"{year}-{m:02d}"
                    amount = MOCK_SALES.get(key, round(350000 + m * 45000 + (m % 3) * 80000, -3))
                    data.append({"month": key, "amount": amount})
                return json.dumps({"code": 0, "data": {"year": year, "monthly": data, "total": sum(d["amount"] for d in data)}}, ensure_ascii=False)

            # ── 销售分布 ──
            if path == "/mock/api/sales/breakdown":
                by = params.get("by", "region")
                if by == "product":
                    data = [{"name": k, "amount": v} for k, v in MOCK_SALES_BY_PRODUCT.items()]
                else:
                    data = [{"name": k, "amount": v} for k, v in MOCK_SALES_BY_REGION.items()]
                total = sum(d["amount"] for d in data)
                for d in data: d["percent"] = round(d["amount"] / total * 100, 1)
                return json.dumps({"code": 0, "data": data, "total": total}, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": True, "message": f"Mock执行失败: {e}"}, ensure_ascii=False)

        return json.dumps({"error": True, "message": f"未知 mock 路径: {path}"}, ensure_ascii=False)

    @staticmethod
    def _normalize_tool(tool_def: dict):
        """填充工具定义的必要默认字段"""
        tool_def.setdefault("description", "")
        tool_def.setdefault("intents", [])
        tool_def.setdefault("type", "api")
        tool_def.setdefault("parameters", {
            "type": "object", "properties": {}, "required": [],
        })
        if tool_def.get("type") == "api":
            tool_def.setdefault("api_config", {
                "method": "GET",
                "url_template": "",
                "headers": {},
                "query_params": [],
                "body_fields": [],
            })

    # ================================================================
    # OpenAI / DeepSeek Function Calling 格式转换
    # ================================================================

    @staticmethod
    def to_openai_format(tools: list) -> list:
        """
        将工具定义列表转换为 OpenAI/DeepSeek Function Calling 格式

        输入:
          [{"name": "...", "description": "...", "parameters": {...}}, ...]

        输出:
          [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}, ...]
        """
        result = []
        for t in tools:
            result.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }),
                },
            })
        return result

    # ================================================================
    # 工具执行
    # ================================================================

    def execute(self, tool_name: str, arguments: dict, user_account: str = "") -> str:
        """
        执行工具调用，返回结果字符串

        参数:
          tool_name: 工具名称
          arguments: LLM 提取的参数 dict
          user_account: 当前登录用户的账号名，会作为 X-User-Account header 转发

        返回:
          执行结果的字符串（JSON 或文本）
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return json.dumps(
                {"error": True, "message": f"工具 '{tool_name}' 不存在"},
                ensure_ascii=False,
            )

        tool_type = tool.get("type", "api")

        if tool_type == "api":
            return self._execute_api_tool(tool, arguments, user_account)
        else:
            return json.dumps(
                {"error": True, "message": f"不支持的工具类型: {tool_type}，目前仅支持 'api' 类型"},
                ensure_ascii=False,
            )

    def _execute_api_tool(self, tool: dict, arguments: dict, user_account: str = "") -> str:
        """
        执行 API 类型工具

        流程：
          1. 解析 url_template 中的 {param} 占位符 → 用 arguments 中的值替换
          2. 根据 method 和 query_params/body_fields 配置构造请求
          3. 发送 HTTP 请求
          4. 返回结果
        """
        api_config = tool.get("api_config", {})
        url_template = api_config.get("url_template", "")
        method = api_config.get("method", "GET").upper()
        headers = dict(api_config.get("headers", {}))
        # 如果当前有登录用户，将账号通过 header 转发给下游 API
        if user_account:
            headers["X-User-Account"] = user_account
        query_params = list(api_config.get("query_params", []))
        body_fields = list(api_config.get("body_fields", []))

        # ---- 1. URL 参数替换 ----
        url = url_template
        remaining_args = dict(arguments)
        for key, value in list(remaining_args.items()):
            placeholder = "{" + key + "}"
            if placeholder in url:
                url = url.replace(placeholder, str(value))
                del remaining_args[key]

        # ---- 2. 查询参数 ----
        params = {}
        if query_params:
            for key in query_params:
                if key in remaining_args:
                    params[key] = remaining_args.pop(key)
        elif method in ("GET", "DELETE"):
            # 未指定 query_params 时，GET/DELETE 的剩余参数都作为 query params
            params = dict(remaining_args)
            remaining_args = {}

        # ---- 3. 请求体 ----
        body = None
        if method in ("POST", "PUT", "PATCH"):
            if body_fields:
                body = {
                    k: remaining_args.get(k)
                    for k in body_fields
                    if k in remaining_args
                }
            elif remaining_args:
                body = dict(remaining_args)

        # ---- 4. 发送请求（mock 直调避免 HTTP 死锁）----
        print(f"[Tool执行] {tool['name']} → {method} {url}")
        if params:
            print(f"  Query: {params}")
        if body:
            body_preview = json.dumps(body, ensure_ascii=False)
            if len(body_preview) > 200:
                body_preview = body_preview[:200] + "..."
            print(f"  Body: {body_preview}")

        # localhost mock API → 直接调用，避免服务器自己调自己死锁
        if "localhost:8000/mock/api" in url or "127.0.0.1:8000/mock/api" in url:
            result = self._call_mock(url, method, params, body)
            print(f"  → mock 直调 ({len(result)} 字符)")
            return result

        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                params=params if params else None,
                json=body,
                timeout=15,
            )
            resp.encoding = resp.apparent_encoding or "utf-8"

            if resp.status_code >= 400:
                print(f"  → HTTP {resp.status_code}: {resp.text[:200]}")
                return json.dumps({
                    "error": True,
                    "status_code": resp.status_code,
                    "message": resp.text[:500],
                }, ensure_ascii=False)

            print(f"  → 成功 ({len(resp.text)} 字符)")

            # 尝试解析为 JSON，失败则返回原始文本（截断）
            try:
                return json.dumps(resp.json(), ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                return resp.text[:3000]

        except requests.Timeout:
            print(f"  → 超时")
            return json.dumps(
                {"error": True, "message": "API 请求超时（15秒）"},
                ensure_ascii=False,
            )
        except requests.RequestException as e:
            print(f"  → 网络错误: {e}")
            return json.dumps(
                {"error": True, "message": str(e)},
                ensure_ascii=False,
            )
