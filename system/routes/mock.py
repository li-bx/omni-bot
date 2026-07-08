"""
Mock API — 模拟后端接口，供 Function Calling 演示
"""
import time
import uuid
from fastapi import APIRouter, Body
from ..mock_data import (
    MOCK_PRODUCTS, MOCK_PROJECTS, MOCK_TICKETS, MOCK_ORDERS,
    MOCK_SUPPLIERS, MOCK_INVOICES, MOCK_PAYMENTS, MOCK_CONTRACTS,
    MOCK_SALES, MOCK_SALES_BY_REGION, MOCK_SALES_BY_PRODUCT,
    MOCK_OA_TASKS, MOCK_LEAVE_BALANCE, MOCK_COMPANY_INFO,
)

router = APIRouter()


@router.get("/mock/api/products")
@router.get("/mock/api/products/{model}")
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


@router.get("/mock/api/pricing/{model}")
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


@router.get("/mock/api/projects")
@router.get("/mock/api/projects/{project_id}/progress")
async def mock_project_progress(project_id: str = None):
    """查询项目进度（无参数返回全部）"""
    if project_id:
        p = MOCK_PROJECTS.get(project_id.upper())
        if p:
            return {"code": 0, "data": p}
        return {"code": 404, "message": f"未找到项目: {project_id}"}
    return {"code": 0, "data": list(MOCK_PROJECTS.values()), "total": len(MOCK_PROJECTS)}


@router.post("/mock/api/tickets")
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


@router.get("/mock/api/invoices")
@router.get("/mock/api/invoices/{invoice_id}")
async def mock_invoice(invoice_id: str = None):
    """查询发票状态（无参数返回全部）"""
    if invoice_id:
        inv = MOCK_INVOICES.get(invoice_id.upper())
        if inv:
            return {"code": 0, "data": inv}
        return {"code": 404, "message": f"未找到发票: {invoice_id}"}
    return {"code": 0, "data": list(MOCK_INVOICES.values()), "total": len(MOCK_INVOICES)}


@router.get("/mock/api/payments/{reference_no}")
async def mock_payment(reference_no: str):
    """查询付款状态"""
    pay = MOCK_PAYMENTS.get(reference_no.upper())
    if pay:
        return {"code": 0, "data": pay}
    return {"code": 404, "message": f"未找到付款记录: {reference_no}"}


@router.get("/mock/api/orders/{order_id}")
async def mock_order(order_id: str):
    """查询采购订单"""
    o = MOCK_ORDERS.get(order_id.upper())
    if o:
        return {"code": 0, "data": o}
    return {"code": 404, "message": f"未找到订单: {order_id}"}


@router.get("/mock/api/sales/monthly")
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


@router.get("/mock/api/sales/breakdown")
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


@router.get("/mock/api/contracts")
@router.get("/mock/api/contracts/{contract_id}")
async def mock_contract(contract_id: str = None):
    """查询合同（无参数返回全部）"""
    if contract_id:
        c = MOCK_CONTRACTS.get(contract_id.upper())
        if c:
            return {"code": 0, "data": c}
        return {"code": 404, "message": f"未找到合同: {contract_id}"}
    return {"code": 0, "data": list(MOCK_CONTRACTS.values()), "total": len(MOCK_CONTRACTS)}


# ── OA办公 ──
@router.get("/mock/api/oa/tasks")
async def mock_oa_tasks():
    """查询我的待办任务"""
    return {"code": 0, "data": MOCK_OA_TASKS, "total": len(MOCK_OA_TASKS)}


@router.get("/mock/api/oa/leave-balance")
async def mock_leave_balance(username: str = "admin"):
    """查询假期余额"""
    data = MOCK_LEAVE_BALANCE.get(username, {"name": username, "annual_leave_remain": 10, "sick_leave_remain": 5, "personal_leave_remain": 3})
    return {"code": 0, "data": data}


# ── 企业知识 ──
@router.get("/mock/api/company/org")
async def mock_org_structure():
    """查询组织架构"""
    return {"code": 0, "data": MOCK_COMPANY_INFO["organization"]}


@router.get("/mock/api/company/policies")
@router.get("/mock/api/company/policies/{name}")
async def mock_policy(name: str = None):
    """查询企业制度（无参数返回全部）"""
    if name:
        for p in MOCK_COMPANY_INFO["policies"]:
            if name in p["name"]:
                return {"code": 0, "data": p}
        return {"code": 404, "message": f"未找到制度: {name}"}
    return {"code": 0, "data": MOCK_COMPANY_INFO["policies"], "total": len(MOCK_COMPANY_INFO["policies"])}


@router.get("/mock/api/suppliers")
async def mock_suppliers(category: str = None, grade: str = None):
    """查询供应商"""
    result = MOCK_SUPPLIERS
    if category:
        result = [s for s in result if category in s["category"]]
    if grade:
        result = [s for s in result if s["grade"] == grade.upper()]
    return {"code": 0, "data": result, "total": len(result)}
