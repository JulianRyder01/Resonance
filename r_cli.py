# r_cli.py
import argparse
import requests
import sys
import os
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
        sys.exit(1)
    except Exception as e:
        print(f"[Error] Request failed: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Resonance AI Host CLI")
    parser.add_argument("message", type=str, help="The message to send to the AI")
    parser.add_argument("-s", "--session", type=str, default="resonance_main", help="Target session ID (default: resonance_main)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Do not show toast notification")
    
    args = parser.parse_args()
    
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
    if not args.quiet:
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
            # icon=... (如果有icon路径可以加在这里)
        )

if __name__ == "__main__":
    main()