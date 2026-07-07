"""
Mock 数据 — 统一数据源

main.py（HTTP API 端点）和 tool_manager.py（Function Calling 直接执行）共用这份数据，
避免两份硬编码数据不一致。

修改数据时只需改这一个文件。
"""

# ── 产品数据 ──
MOCK_PRODUCTS = {
    "X2000-Standard": {
        "model": "X2000-Standard", "name": "工业传感器标准版",
        "range": "0-1000 N·m", "precision": "0.5% FS", "response": "<10ms",
        "voltage": "DC 12-36V", "output": "4-20mA / RS485",
        "protection": "IP65", "temperature": "-20°C ~ +70°C", "price": 3800,
    },
    "X2000-Pro": {
        "model": "X2000-Pro", "name": "工业传感器专业版",
        "range": "0-2000 N·m", "precision": "0.1% FS", "response": "<5ms",
        "voltage": "DC 12-36V", "output": "4-20mA / RS485 / CAN / 以太网",
        "protection": "IP67", "temperature": "-40°C ~ +85°C", "price": 6800,
        "features": "IoT 云平台接入、内置自诊断",
    },
    "X2000-Ultra": {
        "model": "X2000-Ultra", "name": "工业传感器旗舰版",
        "range": "0-5000 N·m", "precision": "0.05% FS", "response": "<2ms",
        "voltage": "DC 12-36V", "output": "全协议支持",
        "protection": "IP68", "temperature": "-55°C ~ +125°C", "price": 15800,
        "features": "ATEX/IECEx 防爆认证",
    },
    "K-500E": {
        "model": "K-500E", "name": "智能控制器经济型",
        "cpu": "ARM Cortex-A72 四核 1.8GHz", "memory": "4GB",
        "io_points": 256, "ethernet": "2路", "ai": "不支持", "price": 12000,
    },
    "K-500S": {
        "model": "K-500S", "name": "智能控制器标准型",
        "cpu": "ARM Cortex-A72 四核 1.8GHz", "memory": "4GB",
        "io_points": 512, "ethernet": "2路", "ai": "轻量", "price": 18500,
    },
    "K-500P": {
        "model": "K-500P", "name": "智能控制器旗舰型",
        "cpu": "ARM Cortex-A72 四核 1.8GHz", "memory": "4GB",
        "io_points": 1024, "ethernet": "4路", "ai": "全支持", "price": 32000,
    },
}

# ── 项目数据 ──
MOCK_PROJECTS = {
    "PRJ2026-001": {
        "id": "PRJ2026-001", "name": "某石化工厂智能化改造",
        "progress": "实施部署阶段", "percent": 65,
        "milestones": [
            {"name": "需求调研", "done": True}, {"name": "方案设计", "done": True},
            {"name": "设备安装", "done": True}, {"name": "系统调试", "done": False},
            {"name": "培训上线", "done": False}, {"name": "项目验收", "done": False},
        ],
        "next": "系统调试（预计7月20日开始）", "pm": "张工", "contact": "13800138001",
    },
    "PRJ2026-002": {
        "id": "PRJ2026-002", "name": "某电力公司状态监测系统",
        "progress": "方案设计阶段", "percent": 30,
        "milestones": [
            {"name": "需求调研", "done": True}, {"name": "方案设计", "done": False},
            {"name": "设备安装", "done": False}, {"name": "系统调试", "done": False},
            {"name": "项目验收", "done": False},
        ],
        "next": "方案评审（7月25日）", "pm": "李工", "contact": "13900139002",
    },
}

# ── 工单数据 ──
MOCK_TICKETS = []

