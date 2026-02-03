# main.py
import os
import sys

# === 新增：抢占式初始化 ONNX ===
try:
    import onnxruntime as _ort
    # 这一行不产生输出，但会强制 Windows 加载底层 DLL
    _ort.get_device() 
except Exception:
    pass
# ============================

import subprocess
import argparse
from core.host_agent import HostAgent
from win11toast import toast

# =========================================================================
# 修改说明：
# 1. 移除了旧版直接打印 agent.chat 结果的逻辑。
# 2. 重构了 run_cli 函数，使其能够消费 agent.chat 返回的生成器。
# 3. 引入了实时终端输出逻辑 (sys.stdout.write)，支持流式显示内容。
# 4. 增加了对 status, delta, tool, error 不同事件类型的分支处理。
# =========================================================================

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
        # 命令行模式
        run_cli(args.query, args.session)
    else:
        # GUI 模式
        run_gui()