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
# [修改点] 引入 win11toast 用于桌面通知
from win11toast import toast

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

# --- [核心修改] 哨兵自动响应逻辑 ---

async def run_autonomous_reaction(trigger_message: str):
    """
    [新增] 自主反应任务：
    当哨兵触发时，不仅通知前端，还启动 AI 进行分析和工具执行。
    结果会实时流式传输到 WebSocket，最后通过 Toast 弹窗通知。
    """
    session_id = "resonance_main"
    logger.info(f"[Auto-Reaction] Started for: {trigger_message}")

    # 1. 构造触发提示词
    # 我们告诉 AI 刚刚发生了系统警报，要求它分析
    prompt = f"[System Sentinel Triggered]: {trigger_message}\nPlease analyze this event. If it requires action (like checking a file, looking up info), DO IT. Finally, verify if everything is OK."
    
    full_response_text = ""
    
    # 2. 通知前端 AI 开始工作了
    await manager.broadcast({
        "type": "system_status", 
        "content": "🛡️ Sentinel Active: AI Host is responding...",
        "session_id": session_id
    })

    try:
        # 3. 运行 Agent 推理循环 (模拟用户输入)
        # 注意：Agent.chat 是同步生成器，我们需要在循环中释放控制权给 asyncio loop
        iterator = state.agent.chat(prompt, session_id=session_id)
        
        for event in iterator:
            # 广播事件到前端（带上 session_id，让前端知道这是主进程的消息）
            event["session_id"] = session_id
            await manager.broadcast(event)
            
            # 收集最终文本用于 Toast 通知
            if event["type"] == "delta":
                full_response_text += event.get("content", "")
            
            # [关键] 让出控制权，防止阻塞 WebSocket 心跳
            await asyncio.sleep(0.01)
            
        # 4. 结束信号
        await manager.broadcast({"type": "done", "session_id": session_id})
        
        # 5. 发送 Windows Toast 通知
        if full_response_text.strip():
            # 简单清洗 Markdown 符号以便在通知中显示
            clean_text = full_response_text.replace("**", "").replace("##", "").strip()
            # 截断过长内容
            display_text = clean_text[:150] + "..." if len(clean_text) > 150 else clean_text
            
            toast(
                "Resonance AI",
                display_text,
                duration="long", # 保持较长时间
                # on_click=... (如果需要可以加打开浏览器的回调)
            )
            logger.info(f"[Auto-Reaction] Completed. Notification sent.")

    except Exception as e:
        logger.error(f"[Auto-Reaction] Error: {e}")
        await manager.broadcast({
            "type": "error", 
            "content": f"Auto-reaction failed: {str(e)}",
            "session_id": session_id
        })


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
        # A. 写入主进程内存 (记录日志)
        state.agent.handle_sentinel_trigger(message_str)

        # B. 广播到前端 (Toast Alert)
        payload = {
            "type": "sentinel_alert",
            "content": message_str,
            "timestamp": int(asyncio.get_event_loop().time())
        }
        asyncio.run_coroutine_threadsafe(manager.broadcast(payload), loop)
        
        # C. [新增] 启动 AI 自主响应闭环
        asyncio.run_coroutine_threadsafe(run_autonomous_reaction(message_str), loop)

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
    # [修改说明] 这里的 logic 移到了 rag_store.py 内部处理 robustness，这里只负责透传
    df = state.agent.rag_store.get_all_memories_as_df()
    
    # 再次确保转为字典列表，处理可能的空 DataFrame
    if df.empty:
        return []
        
    data = df.to_dict(orient="records")
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
            await websocket.send_json({"type": "user", "content": user_input, "session_id": session_id})

            # 2. 调用 Agent
            
            # 检测是否是打断命令
            if user_input == "/stop":
                state.agent.interrupt()
                continue

            try:
                # 迭代 Agent 的生成器，[修改点] 传入 session_id
                for event in state.agent.chat(user_input, session_id=session_id):
                    # 实时推送到前端，带上 session_id 方便前端区分
                    event["session_id"] = session_id
                    await websocket.send_json(event)
                    # 让出控制权，防止阻塞心跳
                    await asyncio.sleep(0.01)
                
                await websocket.send_json({"type": "done", "session_id": session_id})

            except Exception as e:
                await websocket.send_json({"type": "error", "content": str(e), "session_id": session_id})

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