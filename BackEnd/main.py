from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import httpx
import json
import os
from dotenv import load_dotenv

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
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(DEEPSEEK_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


@app.websocket("/ws/chat")
async def chat_endpoint(websocket: WebSocket):
    await websocket.accept()
    conversation: list[dict] = [
        {"role": "system", "content": "Eres un asistente útil y amigable. Responde siempre en el idioma que te hablen."}
    ]

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            user_text = message.get("content", "")

            conversation.append({"role": "user", "content": user_text})

            await websocket.send_text(json.dumps({"type": "typing", "content": ""}))

            try:
                reply = await ask_deepseek(conversation)
                conversation.append({"role": "assistant", "content": reply})
                await websocket.send_text(json.dumps({"type": "message", "content": reply}))
            except Exception as e:
                await websocket.send_text(json.dumps({"type": "error", "content": f"Error al contactar con la IA: {str(e)}"}))

    except WebSocketDisconnect:
        pass
