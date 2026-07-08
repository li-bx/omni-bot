"""
HTMX UI 路由 — 返回 HTML 片段供 HTMX 前端使用
所有端点检查 HX-Request 或不强制检查，返回预处理好的 HTML
"""
import os
import html as html_mod
import json as _json
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form, Body
from fastapi.responses import HTMLResponse, PlainTextResponse
from typing import Optional

from ..shared import (
    dm, tm, registry, tool_manager, tokens, sessions, MAX_HISTORY,
    check_auth, _get_user, _get_user_role, _session_key,
    jinja,
)
from .. import auth_db
from ..prompts import load_prompts, save_prompts
from ..chat_pipeline import run_chat_pipeline
from ..config import scan_upload_documents

router = APIRouter(prefix="/ui")

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _hx_redirect(url: str) -> HTMLResponse:
    """让 HTMX 客户端跳转到指定 URL"""
    return HTMLResponse(content="", headers={"HX-Redirect": url})

def _hx_refresh() -> HTMLResponse:
    """让 HTMX 客户端刷新当前页面"""
    return HTMLResponse(content="", headers={"HX-Refresh": "true"})

def _hx_trigger(*events: str) -> dict:
    """返回自定义事件触发头"""
    return {"HX-Trigger": ", ".join(events)}

def _require_auth(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="请先登录")

def _tag(label: str, cls: str = "gray") -> str:
    return f'<span class="tag tag-{cls}">{html_mod.escape(label)}</span>'

def _badge(label: str, icon: str = "", cls: str = "gray") -> str:
    ico = f"{icon} " if icon else ""
    return f'<span class="tag tag-{cls}">{ico}{html_mod.escape(label)}</span>'

def _btn(label: str, cls: str = "btn-outline", **attrs) -> str:
    a = " ".join(f'{k}="{html_mod.escape(str(v), True)}"' for k, v in attrs.items())
    return f'<button class="btn {cls}" {a}>{label}</button>'

def _status_dot(on: bool) -> str:
    c = "on" if on else "off"
    return f'<span class="status-pulse {c}"></span>'

def _spinner() -> str:
    return '<span class="loading"></span>'

def _progress_bar(pct: float) -> str:
    p = max(0, min(100, int(pct * 100)))
    return f'<div class="progress-bar" style="width:200px;display:inline-block;vertical-align:middle"><div class="fill" style="width:{p}%"></div></div>'

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@router.get("/chat/empty", response_class=HTMLResponse)
async def chat_empty(request: Request):
    """返回空对话状态（欢迎提示 + 建议列表）"""
    raw = [
        ("📋", "OA办公", "我的待办任务有哪些"),
        ("🏢", "企业知识", "公司的组织架构是怎样的"),
        ("🔍", "产品对比", "X2000-Pro 和 K-500S 有什么区别"),
        ("💰", "销售报价", "批量采购 10 台 X2000 什么价格"),
        ("📈", "销售图表", "今年Q2华东区X2000销售额和趋势"),
        ("📊", "项目进度", "我们项目现在到什么阶段了"),
        ("🔧", "故障报修", "设备报 E05 通信超时怎么排查"),
        ("🧾", "发票查询", "我们的发票什么时候能开出来"),
        ("🏭", "供应商管理", "帮我查下供应商有哪些 A 级的"),
        ("📦", "采购订单", "PO20260601 采购订单货到哪了"),
        ("🛡️", "售后政策", "产品保修期是多久怎么延保"),
        ("📋", "合同条款", "合同里的违约责任条款怎么约定"),
        ("🔄", "退换货", "我要退货已经收到货了怎么操作"),
    ]
    suggestions = [
        {
            "icon": icon,
            "label": label,
            "text": q,
            "hx_vals": _json.dumps({"text": q}, ensure_ascii=False),
        }
        for icon, label, q in raw
    ]
    tmpl = jinja.get_template("chat/empty.html")
    return HTMLResponse(tmpl.render(request=request, suggestions=suggestions))


