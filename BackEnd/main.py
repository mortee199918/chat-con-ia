from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import json
import os
import uuid
from dotenv import load_dotenv
from typing import Dict

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"


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


class ConnectionManager:
    def __init__(self):
        # room_id -> { id, name, type, connections: {username: ws} }
        self.rooms: Dict[str, dict] = {}
        # room_id -> historial de conversación para la IA
        self.conversations: Dict[str, list] = {}

    def create_room(self, name: str, room_type: str) -> dict:
        room_id = str(uuid.uuid4())[:8].upper()
        self.rooms[room_id] = {
            "id": room_id,
            "name": name,
            "type": room_type,
            "connections": {},
        }
        if room_type == "ai":
            self.conversations[room_id] = [
                {
                    "role": "system",
                    "content": "Eres un asistente útil y amigable. Responde siempre en el idioma que te hablen.",
                }
            ]
        return self.rooms[room_id]

    def get_rooms(self):
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "type": r["type"],
                "users": list(r["connections"].keys()),
            }
            for r in self.rooms.values()
        ]

    async def connect(self, room_id: str, username: str, websocket: WebSocket):
        await websocket.accept()
        self.rooms[room_id]["connections"][username] = websocket
        await self.broadcast(
            room_id,
            {
                "type": "system",
                "content": f"{username} se ha unido al chat",
                "username": "Sistema",
                "from": "system",
                "users": list(self.rooms[room_id]["connections"].keys()),
            },
        )

    def disconnect(self, room_id: str, username: str):
        if room_id in self.rooms:
            self.rooms[room_id]["connections"].pop(username, None)

    async def broadcast(self, room_id: str, message: dict, exclude: str = None):
        if room_id not in self.rooms:
            return
        dead = []
        for uname, ws in self.rooms[room_id]["connections"].items():
            if uname == exclude:
                continue
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(uname)
        for uname in dead:
            self.rooms[room_id]["connections"].pop(uname, None)

    async def send_to(self, room_id: str, username: str, message: dict):
        ws = self.rooms[room_id]["connections"].get(username)
        if ws:
            await ws.send_text(json.dumps(message))


manager = ConnectionManager()


# ── HTTP endpoints ──────────────────────────────────────────────

@app.get("/rooms")
def get_rooms():
    return manager.get_rooms()


class CreateRoomRequest(BaseModel):
    name: str
    type: str  # "ai" | "peer"


@app.post("/rooms")
def create_room(req: CreateRoomRequest):
    room = manager.create_room(req.name, req.type)
    return {"id": room["id"], "name": room["name"], "type": room["type"]}


# ── WebSocket endpoint ──────────────────────────────────────────

@app.websocket("/ws/{room_id}/{username}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, username: str):
    if room_id not in manager.rooms:
        await websocket.close(code=4004)
        return

    await manager.connect(room_id, username, websocket)
    room = manager.rooms[room_id]

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            content = message.get("content", "")

            # Difundir el mensaje del usuario a todos en la sala
            await manager.broadcast(
                room_id,
                {"type": "message", "content": content, "username": username, "from": "user"},
            )

            # Si es sala de IA, pedir respuesta a DeepSeek
            if room["type"] == "ai":
                conv = manager.conversations[room_id]
                conv.append({"role": "user", "content": f"{username}: {content}"})

                await manager.broadcast(
                    room_id, {"type": "typing", "content": "", "username": "DeepSeek AI", "from": "ai"}
                )

                try:
                    reply = await ask_deepseek(conv)
                    conv.append({"role": "assistant", "content": reply})
                    await manager.broadcast(
                        room_id,
                        {"type": "message", "content": reply, "username": "DeepSeek AI", "from": "ai"},
                    )
                except Exception as e:
                    await manager.broadcast(
                        room_id,
                        {"type": "error", "content": f"Error con la IA: {str(e)}", "username": "Sistema", "from": "system"},
                    )

    except WebSocketDisconnect:
        manager.disconnect(room_id, username)
        await manager.broadcast(
            room_id,
            {
                "type": "system",
                "content": f"{username} ha salido del chat",
                "username": "Sistema",
                "from": "system",
                "users": list(manager.rooms[room_id]["connections"].keys()),
            },
        )
