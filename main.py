from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
import json
import random

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 15가지 요소와 각각이 이기는 대상들 (David C. Lovelace의 15-way RPS 규칙 기반)
# 각 요소가 이기는 7가지 다른 요소들을 매핑합니다.
ELEMENTS = [
    "Rock", "Gun", "Lightning", "Devil", "Dragon", 
    "Water", "Air", "Paper", "Sponge", "Wolf", 
    "Tree", "Human", "Snake", "Scissors", "Fire"
]

# 간소화를 위해 각 원소가 이기는 7개 항목 정의 (시계/반시계 방향 순환 규칙)
# 여기서는 인덱스 기반 혹은 명시적 룰셋으로 판정합니다.
# 15개 원소 원형 고리에서 자신보다 앞선 7개를 이긴다고 가정합니다.
def check_win(p1: str, p2: str) -> str:
    if p1 == p2:
        return "draw"
    try:
        idx1 = ELEMENTS.index(p1)
        idx2 = ELEMENTS.index(p2)
    except ValueError:
        return "draw"
    
    # 15개 중 절반인 7개를 이기는 구조 (거리 계산)
    diff = (idx2 - idx1) % 15
    if diff <= 7 and diff != 0:
        return "win" # p1 기준 p2를 이김? 규칙에 따라 조정 필요
    else:
        return "lose"

# 정확한 15목 가위바위보 승패 판정 로직 (이기는 대상 7개씩 지정)
WIN_RULES = {
    "Rock": ["Fire", "Scissors", "Snake", "Human", "Tree", "Wolf", "Sponge"],
    "Gun": ["Rock", "Fire", "Scissors", "Snake", "Human", "Tree", "Wolf"],
    "Lightning": ["Gun", "Rock", "Fire", "Scissors", "Snake", "Human", "Tree"],
    "Devil": ["Lightning", "Gun", "Rock", "Fire", "Scissors", "Snake", "Human"],
    "Dragon": ["Devil", "Lightning", "Gun", "Rock", "Fire", "Scissors", "Snake"],
    "Water": ["Dragon", "Devil", "Lightning", "Gun", "Rock", "Fire", "Scissors"],
    "Air": ["Water", "Dragon", "Devil", "Lightning", "Gun", "Rock", "Fire"],
    "Paper": ["Air", "Water", "Dragon", "Devil", "Lightning", "Gun", "Rock"],
    "Sponge": ["Paper", "Air", "Water", "Dragon", "Devil", "Lightning", "Gun"],
    "Wolf": ["Sponge", "Paper", "Air", "Water", "Dragon", "Devil", "Lightning"],
    "Tree": ["Wolf", "Sponge", "Paper", "Air", "Water", "Dragon", "Devil"],
    "Human": ["Tree", "Wolf", "Sponge", "Paper", "Air", "Water", "Dragon"],
    "Snake": ["Human", "Tree", "Wolf", "Sponge", "Paper", "Air", "Water"],
    "Scissors": ["Snake", "Human", "Tree", "Wolf", "Sponge", "Paper", "Air"],
    "Fire": ["Scissors", "Snake", "Human", "Tree", "Wolf", "Sponge", "Paper"]
}

def get_winner(choice1, choice2):
    if choice1 == choice2:
        return "draw"
    if choice2 in WIN_RULES.get(choice1, []):
        return "player1"
    else:
        return "player2"

# 방 관리 클래스
class RoomManager:
    def __init__(self):
        self.rooms = {} # {room_id: {"players": [websocket, ...], "choices": {websocket: choice}}}

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {"players": [], "choices": {}}
        
        if len(self.rooms[room_id]["players"]) >= 2:
            await websocket.send_text(json.dumps({"type": "error", "message": "방이 꽉 찼습니다."}))
            await websocket.close()
            return False

        self.rooms[room_id]["players"].append(websocket)
        return True

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.rooms:
            if websocket in self.rooms[room_id]["players"]:
                self.rooms[room_id]["players"].remove(websocket)
            if websocket in self.rooms[room_id]["choices"]:
                del self.rooms[room_id]["choices"][websocket]
            if not self.rooms[room_id]["players"]:
                del self.rooms[room_id]

    async def broadcast(self, room_id: str, message: dict):
        if room_id in self.rooms:
            for player in self.rooms[room_id]["players"]:
                await player.send_text(json.dumps(message))

manager = RoomManager()

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    connected = await manager.connect(websocket, room_id)
    if not connected:
        return

    try:
        # 방에 현재 접속한 인원 수 알림
        num_players = len(manager.rooms[room_id]["players"])
        await manager.broadcast(room_id, {"type": "info", "message": f"플레이어 입장 (현재 {num_players}/2명)"})

        while True:
            data = await websocket.receive_text()
            packet = json.loads(data)
            
            if packet["type"] == "choice":
                choice = packet["choice"]
                room = manager.rooms.get(room_id)
                if room:
                    room["choices"][websocket] = choice
                    await websocket.send_text(json.dumps({"type": "info", "message": f"선택 완료: {choice}. 상대방을 기다리는 중..."}))

                    # 두 명 모두 선택을 마쳤을 경우
                    if len(room["choices"]) == 2:
                        p_list = room["players"]
                        c1 = room["choices"][p_list[0]]
                        c2 = room["choices"][p_list[1]]

                        winner = get_winner(c1, c2)
                        
                        result_msg = {
                            "type": "result",
                            "p1_choice": c1,
                            "p2_choice": c2,
                            "winner": winner
                        }
                        await manager.broadcast(room_id, result_msg)
                        
                        # 다음 판을 위해 선택 초기화
                        room["choices"] = {}

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
        await manager.broadcast(room_id, {"type": "info", "message": "상대방이 나갔습니다."})