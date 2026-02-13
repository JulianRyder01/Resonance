# r_hud.py
import webview
import sys
import threading
import time
import requests

# 确保后端已经运行
def check_backend():
    try:
        requests.get("http://localhost:8000/api/status", timeout=1)
        return True
    except:
        return False

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

if __name__ == '__main__':
    start_hud()