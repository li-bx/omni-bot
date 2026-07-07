"""
RBAC 用户角色权限管理 — SQLite 持久化

表:
  roles                  — 角色
  users                  — 用户（关联角色）
  role_tool_permissions  — 角色 → 工具权限
"""
import os
import sqlite3
import hashlib
from typing import Optional, List, Dict, Set
from contextlib import contextmanager

from .config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "configs", "auth.db")

# ================================================================
# 连接管理
# ================================================================

@contextmanager
def _conn():
    """获取数据库连接（自动提交/关闭）"""
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


# ================================================================
# 初始化
# ================================================================

def init_db():
    """建表 + 默认数据（幂等，首次运行自动创建）"""
    with _conn() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS roles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name  TEXT NOT NULL,
                role_id       INTEGER NOT NULL,
                enabled       INTEGER DEFAULT 1,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (role_id) REFERENCES roles(id)
            );

            CREATE TABLE IF NOT EXISTS role_tool_permissions (
                role_id   INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                PRIMARY KEY (role_id, tool_name),
                FOREIGN KEY (role_id) REFERENCES roles(id)
            );
        """)

    # 默认角色
    with _conn() as db:
        exist = db.execute("SELECT id FROM roles WHERE name = ?", ("管理员",)).fetchone()
        if not exist:
            db.execute(
                "INSERT INTO roles (name, description) VALUES (?, ?)",
                ("管理员", "系统管理员，拥有全部权限"),
            )
    # 默认用户
    with _conn() as db:
        exist = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
        if not exist:
            role = db.execute("SELECT id FROM roles WHERE name = ?", ("管理员",)).fetchone()
            pw = _hash("123456")
            db.execute(
                "INSERT INTO users (username, password_hash, display_name, role_id) VALUES (?,?,?,?)",
                ("admin", pw, "管理员", role["id"]),
            )

    print(f"[AuthDB] 初始化完成: {DB_PATH}")


# ================================================================
# 密码工具
# ================================================================

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return _hash(password) == password_hash


# ================================================================
# 用户 CRUD
# ================================================================

def get_user(username: str) -> Optional[dict]:
    """获取用户（含角色名和权限）"""
    with _conn() as db:
        row = db.execute(
            """SELECT u.*, r.name AS role_name
               FROM users u JOIN roles r ON u.role_id = r.id
               WHERE u.username = ? AND u.enabled = 1""",
            (username,),
        ).fetchone()
        if not row:
            return None
        user = dict(row)
        user["permissions"] = get_role_tool_permissions(user["role_name"])
        return user


def list_users() -> List[dict]:
    """列出所有用户"""
    with _conn() as db:
        rows = db.execute(
            """SELECT u.id, u.username, u.display_name, u.enabled, u.created_at,
                      r.name AS role_name
               FROM users u JOIN roles r ON u.role_id = r.id
               ORDER BY u.id"""
        ).fetchall()
        return [dict(r) for r in rows]


def create_user(username: str, password: str, display_name: str, role_name: str) -> dict:
    """创建用户，返回 {ok, error}"""
    if not username or not password:
        return {"ok": False, "error": "用户名和密码不能为空"}
    with _conn() as db:
        exist = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if exist:
            return {"ok": False, "error": f"用户 '{username}' 已存在"}
        role = db.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()
        if not role:
            return {"ok": False, "error": f"角色 '{role_name}' 不存在"}
        db.execute(
            "INSERT INTO users (username, password_hash, display_name, role_id) VALUES (?,?,?,?)",
            (username, _hash(password), display_name, role["id"]),
        )
        return {"ok": True, "username": username}


def update_user(username: str, **kwargs) -> dict:
    """更新用户字段: display_name, role_name, password, enabled"""
    with _conn() as db:
        exist = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not exist:
            return {"ok": False, "error": f"用户 '{username}' 不存在"}

        updates = {}
        if "display_name" in kwargs:
            updates["display_name"] = kwargs["display_name"]
        if "enabled" in kwargs:
            updates["enabled"] = 1 if kwargs["enabled"] else 0
        if "password" in kwargs and kwargs["password"]:
            updates["password_hash"] = _hash(kwargs["password"])
        if "role_name" in kwargs:
            role = db.execute("SELECT id FROM roles WHERE name = ?", (kwargs["role_name"],)).fetchone()
            if not role:
                return {"ok": False, "error": f"角色 '{kwargs['role_name']}' 不存在"}
            updates["role_id"] = role["id"]

        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            vals = list(updates.values()) + [username]
            db.execute(f"UPDATE users SET {sets} WHERE username = ?", vals)
        return {"ok": True, "username": username}


def delete_user(username: str) -> dict:
    """删除用户（禁止删除最后一个管理员）"""
    with _conn() as db:
        exist = db.execute(
            """SELECT u.id, r.name AS role_name
               FROM users u JOIN roles r ON u.role_id = r.id
               WHERE u.username = ?""", (username,),
        ).fetchone()
        if not exist:
            return {"ok": False, "error": f"用户 '{username}' 不存在"}
        # 不允许删除最后一个管理员
        if exist["role_name"] == "管理员":
            admin_count = db.execute(
                """SELECT COUNT(*) AS cnt FROM users u
                   JOIN roles r ON u.role_id = r.id
                   WHERE r.name = '管理员' AND u.enabled = 1"""
            ).fetchone()["cnt"]
            if admin_count <= 1:
                return {"ok": False, "error": "不能删除最后一个管理员"}
        db.execute("DELETE FROM users WHERE username = ?", (username,))
        return {"ok": True, "username": username}


# ================================================================
# 角色 CRUD
# ================================================================

def list_roles() -> List[dict]:
    """列出所有角色"""
    with _conn() as db:
        rows = db.execute(
            """SELECT r.*, COUNT(rtp.tool_name) AS tool_count
               FROM roles r
               LEFT JOIN role_tool_permissions rtp ON r.id = rtp.role_id
               GROUP BY r.id
               ORDER BY r.id"""
        ).fetchall()
        return [dict(r) for r in rows]


def create_role(name: str, description: str = "") -> dict:
    """创建角色"""
    if not name:
        return {"ok": False, "error": "角色名不能为空"}
    with _conn() as db:
        exist = db.execute("SELECT id FROM roles WHERE name = ?", (name,)).fetchone()
        if exist:
            return {"ok": False, "error": f"角色 '{name}' 已存在"}
        db.execute("INSERT INTO roles (name, description) VALUES (?,?)", (name, description))
        return {"ok": True, "name": name}


def delete_role(name: str) -> dict:
    """删除角色（禁止删除最后一个管理员角色，禁止删除有关联用户的角色）"""
    if name == "管理员":
        return {"ok": False, "error": "不能删除管理员角色"}
    with _conn() as db:
        role = db.execute("SELECT id FROM roles WHERE name = ?", (name,)).fetchone()
        if not role:
            return {"ok": False, "error": f"角色 '{name}' 不存在"}
        # 检查是否有用户关联
        users = db.execute("SELECT COUNT(*) AS cnt FROM users WHERE role_id = ?", (role["id"],)).fetchone()
        if users["cnt"] > 0:
            return {"ok": False, "error": f"角色 '{name}' 还有 {users['cnt']} 个用户，请先迁移用户"}
        db.execute("DELETE FROM role_tool_permissions WHERE role_id = ?", (role["id"],))
        db.execute("DELETE FROM roles WHERE id = ?", (role["id"],))
        return {"ok": True, "name": name}


# ================================================================
# 角色工具权限
# ================================================================

def get_role_tool_permissions(role_name: str) -> Set[str]:
    """获取角色的工具权限列表（返回 tool_name 集合）"""
    with _conn() as db:
        role = db.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()
        if not role:
            return set()
        rows = db.execute(
            "SELECT tool_name FROM role_tool_permissions WHERE role_id = ?",
            (role["id"],),
        ).fetchall()
        return {r["tool_name"] for r in rows}


def set_role_tool_permissions(role_name: str, tool_names: List[str]) -> dict:
    """全量替换角色的工具权限"""
    with _conn() as db:
        role = db.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()
        if not role:
            return {"ok": False, "error": f"角色 '{role_name}' 不存在"}
        rid = role["id"]
        db.execute("DELETE FROM role_tool_permissions WHERE role_id = ?", (rid,))
        for tn in tool_names:
            db.execute(
                "INSERT OR IGNORE INTO role_tool_permissions (role_id, tool_name) VALUES (?,?)",
                (rid, tn),
            )
        return {"ok": True, "role": role_name, "tools": tool_names}


def grant_all_tools_to_admin(tool_names: List[str]):
    """授予管理员角色所有工具权限（用于新增工具后同步）"""
    with _conn() as db:
        role = db.execute("SELECT id FROM roles WHERE name = ?", ("管理员",)).fetchone()
        if not role:
            return
        rid = role["id"]
        for tn in tool_names:
            db.execute(
                "INSERT OR IGNORE INTO role_tool_permissions (role_id, tool_name) VALUES (?,?)",
                (rid, tn),
            )
