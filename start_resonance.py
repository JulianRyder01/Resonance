# start.py
import subprocess
import time
import os
import sys

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

if __name__ == "__main__":
    print("=========================================")
    print("   🚀 Resonance Backend Host - One-Click Run")
    print("=========================================")
    
    backend = None
    
    try:
        backend = start_backend()
        # 等待后端启动
        time.sleep(3) 

        
        print("\n✅ Backend systems go!")
        print("Backend running on: http://localhost:8000")
        
        
        # 保持主进程运行
        backend.wait()

        
    except KeyboardInterrupt:
        print("\n[Launcher] Shutting down services...")
        if backend: backend.terminate()
        print("[Launcher] Bye!")