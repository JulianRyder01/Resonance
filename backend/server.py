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
from core.memory import ConversationMemory
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
        # [修改点] 默认主会话
        self.agent = HostAgent(default_session="resonance_main")
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

class SessionRename(BaseModel):
    new_name: str

# [新增] CLI 聊天请求模型
class ChatSyncRequest(BaseModel):
    message: str
    session_id: str = "resonance_main"

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
    1. 通知前端 (Toast)
    2. [新增] 将事件写入主进程会话，实现对话连贯
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        # A. 写入主进程内存
        state.agent.handle_sentinel_trigger(message_str)

        # B. 广播到前端
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

# [修改点] 获取特定会话的历史记录
@app.get("/api/history")
async def get_history(session_id: str = "resonance_main"):
    mem = state.agent.get_memory(session_id)
    return mem.get_full_log()

# --- [新增] 同步聊天接口 (供 API/CLI 调用) ---
@app.post("/api/chat/sync")
async def chat_sync(request: ChatSyncRequest):
    """
    CLI 专用接口。
    执行完整的 ReAct 循环并返回最终文本结果。
    """
    full_response = ""
    last_tool_output = ""
    
    # 运行生成器直到结束
    # 注意：Agent.chat 是同步生成器，这里会阻塞当前 Worker，生产环境建议放入 run_in_executor
    try:
        for event in state.agent.chat(request.message, session_id=request.session_id):
            if event['type'] == 'delta':
                full_response += (event.get('content') or "")
            elif event['type'] == 'tool':
                # 记录工具输出以便如果 LLM 没有后续文本，至少能看到工具结果
                last_tool_output = f"[Tool Executed: {event['name']} -> {str(event['content'])[:100]}...]"
            elif event['type'] == 'error':
                return {"status": "error", "content": event['content']}
                
        # 如果没有生成文本但执行了工具，返回工具提示
        final_text = full_response if full_response.strip() else last_tool_output
        return {
            "status": "success", 
            "content": final_text, 
            "session_id": request.session_id
        }
    except Exception as e:
        return {"status": "error", "content": str(e)}

# --- Session Management APIs ---

@app.get("/api/sessions")
async def list_sessions():
    """列出所有会话"""
    return ConversationMemory.list_sessions()

@app.post("/api/sessions")
async def create_session(session_id: str = Body(..., embed=True)):
    """创建一个新会话（实际上就是确保加载了它）"""
    mem = state.agent.get_memory(session_id)
    return {"status": "created", "id": session_id}

@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, payload: SessionRename):
    """重命名会话"""
    mem = state.agent.get_memory(session_id)
    try:
        mem.rename_session(payload.new_name)
        # 清除旧缓存
        if session_id in state.agent.memory_cache:
            del state.agent.memory_cache[session_id]
        return {"status": "renamed", "new_name": payload.new_name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    if session_id == "resonance_main":
        raise HTTPException(status_code=403, detail="Cannot delete main process session.")
    
    success = ConversationMemory.delete_session(session_id)
    if session_id in state.agent.memory_cache:
        del state.agent.memory_cache[session_id]
        
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}

@app.delete("/api/sessions/{session_id}/messages")
async def clear_session_messages(session_id: str):
    """清空会话内容"""
    mem = state.agent.get_memory(session_id)
    mem.clear()
    return {"status": "cleared"}

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
                # [修改点] 支持指定会话ID，默认为主进程
                session_id = payload.get("session_id", "resonance_main")
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
                # 迭代 Agent 的生成器，[修改点] 传入 session_id
                for event in state.agent.chat(user_input, session_id=session_id):
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
if os.path.exists("../frontend/dist"):
    app.mount("/", StaticFiles(directory="../frontend/dist", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # 启动服务器
    uvicorn.run(app, host="0.0.0.0", port=8000)