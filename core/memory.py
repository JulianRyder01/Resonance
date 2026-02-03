# core/memory.py
import json
import os
import glob
import time
from typing import List, Dict, Any

class ConversationMemory:
    """
    管理Agent的对话历史。
    特性：
    1. 完整日志记录 (Full Log)：保存到磁盘，不做删减。
    2. 滑动窗口 (Sliding Window)：用于 LLM 上下文，只返回最近 N 轮。
    3. 摘要 (Summary)：存储历史对话的总结。
    """
    def __init__(self, session_id="default", base_dir="logs/sessions", window_size=10):
        self.session_id = session_id
        self.base_dir = base_dir
        self.save_path = os.path.join(self.base_dir, f"{self.session_id}.json")
        self.summary_path = os.path.join(self.base_dir, f"{self.session_id}_summary.txt")
        
        # 配置
        self.window_size = window_size  # 保留的消息数量（非轮数，简单起见）
        
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)

    # --- 磁盘 I/O ---

    def _read_full_log(self) -> List[Dict]:
        """从磁盘读取完整日志"""
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
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
            with open(self.summary_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return ""

    def save_summary(self, summary_text):
        """保存摘要"""
        with open(self.summary_path, 'w', encoding='utf-8') as f:
            f.write(summary_text)

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
            "content": content, # 通常为 None
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

    # --- 核心：获取上下文 (Sliding Window) ---

    def get_active_context(self, include_summary=True) -> List[Dict]:
        """
        获取用于发送给 API 的上下文：
        1. 包含 System Prompt (由 Agent 负责，这里只返回对话历史)
        2. 包含最近的 N 条消息 (Sliding Window)
        3. 必须确保 Tool Call 和 Tool Output 不被截断分离
        """
        full_history = self._read_full_log()
        
        if not full_history:
            return []

        # 1. 简单的切片 (取最近 window_size 条)
        # 注意：为了防止把 Tool Call 和 Tool Result 切开，我们不仅看数量，还要向后回溯
        window_msgs = full_history[-self.window_size:]
        
        # 修正逻辑：如果切片的第一条是 'tool' (Result)，说明它的 'assistant' (Call) 被切掉了，需要补回来
        # 或者如果第一条是 'assistant' 且有 'tool_calls'，但上下文不完整，也需要处理
        # 简易策略：如果 window_msgs[0].role == 'tool'，则尝试向前多取一条
        
        while len(full_history) > len(window_msgs):
            first_msg = window_msgs[0]
            if first_msg.get('role') == 'tool':
                # 工具结果，必须包含前面的工具调用
                extra_idx = len(full_history) - len(window_msgs) - 1
                window_msgs.insert(0, full_history[extra_idx])
            else:
                break
        
        # 2. 清洗字段 (去除 timestamp 等)
        clean_history = []
        for msg in window_msgs:
            clean_msg = {k: v for k, v in msg.items() if k in ["role", "content", "tool_calls", "tool_call_id", "name"]}
            # OpenAI 不允许 tool 消息有 content 以外的额外字段，除了 tool_call_id
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