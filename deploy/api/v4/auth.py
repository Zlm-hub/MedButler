"""
MedButler v4 用户认证模块（自包含，不动报告解读主流程）

- 存储：SQLite users.db（同目录，已 gitignore）
- 密码：PBKDF2-HMAC-SHA256（10 万轮 + 16 字节随机盐）
- 会话：HMAC-SHA256 签名 cookie（无服务端会话表，AUTH_SECRET 不变则重启不掉线）
- 角色：admin / user；管理员账号在首次启动时从 .env 的 ADMIN_USERNAME/ADMIN_PASSWORD 播种
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from config import cfg

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_APP_DIR, "users.db")
COOKIE_NAME = "medbutler_session"
SESSION_TTL = cfg.SESSION_TTL_HOURS * 3600

# 签名密钥：.env 未配置则生成并写回（下次重启沿用）
AUTH_SECRET = cfg.AUTH_SECRET
if not AUTH_SECRET:
    AUTH_SECRET = secrets.token_hex(32)
    try:
        with open(os.path.join(_APP_DIR, ".env"), "a", encoding="utf-8") as f:
            f.write(f"\n# 会话签名密钥（自动生成；更换后所有登录失效）\nAUTH_SECRET={AUTH_SECRET}\n")
    except OSError:
        pass


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )"""
    )
    # 迁移：新增 is_active 列（首次启动或老库；已有列则跳过）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    if "is_active" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    return conn


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(_hash_password(password, salt), stored)


def _sign(raw: str) -> str:
    return hmac.new(AUTH_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()


def _make_token(username: str, role: str) -> str:
    payload = json.dumps(
        {"u": username, "r": role, "exp": int(time.time()) + SESSION_TTL},
        separators=(",", ":"),
    )
    raw = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{raw}.{_sign(raw)}"


def _parse_token(token: str) -> dict | None:
    try:
        raw, sig = token.split(".", 1)
        if not hmac.compare_digest(_sign(raw), sig):
            return None
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def get_current_user(request: Request) -> dict | None:
    """从请求 cookie 解析当前登录用户；供本模块与主流程（强制登录开关）共用。"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    data = _parse_token(token)
    if not data:
        return None
    conn = _db()
    row = conn.execute("SELECT username, role FROM users WHERE username=?", (data["u"],)).fetchone()
    conn.close()
    return {"username": row[0], "role": row[1]} if row else None


def _seed_admin():
    """首次启动播种管理员：.env 配了 ADMIN_USERNAME/ADMIN_PASSWORD 且库里还没有 admin 时生效。"""
    if not (cfg.ADMIN_USERNAME and cfg.ADMIN_PASSWORD):
        return
    conn = _db()
    has_admin = conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone()
    if not has_admin:
        conn.execute(
            "INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,?,'admin')",
            (cfg.ADMIN_USERNAME, _hash_password(cfg.ADMIN_PASSWORD)),
        )
        conn.commit()
    conn.close()


_seed_admin()

router = APIRouter(prefix="/api/auth")


class AuthBody(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(body: AuthBody, response: Response):
    u = body.username.strip()
    if not (3 <= len(u) <= 32) or any(c.isspace() for c in u):
        raise HTTPException(status_code=400, detail="用户名需为 3-32 位且不含空格")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO users(username,password_hash,role) VALUES(?,?,'user')",
            (u, _hash_password(body.password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="用户名已被占用")
    conn.close()
    # 注册即登录
    response.set_cookie(COOKIE_NAME, _make_token(u, "user"), httponly=True, samesite="lax", max_age=SESSION_TTL)
    return {"ok": True, "username": u, "role": "user"}


@router.post("/login")
def login(body: AuthBody, response: Response):
    u = body.username.strip()
    conn = _db()
    row = conn.execute("SELECT password_hash, role, is_active FROM users WHERE username=?", (u,)).fetchone()
    conn.close()
    if row and row[2] == 0:
        raise HTTPException(status_code=403, detail="该账号已被禁用，请联系管理员")
    if not row or not _verify_password(body.password, row[0]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    response.set_cookie(COOKIE_NAME, _make_token(u, row[1]), httponly=True, samesite="lax", max_age=SESSION_TTL)
    return {"ok": True, "username": u, "role": row[1]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    conn = _db()
    row = conn.execute("SELECT created_at FROM users WHERE username=?", (user["username"],)).fetchone()
    conn.close()
    return {**user, "created_at": row[0] if row else None}


def require_admin(request: Request) -> dict:
    """管理员鉴权：非 admin 或已登录返回 403。"""
    user = get_current_user(request)
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.get("/admin/users")
def admin_list_users(request: Request):
    require_admin(request)
    conn = _db()
    rows = conn.execute(
        "SELECT username, role, created_at, is_active FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return {"items": [
        {"username": r[0], "role": r[1], "created_at": r[2], "is_active": bool(r[3])}
        for r in rows
    ]}


@router.post("/admin/users/{username}/disable")
def admin_disable_user(username: str, request: Request):
    require_admin(request)
    conn = _db()
    target = conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
    if not target:
        conn.close(); raise HTTPException(status_code=404, detail="用户不存在")
    if target[0] == "admin":
        cnt = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0]
        if cnt <= 1:
            conn.close(); raise HTTPException(status_code=400, detail="不能禁用最后一个管理员")
    conn.execute("UPDATE users SET is_active=0 WHERE username=?", (username,))
    conn.commit(); conn.close()
    return {"ok": True}


@router.post("/admin/users/{username}/enable")
def admin_enable_user(username: str, request: Request):
    require_admin(request)
    conn = _db()
    if not conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        conn.close(); raise HTTPException(status_code=404, detail="用户不存在")
    conn.execute("UPDATE users SET is_active=1 WHERE username=?", (username,))
    conn.commit(); conn.close()
    return {"ok": True}