# ── 订单数据 ──
MOCK_ORDERS = {
    "PO20260601": {
        "id": "PO20260601", "supplier": "某电子科技有限公司",
        "items": [{"name": "传感器芯片", "qty": 500, "unit": "颗"}, {"name": "PCB板", "qty": 200, "unit": "块"}],
        "total": 126000, "status": "已发货", "eta": "2026-07-15", "logistics": "顺丰 SF1234567890",
    },
    "PO20260615": {
        "id": "PO20260615", "supplier": "某精密机械厂",
        "items": [{"name": "不锈钢外壳", "qty": 100, "unit": "套"}],
        "total": 58000, "status": "生产中", "eta": "2026-07-28",
    },
    "PO20260701": {
        "id": "PO20260701", "supplier": "某线缆有限公司",
        "items": [{"name": "屏蔽信号线", "qty": 2000, "unit": "米"}, {"name": "电源线", "qty": 1000, "unit": "米"}],
        "total": 35000, "status": "已入库", "eta": "2026-07-05",
    },
}

# ── 供应商数据 ──
MOCK_SUPPLIERS = [
    {"name": "某电子科技有限公司", "category": "电子元器件", "grade": "A", "cooperation": "5年", "rating": 4.8, "contact": "王经理 13500135001"},
    {"name": "某精密机械厂", "category": "机械加工", "grade": "A", "cooperation": "3年", "rating": 4.5, "contact": "陈经理 13600136001"},
    {"name": "某线缆有限公司", "category": "电气材料", "grade": "B", "cooperation": "2年", "rating": 4.2, "contact": "赵经理 13700137001"},
    {"name": "某自动化设备公司", "category": "自动化设备", "grade": "A", "cooperation": "6年", "rating": 4.9, "contact": "刘经理 13800138002"},
    {"name": "某包装材料厂", "category": "包装材料", "grade": "C", "cooperation": "1年", "rating": 3.8, "contact": "孙经理 13900139003"},
]

# ── 发票数据 ──
MOCK_INVOICES = {
    "INV2026-0620": {"id": "INV2026-0620", "type": "增值税专用发票", "amount": 68000, "status": "已开出", "date": "2026-06-22", "number": "4401234567"},
    "INV2026-0701": {"id": "INV2026-0701", "type": "增值税普通发票", "amount": 12500, "status": "开具中", "date": "", "number": ""},
}

# ── 付款数据 ──
MOCK_PAYMENTS = {
    "PAY2026-001": {"id": "PAY2026-001", "amount": 68000, "status": "已到账", "date": "2026-06-25"},
    "PAY2026-002": {"id": "PAY2026-002", "amount": 30000, "status": "待确认", "date": ""},
}

# ── 销售数据 ──
MOCK_SALES = {
    "2026-01": 285000, "2026-02": 312000, "2026-03": 458000,
    "2026-04": 523000, "2026-05": 489000, "2026-06": 556000,
    "2026-07": 0,  # 当月实时
    "2025-01": 210000, "2025-02": 235000, "2025-03": 340000,
    "2025-04": 395000, "2025-05": 372000, "2025-06": 418000,
    "2025-07": 445000, "2025-08": 432000, "2025-09": 508000,
    "2025-10": 526000, "2025-11": 589000, "2025-12": 672000,
}

MOCK_SALES_BY_REGION = {
    "华东": 1850000, "华南": 1420000, "华北": 980000,
    "西南": 720000, "西北": 450000, "华中": 680000, "东北": 390000,
}

MOCK_SALES_BY_PRODUCT = {
    "X2000系列": 2850000, "K-500系列": 2100000, "SOP系列": 980000, "配件": 560000,
}

# ── 合同数据 ──
MOCK_CONTRACTS = {
    "CT2026-001": {
        "id": "CT2026-001", "name": "某石化工厂智能化改造合同",
        "party_a": "某石化公司", "party_b": "我司",
        "amount": 8500000, "status": "执行中",
        "sign_date": "2026-01-15", "expiry_date": "2027-01-14",
        "key_terms": ["付款方式: 3-3-3-1", "质保期: 2年", "违约责任: 日万分之三"],
    },
    "CT2026-002": {
        "id": "CT2026-002", "name": "某电力公司状态监测系统合同",
        "party_a": "某电力公司", "party_b": "我司",
        "amount": 3200000, "status": "签订中",
        "sign_date": "", "expiry_date": "",
        "key_terms": ["付款方式: 3-6-1", "质保期: 3年", "违约责任: 日万分之五"],
    },
}

