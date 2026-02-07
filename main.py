# main.py
import os
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk
import argparse
import subprocess
from win11toast import toast

# === 新增：抢占式初始化 ONNX ===
try:
    import onnxruntime as _ort
    # 这一行不产生输出，但会强制 Windows 加载底层 DLL
    _ort.get_device() 
except Exception:
    pass
# ============================

from core.host_agent import HostAgent

class ResonanceHUD:
    """
    一个优雅的、悬浮的 HUD 窗口，用于替代简陋的命令行输出。
    支持流式文本渲染、即时输入和打断功能。
    """
    def __init__(self, agent, initial_query=None):
        self.agent = agent
        self.root = tk.Tk()
        self.root.title("Resonance AI HUD")
        
        # --- 窗口配置 ---
        self.root.attributes("-alpha", 0.96)  # 轻微透明
        self.root.attributes("-topmost", True) # 始终置顶
        
        # 居中与尺寸
        width = 800
        height = 600
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 3 # 偏上一点，符合 Spotlight 习惯
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        
        self.root.configure(bg="#1e1e1e")
        
        # --- UI 布局 ---
        # 1. 顶部状态栏
        self.status_var = tk.StringVar(value="Resonance Ready")
        self.lbl_status = tk.Label(self.root, textvariable=self.status_var, bg="#1e1e1e", fg="#4facfe", font=("Consolas", 10))
        self.lbl_status.pack(side="top", fill="x", padx=10, pady=5)
        
        # 2. 聊天内容显示区 (Text Widget)
        self.txt_display = tk.Text(self.root, bg="#2d2d2d", fg="#e0e0e0", 
                                   font=("Segoe UI", 11), wrap="word", 
                                   borderwidth=0, highlightthickness=0,
                                   state="disabled") # 初始只读
        self.txt_display.pack(expand=True, fill="both", padx=15, pady=5)
        
        # 配置 Tag 样式 (Markdown 模拟)
        self.txt_display.tag_config("user", foreground="#88c0d0", font=("Segoe UI", 11, "bold"))
        self.txt_display.tag_config("ai", foreground="#e0e0e0")
        self.txt_display.tag_config("tool", foreground="#d08770", font=("Consolas", 10))
        self.txt_display.tag_config("error", foreground="#bf616a")
        self.txt_display.tag_config("status", foreground="#5e81ac", font=("Consolas", 9, "italic"))
        self.txt_display.tag_config("sentinel", foreground="#ebcb8b", font=("Segoe UI", 11, "bold")) # 哨兵消息颜色

        # 3. 底部输入区
        input_frame = tk.Frame(self.root, bg="#1e1e1e")
        input_frame.pack(side="bottom", fill="x", padx=15, pady=10)
        
        self.entry_input = tk.Entry(input_frame, bg="#3b4252", fg="white", 
                                    font=("Segoe UI", 12), borderwidth=0, 
                                    insertbackground="white")
        self.entry_input.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=5)
        self.entry_input.bind("<Return>", self.on_send)
        
        # 按钮
        self.btn_send = tk.Button(input_frame, text="Send", command=self.on_send, 
                                  bg="#4facfe", fg="white", font=("Segoe UI", 10, "bold"),
                                  relief="flat", activebackground="#3b8eea", activeforeground="white")
        self.btn_send.pack(side="right")
        
        # --- 逻辑控制 ---
        self.msg_queue = queue.Queue()
        self.is_generating = False

        # [新增] 注册哨兵回调
        # 当哨兵引擎触发时，会调用这个 lambda，将消息放入队列
        self.agent.sentinel_engine.set_callback(lambda msg: self.msg_queue.put({"type": "sentinel_trigger", "content": msg}))
        
        # 启动队列监听器
        self.root.after(100, self.process_queue)
        
        # 初始 Query 处理
        if initial_query:
            self.entry_input.insert(0, initial_query)
            self.on_send() # 自动发送
            
    def append_text(self, text, tag=None):
        """线程安全的文本追加"""
        self.txt_display.config(state="normal")
        self.txt_display.insert("end", text, tag)
        self.txt_display.see("end")
        self.txt_display.config(state="disabled")

    def process_queue(self):
        """主线程轮询队列"""
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                m_type = msg.get("type")
                content = msg.get("content")
                
                if m_type == "status":
                    self.status_var.set(f"⚡ {content}")
                    self.append_text(f"\n[System]: {content}\n", "status")
                    
                elif m_type == "delta":
                    self.append_text(content, "ai")
                    
                elif m_type == "tool":
                    self.append_text(f"\n\n🛠️ Tool Output [{msg.get('name')}]:\n{content}\n", "tool")
                    
                elif m_type == "error":
                    self.append_text(f"\n❌ Error: {content}\n", "error")
                    
                elif m_type == "user":
                    self.append_text(f"\n👤 You: {content}\n", "user")
                    self.append_text("💠 Resonance: ", "ai") # 前缀
                
                # [新增] 哨兵触发事件处理
                elif m_type == "sentinel_trigger":
                    if not self.is_generating:
                        # 自动在 UI 上显示触发信息
                        self.append_text(f"\n🔔 {content}\n", "sentinel")
                        # 强制弹出窗口
                        self.root.deiconify() 
                        self.root.attributes("-topmost", True)
                        
                        # 自动开始生成 (Auto-Run)
                        self.is_generating = True
                        self.btn_send.config(text="Stop", bg="#bf616a")
                        
                        # 构造 Prompt 让 AI 知道是哨兵唤醒了它
                        prompt = f"SYSTEM ALERT: {content}\nPlease analyze this event and take necessary actions."
                        
                        # 启动线程
                        t = threading.Thread(target=self.run_agent_task, args=(prompt,), daemon=True)
                        t.start()
                        
                    else:
                        # 如果正在忙，只提示
                        toast("Resonance Sentinel Triggered", content)
                        self.append_text(f"\n[Queue] Sentinel Triggered: {content}\n", "status")

                elif m_type == "done":
                    self.is_generating = False
                    self.status_var.set("Ready")
                    self.btn_send.config(text="Send", bg="#4facfe")
                    
        except queue.Empty:
            pass
        
        self.root.after(100, self.process_queue)

    def run_agent_task(self, query):
        """后台线程运行 Agent"""
        try:
            # 传递用户消息到 UI (如果是 Sentinel 触发的，已经在 process_queue 里打印了)
            if not query.startswith("SYSTEM ALERT"):
                self.msg_queue.put({"type": "user", "content": query})
            else:
                self.msg_queue.put({"type": "user", "content": "[SYSTEM EVENT TRIGGERED]"})
                self.msg_queue.put({"type": "delta", "content": "Checking Sentinel Report...\n"})
            
            for event in self.agent.chat(query):
                self.msg_queue.put(event)
                
        except Exception as e:
            self.msg_queue.put({"type": "error", "content": str(e)})
        finally:
            self.msg_queue.put({"type": "done"})

    def on_send(self, event=None):
        """处理发送/打断逻辑"""
        query = self.entry_input.get().strip()
        
        if self.is_generating:
            # 如果正在生成，按钮功能变为“打断”
            # 或者如果用户输入 /stop
            if query == "/stop" or event is None: # event is None means button click check
                self.agent.interrupt()
                self.entry_input.delete(0, "end")
                return
        
        if not query:
            return
            
        # 这里特别处理 /stop 命令，防止它作为 query 发送
        if query == "/stop":
             if self.is_generating:
                 self.agent.interrupt()
             return

        self.is_generating = True
        self.btn_send.config(text="Stop", bg="#bf616a") # 变红
        self.entry_input.delete(0, "end")
        
        # 启动线程
        t = threading.Thread(target=self.run_agent_task, args=(query,), daemon=True)
        t.start()

    def start(self):
        # [新增] 启动哨兵引擎
        self.agent.sentinel_engine.start()
        self.root.mainloop()