@router.post("/chat", response_class=HTMLResponse)
async def chat_ui(request: Request, text: str = Form(...), session_id: str = Form("default")):
    """处理对话 — 返回 user + assistant 消息 HTML 附加到聊天区"""
    # ---- auth（必须在此处理，管线只抛 HTTPException）----
    if not check_auth(request):
        return _hx_redirect("/login")

    # ---- 执行共享管线 ----
    result = await run_chat_pipeline(request, text, session_id)

    # ---- 渲染 Markdown ----
    try:
        import markdown as md_lib
        rendered = md_lib.markdown(result.reply, extensions=["fenced_code", "tables", "nl2br"])
    except Exception:
        rendered = html_mod.escape(result.reply).replace("\n", "<br>")

    tmpl = jinja.get_template("chat/message_pair.html")
    return HTMLResponse(tmpl.render(
        request=request,
        reply=result.reply,
        rendered_reply=rendered,
        intent=result.intent,
        source=result.source,
        latency_ms=result.latency_ms,
        tool_call_log=result.tool_call_log,
    ))


@router.delete("/chat/session/{session_id}", response_class=HTMLResponse)
async def clear_chat_ui(request: Request, session_id: str):
    """清空会话 — 返回空对话 HTML"""
    skey = _session_key(request, session_id)
    sessions.pop(skey, None)
    # Return empty chat via redirect to the empty endpoint
    return HTMLResponse(
        content="",
        headers={
            "HX-Trigger": "clearChat",
        },
    )

# ---------------------------------------------------------------------------
# Health / System
# ---------------------------------------------------------------------------

@router.get("/health", response_class=HTMLResponse)
async def health_ui():
    """返回系统状态指标 HTML"""
    h = {
        "intent_model": registry.status["intent_loaded"],
        "embedding_model": registry.status["embedding_loaded"],
        "kb_chunks": registry.status["kb_chunks"],
        "tool_count": len(tool_manager.list_tools()),
    }
    metrics = [
        (str(len(dm.list_intents())), "意图类别"),
        (str(len(dm.list_documents())), "知识库文档"),
        (str(h["kb_chunks"]), "知识库段落"),
        (str(h["tool_count"]), "API 工具"),
        ("已加载" if h["intent_model"] else "未加载", "意图模型"),
        ("已加载" if h["embedding_model"] else "未加载", "检索模型"),
    ]
    tmpl = jinja.get_template("system/health.html")
    return HTMLResponse(tmpl.render(
        intent_model=h["intent_model"], embedding_model=h["embedding_model"],
        kb_chunks=h["kb_chunks"], tool_count=h["tool_count"],
        metrics=metrics, jobs=tm.list_jobs(),
    ))


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_ui():
    """返回训练任务列表 HTML"""
    tmpl = jinja.get_template("system/jobs.html")
    return HTMLResponse(tmpl.render(jobs=tm.list_jobs()))


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_status_ui(job_id: str):
    """返回单个训练任务状态 HTML"""
    j = tm.get_job(job_id)
    if not j:
        return HTMLResponse('<span class="tag tag-red">任务不存在</span>')
    status_cls = "green" if j["status"] == "completed" else "red" if j["status"] == "failed" else "blue"
    bar = _progress_bar(j.get("progress", 0)) if j["status"] not in ("completed", "failed") else ""
    return HTMLResponse(
        f'<span class="tag tag-{status_cls}">{html_mod.escape(j["status"])}</span> '
        f'{html_mod.escape(j.get("message",""))} {bar}'
    )

# ---------------------------------------------------------------------------
# Intents & Samples
# ---------------------------------------------------------------------------

@router.get("/intents", response_class=HTMLResponse)
async def intents_ui():
    """返回意图类别 chip 列表 HTML"""
    intents = dm.list_intents()
    priority = ["OA办公", "企业知识"]
    intents.sort(key=lambda i: (
        priority.index(i["name"]) if i["name"] in priority else 99,
        i["name"]
    ))
    tmpl = jinja.get_template("data/intents.html")
    return HTMLResponse(tmpl.render(intents=intents))


@router.post("/intents", response_class=HTMLResponse)
async def add_intent_ui(request: Request, name: str = Form(...)):
    """添加意图 — 刷新意图列表"""
    _require_auth(request)
    dm.add_intent(name)
    # return updated list
    return await intents_ui()


