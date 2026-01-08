from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import httpx
import uuid
import os
from datetime import datetime
import json

app = FastAPI(title="AI Platform")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище пользователей (в памяти)
users_data: Dict[str, Dict[str, Any]] = {}

# GigaChat конфиг
GIGACHAT_API_KEY = "MDE5YjdmZTUtNGQ4Mi03NGViLWEyZDktYWNlNDMzMmZkYzQwOmY2ZGY4YTRhLWNlOTAtNDFjMC04OWU0LTEzNDg0NDJjYTY0YQ=="
gigachat_token = None

# Модели
class ChatRequest(BaseModel):
    message: str
    user_id: str

class Widget(BaseModel):
    id: str
    type: str
    name: str
    config: Dict[str, Any]

# Получение токена GigaChat
async def get_gigachat_token() -> str:
    global gigachat_token
    
    if gigachat_token:
        return gigachat_token
    
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Authorization": f"Basic {GIGACHAT_API_KEY}",
        "RqUID": str(uuid.uuid4()),
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"scope": "GIGACHAT_API_PERS"}
    
    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(url, headers=headers, data=data)
            if response.status_code == 200:
                gigachat_token = response.json()["access_token"]
                return gigachat_token
            else:
                raise HTTPException(status_code=500, detail=f"GigaChat auth failed: {response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GigaChat error: {str(e)}")

# Запрос к GigaChat
async def ask_gigachat(message: str, history: List[Dict] = None) -> str:
    try:
        token = await get_gigachat_token()
        
        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if history:
            messages.extend(history[-10:])  # Последние 10 сообщений
        messages.append({"role": "user", "content": message})
        
        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                return f"Ошибка GigaChat: {response.status_code}"
                
    except Exception as e:
        return f"Ошибка соединения с GigaChat: {str(e)}"

# Инициализация пользователя
def init_user(user_id: str):
    if user_id not in users_data:
        users_data[user_id] = {
            "widgets": [],
            "history": [],
            "created_at": datetime.now().isoformat()
        }

# Парсинг команд создания виджетов
def parse_widget_command(text: str) -> Optional[Dict]:
    text_lower = text.lower().strip()
    
    # Кнопка
    for phrase in ["создай кнопку", "добавь кнопку", "сделай кнопку"]:
        if phrase in text_lower:
            name = text[text_lower.find(phrase) + len(phrase):].strip().strip('"\'')
            if name:
                return {
                    "type": "button",
                    "name": name,
                    "config": {}
                }
    
    # Счётчик
    for phrase in ["создай счётчик", "добавь счётчик", "сделай счётчик", "создай счетчик"]:
        if phrase in text_lower:
            name = text[text_lower.find(phrase) + len(phrase):].strip().strip('"\'')
            if name:
                return {
                    "type": "counter",
                    "name": name,
                    "config": {"value": 0}
                }
    
    # Список
    for phrase in ["создай список", "добавь список", "сделай список"]:
        if phrase in text_lower:
            name = text[text_lower.find(phrase) + len(phrase):].strip().strip('"\'')
            if name:
                return {
                    "type": "list",
                    "name": name,
                    "config": {"items": []}
                }
    
    return None

# API Endpoints
@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.post("/api/chat")
async def chat(req: ChatRequest):
    user_id = req.user_id
    message = req.message
    
    init_user(user_id)
    
    # Проверяем команду создания виджета
    widget_data = parse_widget_command(message)
    
    if widget_data:
        # Создаём виджет
        widget = Widget(
            id=str(uuid.uuid4()),
            type=widget_data["type"],
            name=widget_data["name"],
            config=widget_data["config"]
        )
        
        users_data[user_id]["widgets"].append(widget.dict())
        
        widget_names = {
            "button": "кнопку",
            "counter": "счётчик",
            "list": "список"
        }
        
        response_text = f"✅ Отлично! Создал {widget_names.get(widget.type, 'виджет')} \"{widget.name}\".\n\nОн появился в левой панели. Попробуй кликнуть на него!"
    else:
        # Обычный запрос к AI
        response_text = await ask_gigachat(message, users_data[user_id]["history"])
    
    # Сохраняем в историю
    users_data[user_id]["history"].append({
        "role": "user",
        "content": message
    })
    users_data[user_id]["history"].append({
        "role": "assistant",
        "content": response_text
    })
    
    return {
        "response": response_text,
        "widgets": users_data[user_id]["widgets"]
    }

@app.get("/api/widgets/{user_id}")
async def get_widgets(user_id: str):
    init_user(user_id)
    return {"widgets": users_data[user_id]["widgets"]}

@app.delete("/api/widgets/{user_id}/{widget_id}")
async def delete_widget(user_id: str, widget_id: str):
    init_user(user_id)
    users_data[user_id]["widgets"] = [
        w for w in users_data[user_id]["widgets"] 
        if w["id"] != widget_id
    ]
    return {"success": True}

@app.get("/api/health")
async def health():
    return {"status": "ok", "users": len(users_data)}

# Монтируем статику
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
