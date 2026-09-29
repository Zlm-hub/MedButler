# -*- coding: utf-8 -*-
"""历史会话功能冒烟测试 v2：不依赖模型服务，只测会话管理 + 双层隔离 + 上限裁剪"""
import os
import sys
import tempfile
import secrets as _secrets

_TMP = tempfile.mkdtemp()
sys.path.insert(0, r"F:\私人健康管家\项目代码\MedButler\deploy\api\v4")

import chat_store as store
store.DB_PATH = os.path.join(_TMP, "chat.db")

from fastapi.testclient import TestClient
import fastapi_v4_ui as srv

ALICE = "alice_" + _secrets.token_hex(3)
BOB = "bob_" + _secrets.token_hex(3)
PASSED = []

def check(name, cond, extra=""):
    PASSED.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

# 独立客户端：anon（无 cookie）、alice、bob
anon = TestClient(srv.app)
alice = TestClient(srv.app)
bob = TestClient(srv.app)

check("注册 alice", alice.post("/api/auth/register", json={"username": ALICE, "password": "abc12345"}).status_code == 200)
check("注册 bob", bob.post("/api/auth/register", json={"username": BOB, "password": "abc12345"}).status_code == 200)

# --- 未登录 401 ---
check("未登录创建会话 401", anon.post("/api/chat/conversations").status_code == 401)
check("未登录列会话 401", anon.get("/api/chat/conversations").status_code == 401)

# --- alice 建会话 + 写消息 ---
r = alice.post("/api/chat/conversations")
conv1 = r.json()["id"]
check("alice 建会话", r.status_code == 200 and conv1)

store.add_message(conv1, "user", "头疼怎么办？")
store.add_message(conv1, "assistant", "建议休息多喝水。")
store.touch_conversation(conv1, first_message="头疼怎么办？")

lst = alice.get("/api/chat/conversations").json()["items"]
check("alice 列会话含标题", any(i["id"] == conv1 and i["title"] == "头疼怎么办？" for i in lst))
msgs = alice.get(f"/api/chat/conversations/{conv1}/messages").json()["messages"]
check("alice 读自己消息", len(msgs) == 2 and msgs[0]["content"] == "头疼怎么办？")

# --- build_context：32 条消息取最近 10 条 ---
for i in range(15):
    store.add_message(conv1, "user", f"q{i}")
    store.add_message(conv1, "assistant", f"a{i}")
ctx = store.build_context(conv1)
check("build_context 取最近 10 条", len(ctx) == 10 and ctx[-1]["content"] == "a14" and ctx[0]["content"] == "q10",
      f"len={len(ctx)} first={ctx[0]['content'] if ctx else None} last={ctx[-1]['content'] if ctx else None}")

# --- 用户间隔离：bob 碰 alice 的会话一律 404 ---
s1 = bob.get(f"/api/chat/conversations/{conv1}/messages").status_code
check("bob 读 alice 会话 404", s1 == 404, f"got {s1}")
s2 = bob.delete(f"/api/chat/conversations/{conv1}").status_code
check("bob 删 alice 会话 404", s2 == 404, f"got {s2}")
bitems = bob.get("/api/chat/conversations").json()["items"]
check("bob 列会话为空", bitems == [], f"got {len(bitems)} items")

# --- bob 自建自删 ---
conv2 = bob.post("/api/chat/conversations").json()["id"]
check("bob 删自己会话", bob.delete(f"/api/chat/conversations/{conv2}").json()["ok"] is True)
check("再读已删会话 404", bob.get(f"/api/chat/conversations/{conv2}/messages").status_code == 404)

# --- 50 条上限：连建 59 条（共 60 条，同一秒内靠 rowid tie-break） ---
for i in range(59):
    last_conv = store.create_conversation(ALICE)
import sqlite3
con = sqlite3.connect(store.DB_PATH)
n = con.execute("SELECT COUNT(*) FROM conversations WHERE username=?", (ALICE,)).fetchone()[0]
kept = {r[0] for r in con.execute("SELECT id FROM conversations WHERE username=?", (ALICE,)).fetchall()}
conv1_msgs = con.execute("SELECT COUNT(*) FROM messages WHERE conv_id=?", (conv1,)).fetchone()[0]
orphan = con.execute("SELECT COUNT(*) FROM messages WHERE conv_id NOT IN (SELECT id FROM conversations)").fetchone()[0]
con.close()
check("上限裁剪到 50 条", n == 50, f"got {n}")
check("最旧的 conv1 被裁掉且消息清干净", conv1 not in kept and conv1_msgs == 0)
check("最新一条保留", last_conv in kept)
check("无孤儿消息", orphan == 0)

# --- 不存在的会话 ---
check("不存在会话 owner=None", store.conversation_owner("deadbeef") is None)

print()
fails = [n for n, ok in PASSED if not ok]
print(f"共 {len(PASSED)} 项，失败 {len(fails)} 项" + (f": {fails}" if fails else "，全部通过"))
sys.exit(1 if fails else 0)
