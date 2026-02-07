# backend/server.py
import os
import sys
import json
import asyncio
import logging
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 调整路径以便导入 core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.host_agent import HostAgent
from utils.monitor import SystemMonitor

# --- 配置日志 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ResonanceBackend")

app = FastAPI(title="Resonance AI Host")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 生产环境请限制为前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 全局状态 ---
class GlobalState:
    def __init__(self):
        self.agent = HostAgent(session_id="web_session")
        self.agent.sentinel_engine.start() # 启动哨兵线程
        logger.info("HostAgent & SentinelEngine Started.")

state = GlobalState()

# --- Pydantic Models for Config API ---
class ProfileUpdate(BaseModel):
    profile_id: str
    api_key: str
    base_url: Optional[str] = None
    model: str
    temperature: float = 0.7

class ActiveProfileUpdate(BaseModel):
    profile_id: str

# --- WebSocket 管理器 ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """向所有连接的前端广播消息"""
        text = json.dumps(message, ensure_ascii=False)
        for connection in self.active_connections:
            try:
                await connection.send_text(text)
            except Exception as e:
                logger.error(f"WS Send Error: {e}")

manager = ConnectionManager()

# --- 哨兵回调桥接 ---
# 这是一个运行在 Thread 中的回调，需要安全地调用 Async 方法
def sentinel_callback_bridge(message_str):
    """
    当 SentinelEngine (线程) 触发时调用此函数。
    我们需要将其调度到 FastAPI 的主事件循环中。
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        # 构造 JSON 消息
        payload = {
            "type": "sentinel_alert",
            "content": message_str,
            "timestamp": int(asyncio.get_event_loop().time())
        }
        asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)

# 注册回调
state.agent.sentinel_engine.set_callback(sentinel_callback_bridge)


# --- REST API Endpoints ---

@app.get("/api/status")
async def get_system_status():
    """获取系统监控数据"""
    return SystemMonitor.get_system_metrics()

@app.get("/api/sentinels")
async def get_sentinels():
    """获取当前活跃的哨兵列表"""
    return state.agent.sentinel_engine.list_sentinels()

@app.delete("/api/sentinels/{s_type}/{s_id}")
async def delete_sentinel(s_type: str, s_id: str):
    success = state.agent.sentinel_engine.remove_sentinel(s_type, s_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sentinel not found")
    return {"status": "deleted"}

@app.get("/api/skills")
async def get_skills():
    return state.agent.config.get('scripts', {})

@app.get("/api/history")
async def get_history():
    return state.agent.memory.get_full_log()

# --- Memory Management APIs (New) ---

@app.get("/api/memory")
async def get_all_memories():
    """获取所有长期记忆（RAG）"""
    df = state.agent.rag_store.get_all_memories_as_df()
    # 将 DataFrame 转为 Records 格式列表
    # 处理 NaN 和 Timestamp 对象，确保 JSON 可序列化
    df = df.fillna("")
    data = df.astype(str).to_dict(orient="records")
    return data

@app.delete("/api/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """删除指定 ID 的记忆"""
    success = state.agent.rag_store.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete memory")
    return {"status": "deleted", "id": memory_id}

# --- Config Management APIs (New) ---

@app.get("/api/config")
async def get_full_config():
    """获取当前的配置信息（包含Profiles）"""
    return {
        "active_profile": state.agent.config.get('active_profile'),
        "profiles": state.agent.profiles
    }

@app.post("/api/config/active")
async def set_active_profile(update: ActiveProfileUpdate):
    """切换当前使用的模型"""
    if update.profile_id not in state.agent.profiles:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    state.agent.update_config(new_active_profile=update.profile_id)
    return {"status": "updated", "active_profile": update.profile_id}

# --- WebSocket Chat Endpoint ---

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 接收前端消息
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                user_input = payload.get("message")
            except:
                continue
            
            if not user_input: continue

            # 1. 发送用户消息确认
            await websocket.send_json({"type": "user", "content": user_input})

            # 2. 调用 Agent (同步生成器，需在线程池运行以免阻塞 Async Loop 吗？)
            # HostAgent.chat 是一个 yield generator。
            # 为了简单起见，且 Agent 内部 I/O 操作较多，我们直接迭代。
            # 如果并发量大，建议重构 HostAgent 为 async generator。
            
            # 检测是否是打断命令
            if user_input == "/stop":
                state.agent.interrupt()
                continue

            try:
                # 迭代 Agent 的生成器
                for event in state.agent.chat(user_input):
                    # 实时推送到前端
                    await websocket.send_json(event)
                    # 让出控制权，防止阻塞心跳
                    await asyncio.sleep(0.01)
                
                await websocket.send_json({"type": "done"})

            except Exception as e:
                await websocket.send_json({"type": "error", "content": str(e)})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS Critical Error: {e}")
        manager.disconnect(websocket)

# backend/server.py (补全部分)

@app.get("/api/system/metrics")
async def get_system_metrics():
    """获取实时 CPU、内存、电池指标"""
    # 直接调用你原始代码中的 SystemMonitor
    return SystemMonitor.get_system_metrics()

@app.get("/api/system/processes")
async def get_system_processes():
    """获取占用资源最高的进程列表"""
    # 原始逻辑返回的是 Pandas DataFrame，我们需要转为 JSON 列表
    df = SystemMonitor.get_process_list(limit=15)
    return df.to_dict(orient="records")

@app.get("/api/system/disk")
async def get_disk_status():
    """获取磁盘使用情况"""
    return SystemMonitor.get_disk_usage()

# --- 静态文件服务 (生产环境) ---
# 假设前端 build 后的文件在 frontend/dist
# 如果是开发模式，可以注释掉这里
if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # 启动服务器
    uvicorn.run(app, host="0.0.0.0", port=8000)