# backend/server.py
import onnxruntime
import os
import sys
import json
import asyncio
import logging
import threading
import queue  # 标准库 queue
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
# 引入 win11toast 用于桌面通知
from win11toast import toast


# 调整路径以便导入 core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.host_agent import HostAgent
from core.memory import ConversationMemory
from utils.monitor import SystemMonitor

# RAG 策略
class RAGConfigUpdate(BaseModel):
    strategy: str # 'semantic' or 'hybrid_time'

class SkillLearnRequest(BaseModel):
    url_or_path: str

# --- 配置日志 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
        # 确保哨兵引擎启动
        try:
            self.agent.sentinel_engine.start() 
        except Exception as e:
            logger.error(f"Sentinel Engine failed to start: {e}")
            
        # [修改点] 增加 loop 引用，用于跨线程通信
        self.loop = None
        
        # [修改点] 初始化全局线程池
        # max_workers 可以根据 CPU 核心数调整，这里设置为 10 以支持并发会话
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="AgentWorker")
        logger.info("HostAgent, SentinelEngine & ThreadPoolExecutor Started.")

    def shutdown(self):
        """优雅关闭"""
        logger.info("Shutting down executor...")
        self.executor.shutdown(wait=False)

state = GlobalState()

@app.on_event("startup")
async def startup_event():
    state.loop = asyncio.get_running_loop()
    logger.info("Main Event Loop captured for thread-safe bridging.")
    
    # --- [新增] 数据库自检与种子注入 ---
    try:
        count = state.agent.rag_store.count()
        logger.info(f"[RAG Check]: Current memory count: {count}")
        
        if count == 0:
            logger.info("[RAG Init]: Database is empty. Injecting seed memory...")
            state.agent.rag_store.add_memory(
                text="Welcome to Resonance. This is the first permanent memory block created to initialize the Vector Database.",
                metadata={
                    "type": "system_init",
                    "source": "server_startup"
                }
            )
            logger.info("[RAG Init]: Seed memory injected successfully.")
    except Exception as e:
        logger.error(f"[RAG Init Error]: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    state.shutdown()

# --- Pydantic Models for Config API ---
class ProfileUpdate(BaseModel):
    profile_id: str
    api_key: str
    base_url: Optional[str] = None
    model: str
    temperature: float = 0.7
    name: Optional[str] = None # Added name field for UI display
    provider: str = "openai"   # Added provider field

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
        logger.info(f"New WS Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WS Client disconnected.")

    async def broadcast(self, message: dict):
        """向所有连接的前端广播消息"""
        if not self.active_connections:
            return
        text = json.dumps(message, ensure_ascii=False)
        # 复制一份列表进行迭代，防止迭代中修改导致错误
        for connection in list(self.active_connections):
            try:
                await connection.send_text(text)
            except Exception as e:
                logger.error(f"WS Broadcast Error: {e}")
                # 如果发送失败，可能连接已断开，尝试清理
                try:
                    await self.disconnect(connection)
                except:
                    pass

manager = ConnectionManager()

# --- [核心修改] 线程安全的 Chat 执行器 ---
# 这个函数在独立的线程池中运行，通过 asyncio.run_coroutine_threadsafe 将结果推回主 Loop 的 Queue
def run_sync_chat_generator(agent_instance, user_input, session_id, async_queue, loop):
    """
    包装器：在线程中运行同步的 agent.chat 生成器，
    并将生成的 item 放入 async_queue 中供 WebSocket 消费。
    """
    try:
        # 执行同步生成器
        # [修改点] 这里的 agent.chat 现在是线程安全的，因为我们在 host_agent.py 中移除了对 self.active_session_id 的依赖
        for event in agent_instance.chat(user_input, session_id=session_id):
            # 必须使用 run_coroutine_threadsafe 跨线程调用 async 方法
            asyncio.run_coroutine_threadsafe(async_queue.put(event), loop)
        
        # 完成信号
        asyncio.run_coroutine_threadsafe(async_queue.put({"type": "done", "session_id": session_id}), loop)
        
    except Exception as e:
        import traceback
        error_msg = f"Internal Agent Error: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        asyncio.run_coroutine_threadsafe(
            async_queue.put({"type": "error", "content": error_msg, "session_id": session_id}), 
            loop
        )

