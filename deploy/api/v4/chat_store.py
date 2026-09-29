"""
MedButler 会话存储模块（自包含）

- 存储：SQLite chat.db（同目录）
- 表：conversations（会话，按 username 隔离）、messages（消息，按 conversation_id 隔离）
- 记忆：build_context 取最近 N 轮（默认 5 轮 = 10 条）作为模型上下文
"""
import os
import secrets
import shutil
import sqlite3
from datetime import datetime

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_APP_DIR, "chat.db")
MEDIA_DIR = os.path.join(_APP_DIR, "media")  # 上传图片落盘根目录（按会话分子目录）

MEMORY_ROUNDS = 5  # 模型携带的对话记忆轮数
MAX_CONVERSATIONS = 50  # 每用户会话数量上限，超出自动删最旧（含消息）


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS conversations(
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '新对话',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id)")
    # 旧库兼容迁移：messages 加 image_path 列（存上传图片的相对路径，空串=无图）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    if "image_path" not in cols:
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN image_path TEXT NOT NULL DEFAULT ''")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    return conn


def create_conversation(username: str, title: str = "新对话") -> str:
    conv_id = secrets.token_hex(8)
    now = _now()
    conn = _db()
    conn.execute(
        "INSERT INTO conversations(id, username, title, created_at, updated_at) VALUES(?,?,?,?,?)",
        (conv_id, username, title, now, now),
    )
    # 上限裁剪：只保留该用户最近 MAX_CONVERSATIONS 条，被挤掉的连同消息一起删
    # （rowid 作 tie-break：同一秒内建多条时按插入序保留最新的）
    conn.execute(
        """DELETE FROM messages WHERE conv_id IN (
            SELECT id FROM conversations
            WHERE username=? AND id NOT IN (
                SELECT id FROM conversations WHERE username=? ORDER BY updated_at DESC, rowid DESC LIMIT ?
            )
        )""",
        (username, username, MAX_CONVERSATIONS),
    )
    conn.execute(
        """DELETE FROM conversations WHERE username=? AND id NOT IN (
            SELECT id FROM conversations WHERE username=? ORDER BY updated_at DESC, rowid DESC LIMIT ?
        )""",
        (username, username, MAX_CONVERSATIONS),
    )
    conn.commit()
    conn.close()
    return conv_id


def list_conversations(username: str) -> list[dict]:
    conn = _db()
    rows = conn.execute(
        "SELECT id, title, updated_at FROM conversations WHERE username=? ORDER BY updated_at DESC LIMIT 50",
        (username,),
    ).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]


def conversation_owner(conv_id: str) -> str | None:
    conn = _db()
    row = conn.execute("SELECT username FROM conversations WHERE id=?", (conv_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def touch_conversation(conv_id: str, first_message: str | None = None):
    """更新会话活跃时间；首轮消息顺便把它设为会话标题（截 20 字）。"""
    conn = _db()
    if first_message:
        row = conn.execute("SELECT title FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if row and row[0] == "新对话":
            title = first_message.strip().replace("\n", " ")[:20] or "新对话"
            conn.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, _now(), conv_id))
            conn.commit()
            conn.close()
            return
    conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conv_id))
    conn.commit()
    conn.close()


def delete_conversation(username: str, conv_id: str) -> bool:
    conn = _db()
    row = conn.execute("SELECT username FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not row or row[0] != username:
        conn.close()
        return False
    conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
    conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    conn.commit()
    conn.close()
    # 会话没了，它的上传图片目录一并清掉（只动 media/<conv_id>，不碰其它）
    shutil.rmtree(os.path.join(MEDIA_DIR, conv_id), ignore_errors=True)
    return True


def save_image(conv_id: str, data: bytes, ext: str) -> str:
    """上传图片落盘到 media/<conv_id>/<随机名>.<ext>，返回相对路径（供消息表与媒体接口用）。"""
    ext = ext.lower().lstrip(".")
    if ext not in ("jpg", "jpeg", "png", "webp", "gif", "bmp"):
        ext = "jpg"
    fname = f"{secrets.token_hex(12)}.{ext}"
    dest_dir = os.path.join(MEDIA_DIR, conv_id)
    os.makedirs(dest_dir, exist_ok=True)
    with open(os.path.join(dest_dir, fname), "wb") as f:
        f.write(data)
    return f"{conv_id}/{fname}"


def media_file(rel_path: str) -> str | None:
    """按相对路径取媒体文件绝对路径；防目录穿越（必须落在 MEDIA_DIR 内）。"""
    rel = os.path.normpath(rel_path).replace("\\", "/").lstrip("/")
    if rel.startswith("..") or os.path.isabs(rel):
        return None
    abs_path = os.path.abspath(os.path.join(MEDIA_DIR, rel))
    if os.path.commonpath([abs_path, os.path.abspath(MEDIA_DIR)]) != os.path.abspath(MEDIA_DIR):
        return None
    return abs_path if os.path.isfile(abs_path) else None


def add_message(conv_id: str, role: str, content: str, image_path: str = ""):
    conn = _db()
    conn.execute(
        "INSERT INTO messages(conv_id, role, content, created_at, image_path) VALUES(?,?,?,?,?)",
        (conv_id, role, content, _now(), image_path),
    )
    conn.commit()
    conn.close()


def get_messages(conv_id: str) -> list[dict]:
    conn = _db()
    rows = conn.execute(
        "SELECT role, content, created_at, image_path FROM messages WHERE conv_id=? ORDER BY id",
        (conv_id,),
    ).fetchall()
    conn.close()
    return [
        {"role": r[0], "content": r[1], "created_at": r[2], "image_path": r[3]}
        for r in rows
    ]


def build_context(conv_id: str, rounds: int = MEMORY_ROUNDS) -> list[dict]:
    """取最近 N 轮（N*2 条）消息作为模型上下文，按时间正序返回。"""
    conn = _db()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?",
        (conv_id, rounds * 2),
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