def check_env():
    """环境自检"""
    print("Checking Resonance Environment...")
    if not os.path.exists("config/config.yaml"):
        print("Error: config/config.yaml not found.")
        return False
    
    # 确保日志和会话目录存在
    os.makedirs("logs/sessions", exist_ok=True)
    return True

def run_gui():
    if not check_env():
        return

    print("Launching Resonance UI...")
    
    # 获取当前Python解释器路径
    python_executable = sys.executable
    
    # 运行 Streamlit
    cmd = [python_executable, "-m", "streamlit", "run", "app.py"]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nResonance Stopped.")


def run_hud_mode(query, session_id):
    """启动 HUD 模式"""
    if not check_env(): return
    
    # 预加载 Agent (稍慢，但只需要一次)
    print("Loading Resonance Core...")
    agent = HostAgent(session_id=session_id)
    
    # 启动 UI
    hud = ResonanceHUD(agent, initial_query=query)
    hud.start()

def run_cli(query, session_id):
    """
    CLI 执行模式 (已重构以支持流式生成器)
    """
    # 确保 session 目录存在
    os.makedirs("logs/sessions", exist_ok=True)
    
    # 打印初始状态
    print(f"\n[Resonance System]: Initializing Session='{session_id}'...")
    print(f"[User]: {query}\n")
    print("-" * 50)
    
    # 初始化 Agent
    try:
        agent = HostAgent(session_id=session_id)
        
        full_response = ""
        last_status = ""

        # --- 修改点: 遍历生成器，处理流式事件 ---
        for event in agent.chat(query):
            etype = event["type"]
            content = event.get("content", "")

            if etype == "status":
                # 状态更新：避免重复打印相同的状态
                if content != last_status:
                    # 使用颜色或特殊符号标识思考过程
                    print(f"\n[*] {content}")
                    last_status = content
            
            elif etype == "delta":
                # 内容增量：实时流式输出到终端
                sys.stdout.write(content)
                sys.stdout.flush()
                full_response += content
            
            elif etype == "tool":
                # 工具调用结果：换行显示并使用代码块风格
                print(f"\n\n[🛠️ Tool Output - {event.get('name')}]:")
                # 稍微缩进显示工具返回的内容
                indented_content = "\n".join(["    " + line for line in str(content).splitlines()])
                print(indented_content)
                print("-" * 30)
                # 工具执行完后重置状态提示，以便接下来的文字输出能正常换行
                last_status = ""
            
            elif etype == "error":
                # 错误处理
                print(f"\n\n[❌ Error]: {content}")

        # 交互结束后的收尾
        print("\n" + "-" * 50)
        print(f"\n[Final Response Generated.]\n")
        
        # Windows 通知 (使用聚合后的完整文本)
        if full_response:
            try:
                # 截取前100个字符用于通知预览
                toast("Resonance Task Completed", full_response[:100] + "...")
            except:
                pass
                
    except Exception as e:
        import traceback
        print(f"\n[Fatal Error]: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resonance AI Host")
    parser.add_argument("query", nargs="?", help="Command to execute immediately (CLI mode)")
    parser.add_argument("--session", default="cli_history", help="Session ID for CLI history (default: cli_history)")
    
    args = parser.parse_args()
    
    if args.query:
        # TODO 命令行模式作为备选项，放在这里不要删，未来实现的时候看见这个需要加上参数 -h 实现hud展示，不加就是无hud。
        # run_cli(args.query, args.session)
        run_hud_mode(args.query, args.session)
    else:
        # GUI 模式
        run_gui()