@router.delete("/intents/{name}", response_class=HTMLResponse)
async def delete_intent_ui(request: Request, name: str):
    """删除意图 — 刷新意图列表"""
    _require_auth(request)
    dm.delete_intent(name)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "intentDeleted"},
    )


@router.get("/samples/{intent}", response_class=HTMLResponse)
async def samples_ui(intent: str):
    """返回样本列表 HTML"""
    r = dm.get_samples(intent, limit=200)
    samples = r.get("samples", [])
    total = r.get("total", 0)
    tmpl = jinja.get_template("data/samples.html")
    return HTMLResponse(tmpl.render(samples=samples, total=total, intent=intent))


@router.post("/samples/{intent}", response_class=HTMLResponse)
async def add_samples_ui(request: Request, intent: str, texts: str = Form(...)):
    """添加样本"""
    _require_auth(request)
    lines = [t.strip() for t in texts.split("\n") if t.strip()]
    dm.add_samples(intent, lines)
    return await samples_ui(intent)


@router.delete("/samples/{intent}", response_class=HTMLResponse)
async def delete_samples_ui(request: Request, intent: str, idx: str = Form("", alias="idx")):
    """删除样本 — idx 可多选"""
    _require_auth(request)
    # idx comes from form checkboxes with same name
    # FastAPI Form doesn't handle multi-value well, parse from request
    import json as _json
    body = await request.body()
    from urllib.parse import parse_qs
    params = parse_qs(body.decode("utf-8"))
    idx_values = params.get("idx", [])
    idx_list = [int(i) for i in idx_values if i.strip().isdigit()]
    if not idx_list:
        # try query param fallback
        return HTMLResponse('<span style="color:var(--danger)">未选择样本</span>')

    dm.delete_samples(intent, idx_list)
    return await samples_ui(intent)


@router.post("/samples/{intent}/generate", response_class=HTMLResponse)
async def generate_samples_ui(request: Request, intent: str):
    """LLM 自动生成样本"""
    _require_auth(request)
    try:
        import requests as req_lib
        from ..config import get_api_key, DEEPSEEK_API_URL

        existing = dm.get_samples(intent, limit=1000)
        existing_texts = [s["text"] for s in existing.get("samples", [])]

        if not existing_texts:
            return HTMLResponse('<span style="color:var(--danger)">需要先手动添加 5-10 条种子样本</span>')

        seeds_str = "\n".join(f"- {t}" for t in existing_texts[:10])
        prompt = f"""以下是一些 AI 企业数智化"{intent}"意图的问句示例：

{seeds_str}

请生成 30 个全新的、不同于以上任何一条的"{intent}"意图问句。
要求：
- 涵盖该意图下的不同子场景
- 模拟真实用户的表达方式（不要太标准）
- 长度从3个字到30个字不等
- 每行一个，不要编号"""

        resp = req_lib.post(
            DEEPSEEK_API_URL,
            headers={"Authorization": f"Bearer {get_api_key()}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.9, "max_tokens": 2048},
            timeout=30,
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        new_texts = [t.strip() for t in content.split("\n") if t.strip()
                     and not t.startswith("-") and not t.startswith(("1.", "2."))]
        result = dm.add_samples(intent, new_texts)

    except Exception as e:
        return HTMLResponse(f'<span style="color:var(--danger)">生成失败: {html_mod.escape(str(e))}</span>')

    return await samples_ui(intent)


@router.get("/samples/{intent}/prompt", response_class=HTMLResponse)
async def prompt_ui(intent: str):
    """返回 System Prompt 编辑区"""
    prompts = load_prompts()
    tmpl = jinja.get_template("data/prompt.html")
    return HTMLResponse(tmpl.render(intent=intent, val=prompts.get(intent, "")))


@router.put("/samples/{intent}/prompt", response_class=HTMLResponse)
async def save_prompt_ui(request: Request, intent: str, prompt: str = Form(...)):
    """保存 System Prompt"""
    _require_auth(request)
    prompts = load_prompts()
    prompts[intent] = prompt
    save_prompts(prompts)
    return HTMLResponse(
        f'<span id="promptSaved" style="margin-left:8px;font-size:13px;color:var(--success);display:inline">已保存 ✓</span>',
        headers={"HX-Trigger": "promptSaved"},
    )


@router.post("/data/export", response_class=HTMLResponse)
async def export_data_ui(request: Request):
    """导出训练数据"""
    _require_auth(request)
    r = dm.export_as_training_data()
    return HTMLResponse(
        f'<span style="color:var(--success)">导出完成: 训练{r.get("train",0)} 验证{r.get("val",0)} 测试{r.get("test",0)}</span>'
    )

# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@router.get("/docs", response_class=HTMLResponse)
async def docs_ui():
    """返回文档列表 HTML"""
    docs = dm.list_documents()
    indexed = set(registry.get_indexed_doc_ids())
    tmpl = jinja.get_template("docs/list.html")
    return HTMLResponse(tmpl.render(docs=docs, indexed=indexed))


@router.post("/docs/upload", response_class=HTMLResponse)
async def upload_doc_ui(request: Request, file: UploadFile = File(...), domain: str = Form("通用"), new_domain: str = Form("")):
    """上传文档"""
    _require_auth(request)
    if new_domain.strip():
        domain = new_domain.strip()
    content = await file.read()
    dm.upload_document(file.filename, content, domain=domain)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshDocs"},
    )


@router.delete("/docs/{doc_id}", response_class=HTMLResponse)
async def delete_doc_ui(request: Request, doc_id: str):
    """删除文档"""
    _require_auth(request)
    dm.delete_document(doc_id)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshDocs"},
    )