# ── OA办公数据 ──
MOCK_OA_TASKS = [
    {"id": "TASK-001", "title": "Q3 销售报告审核", "type": "审批", "from": "销售部-王经理", "deadline": "2026-07-08", "status": "待处理", "priority": "高"},
    {"id": "TASK-002", "title": "新员工入职培训安排", "type": "任务", "from": "HR-李主管", "deadline": "2026-07-10", "status": "进行中", "priority": "中"},
    {"id": "TASK-003", "title": "X2000采购合同盖章申请", "type": "审批", "from": "采购部-赵工", "deadline": "2026-07-07", "status": "待处理", "priority": "高"},
    {"id": "TASK-004", "title": "7月团队建设活动方案", "type": "任务", "from": "行政部-孙经理", "deadline": "2026-07-15", "status": "待处理", "priority": "低"},
    {"id": "TASK-005", "title": "项目验收报告提交", "type": "任务", "from": "PM-张工", "deadline": "2026-07-12", "status": "进行中", "priority": "高"},
]

MOCK_LEAVE_BALANCE = {
    "admin": {"name": "管理员", "annual_leave_total": 15, "annual_leave_used": 3, "annual_leave_remain": 12, "sick_leave_remain": 5, "personal_leave_remain": 3},
}

# ── 企业知识数据 ──
MOCK_COMPANY_INFO = {
    "organization": {
        "departments": [
            {"name": "研发部", "floor": "5楼", "head": "李总监", "count": 45, "responsibility": "产品研发、技术攻关、专利管理"},
            {"name": "销售部", "floor": "3楼", "head": "王总监", "count": 32, "responsibility": "市场开拓、客户关系、销售业绩"},
            {"name": "财务部", "floor": "4楼", "head": "陈总监", "count": 12, "responsibility": "财务管理、成本核算、税务筹划"},
            {"name": "人力资源部", "floor": "4楼", "head": "刘总监", "count": 8, "responsibility": "招聘培训、薪酬福利、绩效考核"},
            {"name": "采购部", "floor": "3楼", "head": "赵总监", "count": 15, "responsibility": "供应商管理、采购执行、成本控制"},
            {"name": "行政部", "floor": "2楼", "head": "孙经理", "count": 10, "responsibility": "办公环境、资产管理、后勤保障"},
            {"name": "项目管理部", "floor": "5楼", "head": "张总监", "count": 20, "responsibility": "项目规划、进度管控、资源协调"},
        ]
    },
    "policies": [
        {"name": "考勤制度", "summary": "弹性工作制，核心工作时间 10:00-16:00，每日工作时长不少于 8 小时", "detail": "迟到 30 分钟内不扣薪，月度累计迟到超 3 次按次扣款 50 元"},
        {"name": "请假制度", "summary": "年假 15 天/年，病假需提供医院证明，事假需提前 1 天申请", "detail": "3 天以内由直属领导审批，3-7 天需部门总监审批，7 天以上需 HR 总监审批"},
        {"name": "报销制度", "summary": "差旅费实报实销，市内交通月结，招待费需提前申请", "detail": "单笔 500 元以下由部门经理审批，500-5000 元需总监审批，5000 元以上需副总审批"},
        {"name": "加班制度", "summary": "工作日加班 1.5 倍工资，周末 2 倍，法定节假日 3 倍", "detail": "加班需提前在 OA 系统申请并经审批，未经审批的加班不计入加班费"},
        {"name": "晋升机制", "summary": "年度两次晋升窗口（3月、9月），需满足绩效 B+ 以上且任职满 1 年", "detail": "晋升流程：自荐/推荐→部门评审→HR审核→晋升答辩→公示→生效"},
    ],
}
