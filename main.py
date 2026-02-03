# main.py
import os
import sys
import subprocess
import argparse
from core.host_agent import HostAgent
from win11toast import toast

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
    """CLI 执行模式"""
    # 确保 session 目录存在
    os.makedirs("logs/sessions", exist_ok=True)
    
    # 打印一些 Loading 状态
    print(f"\n[Resonance]: Session='{session_id}'")
    print(f"[Input]: {query}")
    
    # 初始化 Agent (这一步会读取 config/profiles 等)
    try:
        agent = HostAgent(session_id=session_id)
        
        # 定义一个简单的回调打印到控制台
        def cli_callback(text):
            print(f"  > {text}")
            
        # 执行交互
        response = agent.chat(query, ui_callback=cli_callback)
        
        # 输出结果
        print(f"\n[Result]: {response}\n")
        
        # Windows 通知 (可选)
        try:
            toast("Resonance", response[:100])
        except:
            pass
            
    except Exception as e:
        print(f"[Fatal Error]: {e}")

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