# start.py
import subprocess
import time
import os
import sys
import webbrowser

def start_backend():
    print("[Launcher] Starting Backend (FastAPI)...")
    # 假设 python 环境已激活或直接使用系统 python
    # 如果是在 conda 环境中，确保此时已 activate，或者使用绝对路径
    backend_process = subprocess.Popen(
        [sys.executable, "server.py"], 
        cwd=os.path.join(os.getcwd(), "backend"),
        shell=True
    )
    return backend_process

def start_frontend():
    print("[Launcher] Starting Frontend (Vite)...")
    # 需要 npm 在环境变量中
    frontend_process = subprocess.Popen(
        ["npm", "run", "dev"], 
        cwd=os.path.join(os.getcwd(), "frontend"),
        shell=True
    )
    return frontend_process

if __name__ == "__main__":
    print("=========================================")
    print("   🚀 Resonance AI Host - One-Click Run")
    print("=========================================")
    
    backend = None
    frontend = None
    
    try:
        backend = start_backend()
        # 等待后端启动
        time.sleep(3) 
        
        frontend = start_frontend()
        # 等待前端启动
        time.sleep(3)
        
        print("\n✅ All systems go!")
        print("Backend running on: http://localhost:8000")
        print("Frontend running on: http://localhost:5173")
        
        webbrowser.open("http://localhost:5173")
        
        # 保持主进程运行
        backend.wait()
        frontend.wait()
        
    except KeyboardInterrupt:
        print("\n[Launcher] Shutting down services...")
        if backend: backend.terminate()
        if frontend: frontend.terminate()
        print("[Launcher] Bye!")