from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import json
import os
import uuid
import sqlite3
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
DB_PATH = os.getenv("DB_PATH", "chat.db")


# ── Base de datos SQLite ────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id   TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL,
                role    TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)


@app.on_event("startup")
def startup():
    init_db()


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


# ── Gestor de conexiones WebSocket (en memoria) ─────────────────

class ConnectionManager:
    def __init__(self):
        # Conexiones activas: room_id -> {username: websocket}
        self.connections: Dict[str, Dict[str, WebSocket]] = {}

    def _ensure_room(self, room_id: str):
        if room_id not in self.connections:
            self.connections[room_id] = {}

    def room_exists_in_db(self, room_id: str) -> bool:
        with get_db() as db:
            row = db.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone()
            return row is not None

    def load_conversation(self, room_id: str) -> list:
        system_msg = {
            "role": "system",
            "content": "Eres un asistente útil y amigable. Responde siempre en el idioma que te hablen.",
        }
        with get_db() as db:
            rows = db.execute(
                "SELECT role, content FROM messages WHERE room_id = ? ORDER BY id",
                (room_id,)
            ).fetchall()
        return [system_msg] + [{"role": r["role"], "content": r["content"]} for r in rows]

    def save_message(self, room_id: str, role: str, content: str):
        with get_db() as db:
            db.execute(
                "INSERT INTO messages (room_id, role, content) VALUES (?, ?, ?)",
                (room_id, role, content)
            )

    async def connect(self, room_id: str, username: str, websocket: WebSocket):
        await websocket.accept()
        self._ensure_room(room_id)
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
def get_rooms():
    with get_db() as db:
        rows = db.execute("SELECT id, name, type FROM rooms ORDER BY rowid DESC").fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "users": manager.get_users(r["id"]),
        }
        for r in rows
    ]


class CreateRoomRequest(BaseModel):
    name: str
    type: str


@app.post("/rooms")
def create_room(req: CreateRoomRequest):
    room_id = str(uuid.uuid4())[:8].upper()
    with get_db() as db:
        db.execute(
            "INSERT INTO rooms (id, name, type) VALUES (?, ?, ?)",
            (room_id, req.name, req.type)
        )
    return {"id": room_id, "name": req.name, "type": req.type}


# ── WebSocket endpoint ──────────────────────────────────────────

@app.websocket("/ws/{room_id}/{username}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, username: str):
    if not manager.room_exists_in_db(room_id):
        await websocket.close(code=4004)
        return

    with get_db() as db:
        room = db.execute("SELECT id, name, type FROM rooms WHERE id = ?", (room_id,)).fetchone()
    room_type = room["type"]

    await manager.connect(room_id, username, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            content = json.loads(data).get("content", "")

            await manager.broadcast(room_id, {
                "type": "message",
                "content": content,
                "username": username,
                "from": "user",
            })

            if room_type == "ai":
                conv = manager.load_conversation(room_id)
                conv.append({"role": "user", "content": f"{username}: {content}"})
                manager.save_message(room_id, "user", f"{username}: {content}")

                await manager.broadcast(room_id, {
                    "type": "typing", "content": "", "username": "DeepSeek AI", "from": "ai"
                })

                try:
                    reply = await ask_deepseek(conv)
                    manager.save_message(room_id, "assistant", reply)
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
        await manager.broadcast(room_id, {
            "type": "system",
            "content": f"{username} ha salido del chat",
            "username": "Sistema",
            "from": "system",
            "users": manager.get_users(room_id),
        })