# --- [核心修改] 哨兵自动响应逻辑 ---

async def run_autonomous_reaction(trigger_message: str):
    """
    [新增] 自主反应任务：
    当哨兵触发时，不仅通知前端，还启动 AI 进行分析和工具执行。
    结果会实时流式传输到 WebSocket，最后通过 Toast 弹窗通知。
    """
    session_id = "resonance_main"
    logger.info(f"[Auto-Reaction] AI triggered by sentinel: {trigger_message}")

    # 1. 等待 WebSocket 连接稳定（防止触发瞬间连接还没握手完成）
    await asyncio.sleep(0.5)

    # 2. 发送初始状态通知
    await manager.broadcast({
        "type": "sentinel_alert", # 前端会触发 Toast
        "content": f"Sentinel triggered. AI is responding to: {trigger_message}",
        "session_id": session_id
    })

    # 3. 构造 Prompt 注入
    prompt = f"[System Alert]: {trigger_message}. Please check this and take necessary actions."
    
    full_response_text = ""
    event_queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    
    # [修改点] 使用线程池提交任务，而不是手动创建 Thread
    state.executor.submit(
        run_sync_chat_generator, 
        state.agent, 
        prompt, 
        session_id, 
        event_queue, 
        loop
    )

    # 4. 消费队列并广播
    while True:
        event = await event_queue.get()
        event["session_id"] = session_id
        
        # 实时推送
        await manager.broadcast(event)
        
        if event["type"] == "delta":
            full_response_text += (event.get("content") or "")
        elif event["type"] == "done":
            break
        elif event["type"] == "error":
            logger.error(f"Auto-reaction AI error: {event['content']}")
            break

    # 5. 发送 Windows Toast 弹窗
    if full_response_text.strip():
        # 清洗文本
        clean_text = full_response_text.replace("*", "").replace("#", "")
        display_text = clean_text[:120] + "..." if len(clean_text) > 120 else clean_text
        
        try:
            toast("Resonance AI (Sentinel Response)", display_text)
        except Exception as e:
            logger.error(f"Windows Toast Error: {e}")

# --- 哨兵回调桥接 ---
# 这是一个运行在 Thread 中的回调，需要安全地调用 Async 方法
def sentinel_callback_bridge(message_str):
    """
    当 SentinelEngine (线程) 触发时调用此函数。
    1. 通知前端 (Toast)
    2. [新增] 将事件写入主进程会话，实现对话连贯
    """
    if state.loop is None:
        logger.error("Sentinel Error: Main Loop not initialized yet.")
        return

    # A. 写入主进程内存
    state.agent.handle_sentinel_trigger(message_str)

    # B. [核心修复] 使用 run_coroutine_threadsafe 跨线程调用异步函数
    logger.info(f"Sentinel Bridge: Scheduling auto-reaction for: {message_str}")
    asyncio.run_coroutine_threadsafe(run_autonomous_reaction(message_str), state.loop)

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

# --- [新增] RAG 配置接口 ---
@app.get("/api/config/rag")
async def get_rag_config():
    """获取当前 RAG 策略"""
    strategy = state.agent.config.get('system', {}).get('memory', {}).get('rag_strategy', 'semantic')
    return {"strategy": strategy}

@app.post("/api/config/rag")
async def set_rag_config(update: RAGConfigUpdate):
    """设置 RAG 策略"""
    if update.strategy not in ['semantic', 'hybrid_time']:
        raise HTTPException(status_code=400, detail="Invalid strategy. Use 'semantic' or 'hybrid_time'.")
    
    # 更新内存中的配置
    if 'system' not in state.agent.config: state.agent.config['system'] = {}
    if 'memory' not in state.agent.config['system']: state.agent.config['system']['memory'] = {}
    
    state.agent.config['system']['memory']['rag_strategy'] = update.strategy
    
    # 持久化到文件
    state.agent.update_config(new_config=state.agent.config)
    
    return {"status": "updated", "strategy": update.strategy}