@router.post("/docs/add-to-kb", response_class=HTMLResponse)
async def add_to_kb_ui(request: Request):
    """增量加入知识库"""
    _require_auth(request)
    body = await request.form()
    filenames = body.getlist("filename")
    if not filenames:
        return HTMLResponse(content="", headers={"HX-Trigger": "toastError", "HX-Reswap": "none"})
    r = registry.add_docs_to_kb(filenames)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshDocs, toastOk"},
    )


@router.get("/domains", response_class=HTMLResponse)
async def domains_ui():
    """返回领域选择下拉选项"""
    entries = scan_upload_documents()
    domains = sorted(set(e["domain"] for e in entries))
    opts = "\n".join(f'<option value="{html_mod.escape(d, True)}">{html_mod.escape(d)}</option>' for d in domains)
    return HTMLResponse(opts)

# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

@router.post("/train/intent", response_class=HTMLResponse)
async def train_intent_ui(request: Request):
    """启动意图训练"""
    _require_auth(request)
    r = tm.train_intent({})
    return HTMLResponse(
        f'<span class="tag tag-blue">启动</span> 任务: {html_mod.escape(r.get("job_id","?"))}',
        headers={"HX-Trigger": "trainStarted"},
    )


@router.post("/train/embedding", response_class=HTMLResponse)
async def train_embedding_ui(request: Request):
    """启动 Embedding 训练"""
    _require_auth(request)
    r = tm.train_embedding()
    return HTMLResponse(
        f'<span class="tag tag-blue">启动</span> 任务: {html_mod.escape(r.get("job_id","?"))}',
        headers={"HX-Trigger": "trainStarted"},
    )


@router.post("/models/reload", response_class=HTMLResponse)
async def reload_models_ui(request: Request):
    """重新加载模型"""
    _require_auth(request)
    registry.load_all()
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "modelsReloaded"},
    )


@router.post("/models/rebuild-kb", response_class=HTMLResponse)
async def rebuild_kb_ui(request: Request):
    """重建知识库索引"""
    _require_auth(request)
    r = registry.rebuild_kb()
    chunks = r.get("chunks", 0)
    return HTMLResponse(
        f'<span class="tag tag-green">完成</span> {chunks} 个段落',
        headers={"HX-Trigger": "kbRebuilt"},
    )

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@router.get("/tools", response_class=HTMLResponse)
async def tools_ui():
    """返回工具列表 HTML"""
    tools = tool_manager.list_tools()
    tmpl = jinja.get_template("tools/list.html")
    return HTMLResponse(tmpl.render(tools=tools))


@router.get("/tools/form", response_class=HTMLResponse)
async def tool_form_empty():
    """返回空白工具表单 HTML"""
    all_intents = [i["name"] for i in dm.list_intents()]
    tmpl = jinja.get_template("tools/form.html")
    return HTMLResponse(tmpl.render(tool=None, all_intents=all_intents, sel_intents=set()))


