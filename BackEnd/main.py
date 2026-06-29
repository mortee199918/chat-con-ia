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
MAX_AI_HISTORY = 20  # máximo de mensajes enviados a DeepSeek (10 intercambios)


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
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id    TEXT NOT NULL,
                username   TEXT NOT NULL DEFAULT 'unknown',
                from_type  TEXT NOT NULL DEFAULT 'user',
                content    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Migración: añadir columnas nuevas si la tabla ya existía con el schema antiguo
        for col, definition in [
            ("username",   "TEXT NOT NULL DEFAULT 'unknown'"),
            ("from_type",  "TEXT NOT NULL DEFAULT 'user'"),
            ("created_at", "TEXT DEFAULT (datetime('now'))"),
        ]:
            try:
                db.execute(f"ALTER TABLE messages ADD COLUMN {col} {definition}")
            except Exception:
                pass  # La columna ya existe


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


# ── Gestor de conexiones WebSocket ──────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, Dict[str, WebSocket]] = {}

    def _ensure_room(self, room_id: str):
        if room_id not in self.connections:
            self.connections[room_id] = {}

    def room_exists_in_db(self, room_id: str) -> bool:
        with get_db() as db:
            return db.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)).fetchone() is not None

    def load_conversation(self, room_id: str) -> list:
        """Reconstruye el historial en formato OpenAI para enviar a DeepSeek.
        Solo se envían los últimos MAX_AI_HISTORY mensajes para no superar
        el límite de tokens ni encarecer las peticiones."""
        system_msg = {
            "role": "system",
            "content": "Eres un asistente útil y amigable. Responde siempre en el idioma que te hablen.",
        }
        with get_db() as db:
            rows = db.execute(
                """SELECT from_type, content FROM messages
                   WHERE room_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (room_id, MAX_AI_HISTORY),
            ).fetchall()
        # Revertir para mantener orden cronológico
        rows = list(reversed(rows))
        conv = [system_msg]
        for r in rows:
            role = "assistant" if r["from_type"] == "ai" else "user"
            conv.append({"role": role, "content": r["content"]})
        return conv

    def load_history(self, room_id: str) -> list:
        """Devuelve los mensajes guardados en formato para el frontend."""
        with get_db() as db:
            rows = db.execute(
                "SELECT username, from_type, content, created_at FROM messages WHERE room_id = ? ORDER BY id",
                (room_id,),
            ).fetchall()
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

    def save_message(self, room_id: str, username: str, from_type: str, content: str):
        with get_db() as db:
            db.execute(
                "INSERT INTO messages (room_id, username, from_type, content) VALUES (?, ?, ?, ?)",
                (room_id, username, from_type, content),
            )

    async def connect(self, room_id: str, username: str, websocket: WebSocket):
        await websocket.accept()
        self._ensure_room(room_id)

        # Enviar historial solo al usuario que se conecta
        history = self.load_history(room_id)
        if history:
            await websocket.send_text(json.dumps({"type": "history", "messages": history}))

        self.connections[room_id][username] = websocket

        # Notificar a todos que llegó alguien nuevo
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
            (room_id, req.name, req.type),
        )
    return {"id": room_id, "name": req.name, "type": req.type}


# ── WebSocket endpoint ──────────────────────────────────────────

@app.websocket("/ws/{room_id}/{username}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, username: str):
    if not manager.room_exists_in_db(room_id):
        await websocket.close(code=4004)
        return

    # Validar nombre duplicado
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

    with get_db() as db:
        room = db.execute("SELECT type FROM rooms WHERE id = ?", (room_id,)).fetchone()
    room_type = room["type"]

    await manager.connect(room_id, username, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            content = json.loads(data).get("content", "")

            # Guardar y difundir el mensaje del usuario
            manager.save_message(room_id, username, "user", content)
            await manager.broadcast(room_id, {
                "type": "message",
                "content": content,
                "username": username,
                "from": "user",
            })

            # Si es sala de IA, pedir respuesta a DeepSeek
            if room_type == "ai":
                conv = manager.load_conversation(room_id)

                await manager.broadcast(room_id, {
                    "type": "typing", "content": "", "username": "DeepSeek AI", "from": "ai",
                })

                try:
                    reply = await ask_deepseek(conv)
                    manager.save_message(room_id, "DeepSeek AI", "ai", reply)
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
