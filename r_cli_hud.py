# r_cli_hud.py
import webview
import sys
import threading
import time
import requests
import argparse
from win11toast import toast

# 配置
API_URL = "http://localhost:8000/api/chat/sync"
FRONTEND_URL = "http://localhost:5173"

def send_chat(message, session_id="resonance_main"):
    """发送请求到后端并等待回复"""
    payload = {
        "message": message,
        "session_id": session_id
    }
    
    print(f"[*] Sending message to session '{session_id}'...")
    try:
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        print("[Error] Could not connect to Resonance Backend. Is it running?")
        toast("Resonance", "Could not connect to Resonance Backend. Is it running?", duration="short")
        sys.exit(1)
    except Exception as e:
        print(f"[Error] Request failed: {e}")
        sys.exit(1)

def start_hud():
    # 检测后端
    print("Waiting for Resonance Backend...")
    for _ in range(10):
        if check_backend():
            break
        time.sleep(1)
    
    # 目标 URL：指向前端的 HUD 路由
    # 注意：前端 Vite 开发服务器默认在 5173
    url = "http://localhost:5173/hud"
    
    # 如果是生产环境打包为 dist，可以指向本地 HTML 文件，
    # 但这里假设是开发环境或已 build 的 serve 环境
    
    webview.create_window(
        title='Resonance HUD', 
        url=url, 
        width=400, 
        height=500, 
        frameless=True,       # 无边框
        on_top=True,          # 置顶
        easy_drag=True,       # 允许拖拽背景移动
        background_color='#0f172a', # 匹配前端 Slate-900
        text_select=True
    )
    
    webview.start()

# 确保后端已经运行
def check_backend():
    try:
        requests.get("http://localhost:8000/api/status", timeout=1)
        return True
    except:
        return False

def main():
    parser = argparse.ArgumentParser(description="Resonance AI HUD CLI")
    parser.add_argument("message", type=str, nargs='?', help="The message to send to the AI (optional, if not provided opens HUD window)")
    parser.add_argument("-s", "--silent", action="store_true", help="Silent mode - only show toast after execution")
    parser.add_argument("-q", "--quiet", action="store_true", help="Do not show toast notification")
    parser.add_argument("--session", type=str, default="resonance_main", help="Target session ID (default: resonance_main)")
    
    args = parser.parse_args()
    
    # 如果提供了消息参数，则发送消息
    if args.message:
        # 1. 发送请求
        result = send_chat(args.message, args.session)
        
        if result.get("status") == "error":
            print(f"[AI Error]: {result.get('content')}")
            return

        content = result.get("content", "")
        
        # 2. 命令行输出
        print("\n" + "="*40)
        print(f"Resonance ({args.session}):")
        print(content)
        print("="*40 + "\n")
        
        # 3. 弹窗通知 (Win11Toast)
        if not args.quiet and not args.silent:
            # 构建点击跳转链接
            # 前端已修改支持 ?session=xxx 参数
            target_url = f"{FRONTEND_URL}?session={args.session}"
            
            # 截取简短内容用于通知
            short_msg = content[:100] + "..." if len(content) > 100 else content
            
            toast(
                "Resonance AI",
                short_msg,
                on_click=target_url,
                duration="short",
            )
        elif args.silent:
            # 静默模式下，在执行完成后显示通知
            toast(
                "Resonance AI (Silent)",
                "Task completed successfully!",
                duration="short",
            )
    else:
        # 如果没有提供消息参数，则启动HUD窗口
        start_hud()

if __name__ == '__main__':
    main()