@router.get("/tools/{name}", response_class=HTMLResponse)
async def tool_edit_form(name: str):
    """返回预填的工具编辑表单"""
    tool = tool_manager.get_tool(name)
    if not tool:
        return HTMLResponse('<span style="color:var(--danger)">工具不存在</span>')

    all_intents = [i["name"] for i in dm.list_intents()]
    sel_intents = set(tool.get("intents", []))
    ac = tool.get("api_config", {}) or {}

    params_json = __import__("json").dumps(tool.get("parameters", {}), ensure_ascii=False, indent=2)
    headers_json = __import__("json").dumps(ac.get("headers", {}), ensure_ascii=False, indent=2)

    tmpl = jinja.get_template("tools/form.html")
    return HTMLResponse(tmpl.render(
        tool=tool,
        all_intents=all_intents,
        sel_intents=sel_intents,
        headers_json=headers_json,
        params_json=params_json,
    ))


@router.post("/tools", response_class=HTMLResponse)
async def add_tool_ui(request: Request):
    """添加工具"""
    _require_auth(request)
    form = await request.form()
    intents = form.getlist("intent")
    try:
        headers = __import__("json").loads(form.get("headers", "{}"))
    except Exception:
        return HTMLResponse(f'<span style="color:var(--danger)">请求头 JSON 格式错误</span>')

    try:
        parameters = __import__("json").loads(form.get("parameters", '{"type":"object","properties":{},"required":[]}'))
    except Exception:
        return HTMLResponse(f'<span style="color:var(--danger)">参数定义 JSON 格式错误</span>')

    body = {
        "name": form.get("name", ""),
        "description": form.get("description", ""),
        "type": form.get("type", "api"),
        "intents": intents,
        "api_config": {
            "method": form.get("method", "GET"),
            "url_template": form.get("url_template", ""),
            "headers": headers,
            "query_params": [],
            "body_fields": list(parameters.get("properties", {}).keys()),
        },
        "parameters": parameters,
    }
    result = tool_manager.add_tool(body)
    if not result.get("ok"):
        return HTMLResponse(f'<span style="color:var(--danger)">{html_mod.escape(result.get("error","失败"))}</span>')
    return await tools_ui()


@router.put("/tools/{name}", response_class=HTMLResponse)
async def update_tool_ui(request: Request, name: str):
    """更新工具"""
    _require_auth(request)
    form = await request.form()
    intents = form.getlist("intent")
    try:
        headers = __import__("json").loads(form.get("headers", "{}"))
    except Exception:
        return HTMLResponse(f'<span style="color:var(--danger)">请求头 JSON 格式错误</span>')
    try:
        parameters = __import__("json").loads(form.get("parameters", '{"type":"object","properties":{},"required":[]}'))
    except Exception:
        return HTMLResponse(f'<span style="color:var(--danger)">参数定义 JSON 格式错误</span>')

    body = {
        "name": form.get("name", name),
        "description": form.get("description", ""),
        "type": form.get("type", "api"),
        "intents": intents,
        "api_config": {
            "method": form.get("method", "GET"),
            "url_template": form.get("url_template", ""),
            "headers": headers,
            "query_params": [],
            "body_fields": list(parameters.get("properties", {}).keys()),
        },
        "parameters": parameters,
    }
    result = tool_manager.update_tool(name, body)
    if not result.get("ok"):
        return HTMLResponse(f'<span style="color:var(--danger)">{html_mod.escape(result.get("error","失败"))}</span>')
    return await tools_ui()


@router.delete("/tools/{name}", response_class=HTMLResponse)
async def delete_tool_ui(request: Request, name: str):
    """删除工具"""
    _require_auth(request)
    tool_manager.delete_tool(name)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshTools"},
    )


@router.post("/tools/reload", response_class=HTMLResponse)
async def reload_tools_ui(request: Request):
    """重载工具配置"""
    _require_auth(request)
    tool_manager.reload()
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshTools"},
    )

