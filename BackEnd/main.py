from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import json
import os
import uuid
import sqlite3
import asyncio
from contextlib import contextmanager
from dotenv import load_dotenv
from typing import Dict

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
TURSO_URL        = os.getenv("TURSO_URL", "")   # libsql://xxx.turso.io
TURSO_TOKEN      = os.getenv("TURSO_TOKEN", "")
MAX_AI_HISTORY   = 20


# ── Capa de base de datos ───────────────────────────────────────
#
# Turso ofrece una API HTTP REST — no necesitamos ningún paquete
# nativo. Usamos httpx (ya instalado) para enviar SQL directamente
# a sus servidores.
#
# Si TURSO_URL no está configurado (desarrollo local) caemos a
# sqlite3 con un archivo local.

def _turso_http_url() -> str:
    return TURSO_URL.replace("libsql://", "https://")

def _turso_fmt(val):
    if val is None:      return {"type": "null"}
    if isinstance(val, int):   return {"type": "integer", "value": str(val)}
    if isinstance(val, float): return {"type": "float",   "value": val}
    return {"type": "text", "value": str(val)}

def _turso_val(cell) -> object:
    return None if cell["type"] == "null" else cell.get("value")

async def _turso_request(sql: str, args: list) -> dict:
    payload = {
        "requests": [
            {"type": "execute", "stmt": {
                "sql": sql,
                "args": [_turso_fmt(a) for a in args],
            }},
            {"type": "close"},
        ]
    }
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{_turso_http_url()}/v2/pipeline",
            json=payload,
            headers=headers,
        )
        r.raise_for_status()
    return r.json()["results"][0]


async def db_select(sql: str, args: list = []) -> list[dict]:
    """Ejecuta un SELECT y devuelve lista de dicts {col: valor}."""
    if TURSO_URL and TURSO_TOKEN:
        res = await _turso_request(sql, args)
        if res["type"] != "ok":
            return []
        er = res["response"]["result"]
        cols = [c["name"] for c in er["cols"]]
        return [{cols[i]: _turso_val(r[i]) for i in range(len(cols))} for r in er["rows"]]
    else:
        # Fallback SQLite local (datos efímeros, solo para dev)
        def _q():
            conn = sqlite3.connect("chat.db")
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(sql, args).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
        return await asyncio.to_thread(_q)


async def db_run(sql: str, args: list = [], ignore_errors: bool = False) -> None:
    """Ejecuta INSERT / UPDATE / DELETE / CREATE / ALTER."""
    if TURSO_URL and TURSO_TOKEN:
        res = await _turso_request(sql, args)
        if res["type"] != "ok" and not ignore_errors:
            raise Exception(res.get("error", {}).get("message", "Turso error"))
    else:
        def _q():
            conn = sqlite3.connect("chat.db")
            try:
                conn.execute(sql, args)
                conn.commit()
            except Exception:
                if not ignore_errors:
                    raise
            finally:
                conn.close()
        await asyncio.to_thread(_q)


