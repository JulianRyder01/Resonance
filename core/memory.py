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
    4. [新增] 上下文自愈：防止因工具调用中断导致的 API 格式错误。
    """
    def __init__(self, session_id="default", base_dir="logs/sessions", window_size=10):
        self.session_id = session_id
        self.base_dir = base_dir
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
        history.append(message)
        self._write_full_log(history)

    def add_user_message(self, content):
        self._append_message({"role": "user", "content": content})

    def add_ai_message(self, content):
        if content: # 避免保存空内容
            self._append_message({"role": "assistant", "content": content})

    def add_ai_tool_call(self, content, tool_calls):
        """保存 AI 发起的工具调用请求"""
        serializable_calls = []
        for call in tool_calls:
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
        获取上下文并进行滑动窗口处理。
        """
        full_history = self._read_full_log()
        
        if not full_history:
            return []

        # 1. 简单的切片 (取最近 window_size 条)
        # 注意：为了防止把 Tool Call 和 Tool Result 切开，我们不仅看数量，还要向后回溯
        window_msgs = full_history[-self.window_size:]
        
        # 回溯补全：如果切片的第一条是 'tool' (Result)，说明它的 'assistant' (Call) 被切掉了，需要补回来
        while len(full_history) > len(window_msgs):
            first_msg = window_msgs[0]
            if first_msg.get('role') == 'tool':
                # 工具结果，必须包含前面的工具调用
                extra_idx = len(full_history) - len(window_msgs) - 1
                if extra_idx >= 0:
                    window_msgs.insert(0, full_history[extra_idx])
                else:
                    break
            else:
                break

        # 3. 执行自愈清洗
        sanitized = self._sanitize_context(window_msgs)

        # 3. 格式清洗 (去除 timestamp 等 OpenAI 不接受的字段)
        clean_history = []
        allowed_keys = ["role", "content", "tool_calls", "tool_call_id", "name"]
        for msg in sanitized:
            clean_msg = {k: v for k, v in msg.items() if k in allowed_keys}
            clean_history.append(clean_msg)
        return clean_history

    def get_messages_for_summarization(self) -> str:
        """获取需要被摘要的旧消息（即在窗口之外的消息）"""
        full_history = self._read_full_log()
        if len(full_history) <= self.window_size:
            return ""
        
        # 获取窗口之前的消息
        msgs_to_summarize = full_history[:-self.window_size]
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

    @staticmethod
    def list_sessions(base_dir="logs/sessions"):
        """列出所有现有会话"""
        if not os.path.exists(base_dir):
            return []
        files = glob.glob(os.path.join(base_dir, "*.json"))
        # 返回文件名作为 session_id (去掉 .json)
        sessions = [os.path.basename(f).replace(".json", "") for f in files]
        # 按修改时间排序（新的在前）
        sessions.sort(key=lambda x: os.path.getmtime(os.path.join(base_dir, f"{x}.json")), reverse=True)
        return sessions

    @staticmethod
    def delete_session(session_id, base_dir="logs/sessions"):
        path = os.path.join(base_dir, f"{session_id}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False