# ---------------------------------------------------------------------------
# Users & Roles
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def users_ui(request: Request):
    """返回用户列表 HTML"""
    _require_auth(request)
    users = auth_db.list_users()
    for u in users:
        u["created_at"] = str(u.get("created_at", ""))[:10]
    tmpl = jinja.get_template("users/list.html")
    return HTMLResponse(tmpl.render(users=users))


@router.get("/users/{username}/form", response_class=HTMLResponse)
async def user_edit_form(request: Request, username: str):
    """返回用户编辑表单"""
    _require_auth(request)
    all_users = auth_db.list_users()
    u = next((x for x in all_users if x["username"] == username), None)
    if not u:
        return HTMLResponse('<span style="color:var(--danger)">用户不存在</span>')
    tmpl = jinja.get_template("users/form.html")
    return HTMLResponse(tmpl.render(user=u, roles=auth_db.list_roles()))


@router.post("/users", response_class=HTMLResponse)
async def create_user_ui(request: Request):
    """创建用户"""
    _require_auth(request)
    form = await request.form()
    try:
        auth_db.create_user(
            username=form.get("username", ""),
            password=form.get("password", ""),
            display_name=form.get("display_name", form.get("username", "")),
            role_name=form.get("role_name", "管理员"),
        )
    except Exception as e:
        return HTMLResponse(f'<span style="color:var(--danger)">{html_mod.escape(str(e))}</span>')
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshUsers"},
    )


@router.put("/users/{username}", response_class=HTMLResponse)
async def update_user_ui(request: Request, username: str):
    """更新用户"""
    _require_auth(request)
    form = await request.form()
    kwargs = {}
    if form.get("display_name"):
        kwargs["display_name"] = form.get("display_name")
    if form.get("password"):
        kwargs["password"] = form.get("password")
    if form.get("role_name"):
        kwargs["role_name"] = form.get("role_name")
    auth_db.update_user(username, **kwargs)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshUsers"},
    )


@router.delete("/users/{username}", response_class=HTMLResponse)
async def delete_user_ui(request: Request, username: str):
    """删除用户"""
    _require_auth(request)
    auth_db.delete_user(username)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshUsers"},
    )


@router.get("/users/form", response_class=HTMLResponse)
async def user_create_form(request: Request):
    """返回空白用户创建表单"""
    _require_auth(request)
    tmpl = jinja.get_template("users/form.html")
    return HTMLResponse(tmpl.render(user=None, roles=auth_db.list_roles()))


@router.get("/roles", response_class=HTMLResponse)
async def roles_ui(request: Request):
    """返回角色列表 HTML"""
    _require_auth(request)
    tmpl = jinja.get_template("users/roles.html")
    return HTMLResponse(tmpl.render(roles=auth_db.list_roles()))


@router.post("/roles", response_class=HTMLResponse)
async def create_role_ui(request: Request):
    """创建角色"""
    _require_auth(request)
    form = await request.form()
    name = form.get("name", "").strip()
    if not name:
        return HTMLResponse('<span style="color:var(--danger)">角色名不能为空</span>')
    auth_db.create_role(name=name, description=form.get("description", ""))
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshRoles"},
    )


@router.delete("/roles/{name}", response_class=HTMLResponse)
async def delete_role_ui(request: Request, name: str):
    """删除角色"""
    _require_auth(request)
    auth_db.delete_role(name)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshRoles"},
    )


@router.get("/roles/{name}/permissions", response_class=HTMLResponse)
async def role_permissions_ui(request: Request, name: str):
    """返回角色权限编辑面板"""
    _require_auth(request)
    allowed = set(auth_db.get_role_tool_permissions(name))
    all_tools = [t["name"] for t in tool_manager.list_tools()]
    tmpl = jinja.get_template("users/permissions.html")
    return HTMLResponse(tmpl.render(name=name, allowed=allowed, all_tools=all_tools))


@router.put("/roles/{name}/permissions", response_class=HTMLResponse)
async def save_role_permissions_ui(request: Request, name: str):
    """保存角色权限"""
    _require_auth(request)
    form = await request.form()
    tools = form.getlist("tool")
    auth_db.set_role_tool_permissions(name, tools)
    return HTMLResponse(
        content="",
        headers={"HX-Trigger": "refreshRoles"},
    )
