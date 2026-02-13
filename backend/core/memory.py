# core/memory.py
import json
import os
import glob
import time
import copy
from typing import List, Dict, Any

class ConversationMemory:
    """
    管理Agent的对话历史。
    特性：
    1. 完整日志记录 (Full Log)：保存到磁盘，不做删减。
    2. 滑动窗口 (Sliding Window)：用于 LLM 上下文，只返回最近 N 轮。
    3. 摘要 (Summary)：存储历史对话的总结。
    4. 上下文自愈：防止因工具调用中断导致的 API 格式错误。
    5. [修改] 锚定上下文 (Pinned Context)：始终保留对话开头的意图和计划。
    """
    def __init__(self, session_id="default", base_dir="logs/sessions", window_size=10):
        self.session_id = session_id
        self.base_dir = base_dir
        # [修改点] 确保目录路径规范化
        self.save_path = os.path.join(self.base_dir, f"{self.session_id}.json")
        self.summary_path = os.path.join(self.base_dir, f"{self.session_id}_summary.txt")
        
        # 配置
        self.window_size = window_size  # 保留的消息数量（对话条数）
        
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)

    # --- 磁盘 I/O ---

    def _read_full_log(self) -> List[Dict]:
        """从磁盘读取完整日志"""
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    return []
            except Exception:
                return []
        return []

    def _write_full_log(self, history_list):
        """写入完整日志到磁盘"""
        try:
            with open(self.save_path, 'w', encoding='utf-8') as f:
                json.dump(history_list, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving memory: {e}")

    def load_summary(self) -> str:
        """读取当前的对话摘要"""
        if os.path.exists(self.summary_path):
            try:
                with open(self.summary_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except:
                return ""
        return ""

    def save_summary(self, summary_text):
        """保存摘要"""
        try:
            with open(self.summary_path, 'w', encoding='utf-8') as f:
                f.write(summary_text)
        except Exception as e:
            print(f"Error saving summary: {e}")

    # --- 消息操作 ---

    def _append_message(self, message: Dict):
        """内部方法：追加消息并保存"""
        history = self._read_full_log()
        message['timestamp'] = time.time()
        # [新增] 为每条消息生成唯一ID，方便前端删除或修改
        if 'id' not in message:
            message['id'] = str(int(time.time() * 1000))
            
        history.append(message)
        self._write_full_log(history)

    def add_user_message(self, content):
        self._append_message({"role": "user", "content": content})

    def add_ai_message(self, content):
        if content: # 避免保存空内容
            self._append_message({"role": "assistant", "content": content})
            
    # [新增] 添加系统/哨兵消息
    def add_system_message(self, content):
        """用于哨兵系统或系统通知"""
        # 注意：OpenAI API 通常 system message 只在开头。
        # 这里为了保持线性历史，我们将其作为 system 角色插入，
        # 在 _sanitize_context 中可能需要根据模型特性决定是否保留或转为 user/assistant
        self._append_message({"role": "system", "content": content})

    def add_ai_tool_call(self, content, tool_calls):
        """保存 AI 发起的工具调用请求"""
        serializable_calls = []
        for call in tool_calls:
            # 兼容不同格式
            if isinstance(call, dict):
                serializable_calls.append(call)
            else:
                serializable_calls.append({
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments
                    }
                })
        self._append_message({
            "role": "assistant", 
            "content": content, # 通常为 None 或思维链内容
            "tool_calls": serializable_calls,
            "timestamp": time.time()
        })

    def add_tool_message(self, content, tool_call_id):
        self._append_message({
            "role": "tool", 
            "tool_call_id": tool_call_id,
            "content": str(content),
            "timestamp": time.time()
        })

    # --- 核心：获取上下文 (Sliding Window & Sanitization) ---

    def _sanitize_context(self, messages: List[Dict]) -> List[Dict]:
        """
        [鲁棒性增强] 强制性格式修复。
        遵循 OpenAI 规范：Assistant(tool_calls) 后面必须紧跟对应的 Tool 响应。
        """
        if not messages:
            return []

        sanitized = []
        # 用于追踪当前必须立刻出现的 tool_call_id
        pending_ids = []

        for msg in messages:
            role = msg.get("role")

            # 1. 处理 Tool 消息
            if role == "tool":
                tid = msg.get("tool_call_id")
                # 如果这个 tool 消息在“待处理”名单里，或者它是孤儿但我们允许它通过(后续会剔除)，记录它
                if tid in pending_ids:
                    pending_ids.remove(tid)
                    sanitized.append(msg)
                else:
                    # 如果是一个孤儿 Tool 消息（前面没有 Assistant 调用它），直接丢弃
                    # 因为 API 会报错 400
                    continue

            # 2. 如果当前有 pending_ids，但接下来的消息不是 tool
            elif pending_ids:
                # 这是一个格式错误！必须在这里强制插入缺失的 Tool 结果
                for missing_id in pending_ids:
                    sanitized.append({
                        "role": "tool",
                        "tool_call_id": missing_id,
                        "content": "Error: Tool execution was interrupted. System recovered."
                    })
                pending_ids = []
                # 补完缺失的后，再把当前的 user/assistant 消息加进去
                sanitized.append(msg)
                # 如果当前消息又是 assistant 且带 tool_calls，开启新一轮追踪
                if role == "assistant" and msg.get("tool_calls"):
                    pending_ids = [tc['id'] for tc in msg['tool_calls']]
            
            # 3. 处理正常的 Assistant 带工具调用
            elif role == "assistant" and msg.get("tool_calls"):
                pending_ids = [tc['id'] for tc in msg['tool_calls']]
                sanitized.append(msg)
            
            # 4. 正常消息
            else:
                sanitized.append(msg)

        # 5. 循环结束检查：如果结尾还有没闭合的 tool_calls
        if pending_ids:
            for missing_id in pending_ids:
                sanitized.append({
                    "role": "tool",
                    "tool_call_id": missing_id,
                    "content": "Error: Tool sequence incomplete at log end."
                })
        
        return sanitized

    def get_active_context(self) -> List[Dict]:
        """
        [修改说明 - 需求①] 
        移除了强制保留前两条消息（Pinned Context）的逻辑。
        现在采用纯滑动窗口机制。这允许用户在对话中途切换任务时，
        旧的任务指令会被滑出窗口，AI 专注于当前最新的 User Input 和 Summary。
        """
        full_history = self._read_full_log()
        
        if not full_history:
            return []

        # 过滤掉纯 System 消息，除非包含 Supervisor 指令（需要让 AI 看到）
        # 注意：这里的 'system' role 指的是内部注入的日志，不是 Prompt 里的 System Prompt
        conversation_msgs = [m for m in full_history if m.get('role') != 'system' or 'Supervisor' in m.get('content', '')]

        # 简单的滑动窗口：获取最近的 window_size 条
        context_msgs = conversation_msgs[-self.window_size:]

        # 执行格式清洗（修复断裂的 Tool Chain）
        sanitized = self._sanitize_context(context_msgs)

        # 字段过滤，只保留 LLM API 需要的字段
        clean_history = []
        allowed_keys = ["role", "content", "tool_calls", "tool_call_id", "name"]
        for msg in sanitized:
            clean_msg = {k: v for k, v in msg.items() if k in allowed_keys}
            clean_history.append(clean_msg)
            
        return clean_history

    def get_messages_for_summarization(self) -> str:
        """获取需要被摘要的旧消息（即在窗口之外的消息）"""
        full_history = self._read_full_log()
        
        # 需求①适配：因为不再 Pin 前2条，所以摘要应该覆盖所有被滑出的消息
        if len(full_history) <= self.window_size:
            return ""
        
        # 获取窗口之前的消息
        msgs_to_summarize = full_history[:-self.window_size]
        if not msgs_to_summarize:
            return ""

        text_block = ""
        for msg in msgs_to_summarize:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if msg.get('tool_calls'):
                content += f" [Tool Call: {msg['tool_calls'][0]['function']['name']}]"
            text_block += f"{role}: {content}\n"
            
        return text_block

    def get_full_log(self):
        """获取完整日志（用于 UI 展示）"""
        return self._read_full_log()

    def clear(self):
        self._write_full_log([])
        if os.path.exists(self.summary_path):
            os.remove(self.summary_path)

    # --- [新增] 会话管理 API 支持 ---

    def rename_session(self, new_name: str):
        """重命名当前会话文件"""
        new_path = os.path.join(self.base_dir, f"{new_name}.json")
        new_summary_path = os.path.join(self.base_dir, f"{new_name}_summary.txt")
        
        if os.path.exists(new_path):
            raise ValueError(f"Session '{new_name}' already exists.")
            
        if os.path.exists(self.save_path):
            os.rename(self.save_path, new_path)
            self.save_path = new_path
            
        if os.path.exists(self.summary_path):
            os.rename(self.summary_path, new_summary_path)
            self.summary_path = new_summary_path
            
        self.session_id = new_name
        return True

    def delete_message(self, message_index: int):
        """删除特定索引的消息（危险操作：可能破坏上下文）"""
        history = self._read_full_log()
        if 0 <= message_index < len(history):
            history.pop(message_index)
            self._write_full_log(history)
            return True
        return False

    @staticmethod
    def list_sessions(base_dir="logs/sessions"):
        """列出所有现有会话，包括元数据"""
        if not os.path.exists(base_dir):
            return []
        files = glob.glob(os.path.join(base_dir, "*.json"))
        sessions = []
        for f in files:
            try:
                name = os.path.basename(f).replace(".json", "")
                mtime = os.path.getmtime(f)
                # 简单读取最后一条消息作为预览
                with open(f, 'r', encoding='utf-8') as read_f:
                    data = json.load(read_f)
                    preview = ""
                    if data:
                        last_msg = data[-1]
                        preview = str(last_msg.get('content', ''))[:50]
                        if not preview and last_msg.get('tool_calls'):
                            preview = f"[Tool Call: {last_msg['tool_calls'][0]['function']['name']}]"
                
                sessions.append({
                    "id": name,
                    "updated_at": mtime,
                    "preview": preview,
                    "message_count": len(data) if data else 0
                })
            except Exception:
                continue
                
        # 按修改时间排序（新的在前）
        sessions.sort(key=lambda x: x['updated_at'], reverse=True)
        return sessions

    @staticmethod
    def delete_session(session_id, base_dir="logs/sessions"):
        path = os.path.join(base_dir, f"{session_id}.json")
        summary_path = os.path.join(base_dir, f"{session_id}_summary.txt")
        
        deleted = False
        if os.path.exists(path):
            os.remove(path)
            deleted = True
        if os.path.exists(summary_path):
            os.remove(summary_path)
            
        return deleted