# --- [修复] SKILLS MANAGEMENT APIs ---

@app.get("/api/skills/list")
async def list_skills():
    """获取所有技能（包括内置 Scripts 和 导入的 Skills）"""
    # 1. 获取 Legacy scripts (Config.yaml)
    legacy = state.agent.config.get('scripts', {})
    
    # 2. [修复点] 获取真实加载的技能注册表 (SkillManager Registry)
    # 不再依赖 config['imported_skills']，而是直接读取 SkillManager 扫描到的内容
    registry = state.agent.skill_manager.skill_registry
    
    # 转换为前端友好的格式
    imported = {}
    for name, data in registry.items():
        meta = data.get('metadata', {})
        imported[name] = {
            "description": data.get('description', 'No description'),
            "source": meta.get('source', 'local'), # 前端可能用到，默认 local
            "path": data.get('path'),
            "commands": data.get('metadata', {}).get('commands', [])
        }
    
    return {
        "legacy": legacy,
        "imported": imported
    }

@app.post("/api/skills/learn")
async def learn_skill_endpoint(payload: SkillLearnRequest):
    """
    触发 AI 学习新技能。这是一个可能耗时的操作，为了不阻塞主线程，放到 executor 中运行。
    """
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            state.executor, 
            state.agent.skill_manager.learn_skill, 
            payload.url_or_path
        )
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Skill learning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/skills/{skill_name}")
async def delete_skill(skill_name: str):
    """删除已学习的技能"""
    try:
        success = state.agent.skill_manager.delete_skill(skill_name)
        if not success:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"status": "deleted", "skill": skill_name}
    except Exception as e:
        logger.error(f"Delete skill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
    [修改点] 使用 asyncio.to_thread 或 loop.run_in_executor 避免阻塞
    """
    full_response = ""
    last_tool_output = ""
    
    try:
        # 定义同步任务
        def _sync_task():
            response_text = ""
            tool_output = ""
            for event in state.agent.chat(request.message, session_id=request.session_id):
                if event['type'] == 'delta':
                    response_text += (event.get('content') or "")
                elif event['type'] == 'tool':
                    tool_output = f"[Tool Executed: {event['name']} -> {str(event['content'])[:100]}...]"
                elif event['type'] == 'error':
                    raise Exception(event['content'])
            return response_text, tool_output

        # 在线程池中运行
        loop = asyncio.get_running_loop()
        final_text, final_tool_out = await loop.run_in_executor(state.executor, _sync_task)
                
        # 如果没有生成文本但执行了工具，返回工具提示
        result_text = final_text if final_text.strip() else final_tool_out
        
        return {
            "status": "success", 
            "content": result_text, 
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

# [新增] 保存/新建 Profile 接口
@app.post("/api/config/profiles/save")
async def save_profile(profile: ProfileUpdate):
    """新增或修改模型 Profile"""
    # 1. 获取当前 Profiles
    current_profiles = state.agent.profiles
    
    # 2. 更新或插入
    profile_data = {
        "name": profile.name or profile.profile_id,
        "api_key": profile.api_key,
        "base_url": profile.base_url,
        "model": profile.model,
        "temperature": profile.temperature,
        "provider": profile.provider
    }
    
    current_profiles[profile.profile_id] = profile_data
    
    # 3. 持久化
    state.agent.update_config(new_profiles=current_profiles)
    
    return {"status": "success", "profile_id": profile.profile_id}

# [新增] 删除 Profile 接口
@app.delete("/api/config/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """删除模型 Profile"""
    if profile_id not in state.agent.profiles:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    if profile_id == state.agent.config.get('active_profile'):
        raise HTTPException(status_code=400, detail="Cannot delete active profile. Switch first.")
    
    current_profiles = state.agent.profiles
    del current_profiles[profile_id]
    
    state.agent.update_config(new_profiles=current_profiles)
    return {"status": "deleted"}


@app.get("/api/system/metrics")
async def get_system_metrics():
    """获取实时 CPU、内存、电池指标"""
    return SystemMonitor.get_system_metrics()

@app.get("/api/system/processes")
async def get_system_processes():
    """获取占用资源最高的进程列表"""
    df = SystemMonitor.get_process_list(limit=15)
    return df.to_dict(orient="records")

@app.get("/api/system/disk")
async def get_disk_status():
    """获取磁盘使用情况"""
    return SystemMonitor.get_disk_usage()

# --- SKILL MANAGEMENT APIs ---

@app.get("/api/skills/list")
async def list_skills():
    """获取所有技能（包括内置 Scripts 和 导入的 Skills）"""
    # Legacy scripts
    legacy = state.agent.config.get('scripts', {})
    
    # Imported skills from config
    imported = state.agent.config.get('imported_skills', {})
    
    return {
        "legacy": legacy,
        "imported": imported
    }

@app.post("/api/skills/learn")
async def learn_skill_endpoint(payload: SkillLearnRequest):
    """
    触发 AI 学习新技能。这是一个可能耗时的操作，为了不阻塞主线程，放到 executor 中运行。
    """
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            state.executor, 
            state.agent.skill_manager.learn_skill, 
            payload.url_or_path
        )
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Skill learning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/skills/{skill_name}")
async def delete_skill(skill_name: str):
    """删除已学习的技能"""
    try:
        success = state.agent.skill_manager.delete_skill(skill_name)
        if not success:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"status": "deleted", "skill": skill_name}
    except Exception as e:
        logger.error(f"Delete skill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- [核心修复] 全双工 WebSocket Chat Endpoint ---
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await manager.connect(websocket)
    
    # 每个连接专属的队列
    event_queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    
    # 1. 定义 Sender 任务：持续从队列取数据发给前端
    async def sender_task():
        try:
            while True:
                # 这一行会异步等待队列有新数据
                event = await event_queue.get()
                try:
                    await websocket.send_json(event)
                except Exception as e:
                    logger.error(f"WS Send Error: {e}")
                    break
                
                # 如果收到完成或错误信号，并不退出循环，因为用户可能发下一条消息
                # 但如果是 'done'，我们可以标记任务结束（视具体逻辑而定）
                pass
        except asyncio.CancelledError:
            logger.info("Sender task cancelled.")

    # 启动 Sender 作为后台任务
    sender_future = asyncio.create_task(sender_task())

    try:
        # 2. 主循环作为 Receiver：持续监听前端输入
        while True:
            # 这一行会异步等待前端发来数据（包括 /stop）
            # 由于 sender_future 是独立的，这里等待不会阻塞发送
            data = await websocket.receive_text()
            
            try:
                # [Fix] 显式捕获 JSON 错误，防止静默失败
                payload = json.loads(data)
                user_input = payload.get("message")
                session_id = payload.get("session_id", "resonance_main")
                msg_id = payload.get("id")
                
                if not user_input:
                    continue
                    


                # 3. 处理命令
                if user_input == "/stop":
                    logger.info(f"Received STOP command for session: {session_id}")
                    # 立即触发后端中断
                    state.agent.interrupt(session_id=session_id)
                    
                    # 立即反馈给前端（绕过队列，确保响应速度）
                    await websocket.send_json({
                        "type": "status", 
                        "content": "🛑 Aborted by User.",
                        "session_id": session_id
                    })
                    # 同时也放入队列标记结束，确保 frontend 状态重置
                    await event_queue.put({"type": "done", "session_id": session_id})
                    continue

                # 正常消息 echo
                await websocket.send_json({"type": "user", "content": user_input, "session_id": session_id,"id": msg_id})

                # 提交 AI 任务到线程池
                state.executor.submit(
                    run_sync_chat_generator, 
                    state.agent, 
                    user_input, 
                    session_id, 
                    event_queue, 
                    loop
                )
                
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received: {data}")
                await websocket.send_json({"type": "error", "content": "Invalid JSON format"})
            except Exception as e:
                logger.error(f"Message processing error: {e}")
                await websocket.send_json({"type": "error", "content": f"Server Error: {str(e)}"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS Critical Error: {e}")
        manager.disconnect(websocket)
    finally:
        # 清理 Sender 任务
        sender_future.cancel()

# --- 静态文件服务 ---
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