async def init_db():
    await db_run("""
        CREATE TABLE IF NOT EXISTS rooms (
            id   TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL
        )
    """)
    await db_run("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id    TEXT NOT NULL,
            username   TEXT NOT NULL DEFAULT 'unknown',
            from_type  TEXT NOT NULL DEFAULT 'user',
            content    TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    # Migración: añadir columnas si la tabla ya existía sin ellas
    for col, definition in [
        ("username",   "TEXT NOT NULL DEFAULT 'unknown'"),
        ("from_type",  "TEXT NOT NULL DEFAULT 'user'"),
        ("created_at", "TEXT DEFAULT (datetime('now'))"),
    ]:
        await db_run(
            f"ALTER TABLE messages ADD COLUMN {col} {definition}",
            ignore_errors=True,
        )


@app.on_event("startup")
async def startup():
    await init_db()


# ── IA ──────────────────────────────────────────────────────────

async def ask_deepseek(messages: list[dict]) -> str:
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": "deepseek-chat", "messages": messages, "stream": False}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(DEEPSEEK_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


# ── Gestor de conexiones WebSocket ──────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, Dict[str, WebSocket]] = {}
        self._pending_cleanup: Dict[str, asyncio.Task] = {}

    def _ensure_room(self, room_id: str):
        if room_id not in self.connections:
            self.connections[room_id] = {}

    async def room_exists_in_db(self, room_id: str) -> bool:
        rows = await db_select("SELECT id FROM rooms WHERE id = ?", [room_id])
        return len(rows) > 0

    async def load_conversation(self, room_id: str) -> list:
        system_msg = {
            "role": "system",
            "content": "Eres un asistente útil y amigable. Responde siempre en el idioma que te hablen.",
        }
        rows = await db_select(
            "SELECT from_type, content FROM messages WHERE room_id = ? ORDER BY id DESC LIMIT ?",
            [room_id, MAX_AI_HISTORY],
        )
        rows = list(reversed(rows))
        conv = [system_msg]
        for r in rows:
            role = "assistant" if r["from_type"] == "ai" else "user"
            conv.append({"role": role, "content": r["content"]})
        return conv

    async def load_history(self, room_id: str) -> list:
        rows = await db_select(
            "SELECT username, from_type, content, created_at FROM messages WHERE room_id = ? ORDER BY id",
            [room_id],
        )
        return [
            {
                "type": "message",
                "username": r["username"],
                "from": r["from_type"],
                "content": r["content"],
                "timestamp": r["created_at"],
            }
            for r in rows
        ]

    async def save_message(self, room_id: str, username: str, from_type: str, content: str):
        await db_run(
            "INSERT INTO messages (room_id, username, from_type, content) VALUES (?, ?, ?, ?)",
            [room_id, username, from_type, content],
        )

    def schedule_cleanup(self, room_id: str) -> None:
        if room_id in self._pending_cleanup:
            self._pending_cleanup[room_id].cancel()

        async def do_cleanup():
            await asyncio.sleep(30)
            if not self.get_users(room_id):
                await db_run("DELETE FROM messages WHERE room_id = ?", [room_id])
                await db_run("DELETE FROM rooms WHERE id = ?", [room_id])
                self.connections.pop(room_id, None)
            self._pending_cleanup.pop(room_id, None)

        self._pending_cleanup[room_id] = asyncio.create_task(do_cleanup())

    async def connect(self, room_id: str, username: str, websocket: WebSocket):
        if room_id in self._pending_cleanup:
            self._pending_cleanup[room_id].cancel()
            self._pending_cleanup.pop(room_id, None)

        await websocket.accept()
        self._ensure_room(room_id)

        history = await self.load_history(room_id)
        if history:
            await websocket.send_text(json.dumps({"type": "history", "messages": history}))

        self.connections[room_id][username] = websocket

        await self.broadcast(room_id, {
            "type": "system",
            "content": f"{username} se ha unido al chat",
            "username": "Sistema",
            "from": "system",
            "users": list(self.connections[room_id].keys()),
        })

    def disconnect(self, room_id: str, username: str):
        if room_id in self.connections:
            self.connections[room_id].pop(username, None)

    def get_users(self, room_id: str) -> list:
        return list(self.connections.get(room_id, {}).keys())

    async def broadcast(self, room_id: str, message: dict):
        if room_id not in self.connections:
            return
        dead = []
        for uname, ws in self.connections[room_id].items():
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(uname)
        for uname in dead:
            self.connections[room_id].pop(uname, None)


manager = ConnectionManager()


# ── HTTP endpoints ──────────────────────────────────────────────

@app.get("/")
def health_check():
    return {"status": "ok"}


@app.get("/rooms")
async def get_rooms():
    rows = await db_select("SELECT id, name, type FROM rooms ORDER BY rowid DESC")
    return [
        {"id": r["id"], "name": r["name"], "type": r["type"], "users": manager.get_users(r["id"])}
        for r in rows
    ]


@app.get("/rooms/{room_id}")
async def get_room(room_id: str):
    rows = await db_select("SELECT id, name, type FROM rooms WHERE id = ?", [room_id])
    if not rows:
        raise HTTPException(status_code=404, detail="Room not found")
    r = rows[0]
    return {"id": r["id"], "name": r["name"], "type": r["type"], "users": manager.get_users(r["id"])}


class CreateRoomRequest(BaseModel):
    name: str
    type: str


@app.post("/rooms")
async def create_room(req: CreateRoomRequest):
    room_id = str(uuid.uuid4())[:8].upper()
    await db_run(
        "INSERT INTO rooms (id, name, type) VALUES (?, ?, ?)",
        [room_id, req.name, req.type],
    )
    return {"id": room_id, "name": req.name, "type": req.type}


# ── WebSocket endpoint ──────────────────────────────────────────

@app.websocket("/ws/{room_id}/{username}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, username: str):
    if not await manager.room_exists_in_db(room_id):
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "type": "error",
            "content": "Esta sala no existe o ha sido eliminada. Vuelve al lobby.",
            "username": "Sistema",
            "from": "system",
        }))
        await websocket.close(code=4004)
        return

    if username in manager.get_users(room_id):
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "type": "error",
            "content": f"El nombre '{username}' ya está en uso en esta sala. Vuelve al lobby y elige otro.",
            "username": "Sistema",
            "from": "system",
        }))
        await websocket.close(code=4001)
        return

    rows = await db_select("SELECT type FROM rooms WHERE id = ?", [room_id])
    room_type = rows[0]["type"]

    await manager.connect(room_id, username, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            content = json.loads(data).get("content", "")

            await manager.save_message(room_id, username, "user", content)
            await manager.broadcast(room_id, {
                "type": "message",
                "content": content,
                "username": username,
                "from": "user",
            })

            if room_type == "ai":
                conv = await manager.load_conversation(room_id)
                await manager.broadcast(room_id, {
                    "type": "typing", "content": "", "username": "DeepSeek AI", "from": "ai",
                })
                try:
                    reply = await ask_deepseek(conv)
                    await manager.save_message(room_id, "DeepSeek AI", "ai", reply)
                    await manager.broadcast(room_id, {
                        "type": "message",
                        "content": reply,
                        "username": "DeepSeek AI",
                        "from": "ai",
                    })
                except Exception as e:
                    await manager.broadcast(room_id, {
                        "type": "error",
                        "content": f"Error con la IA: {str(e)}",
                        "username": "Sistema",
                        "from": "system",
                    })

    except WebSocketDisconnect:
        manager.disconnect(room_id, username)
        remaining = manager.get_users(room_id)
        await manager.broadcast(room_id, {
            "type": "system",
            "content": f"{username} ha salido del chat",
            "username": "Sistema",
            "from": "system",
            "users": remaining,
        })
        if not remaining:
            manager.schedule_cleanup(room_id)
