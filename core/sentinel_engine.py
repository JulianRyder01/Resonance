# core/sentinel_engine.py
# [新增文件] 哨兵系统核心引擎
import threading
import time
import json
import os
import schedule
import keyboard
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class SentinelEventHandler(FileSystemEventHandler):
    """文件监控事件处理器"""
    def __init__(self, callback, description):
        self.callback = callback
        self.description = description
        self.last_trigger = 0

    def on_any_event(self, event):
        # 简单的防抖动 (Debounce)
        current_time = time.time()
        if current_time - self.last_trigger < 1.0:
            return
        
        # 忽略目录变化，通常我们关注文件
        if event.is_directory:
            return

        self.last_trigger = current_time
        msg = f"[File Sentinel Triggered] Path: {event.src_path} | Event: {event.event_type} | Watch Reason: {self.description}"
        self.callback(msg)

class SentinelEngine:
    """
    哨兵引擎：负责管理时间、文件和行为哨兵的生命周期。
    支持持久化存储，确保重启后哨兵配置不丢失。
    """
    def __init__(self, config_path="config/sentinels.json"):
        self.config_path = config_path
        self.callback_func = None # 触发时的回调函数
        
        # 状态存储
        self.sentinels = {
            "time": {},
            "file": {},
            "behavior": {}
        }
        
        # 运行时对象
        self.file_observer = None
        self.running = False
        self.thread = None

    def set_callback(self, func):
        """设置触发回调，通常是 Main 程序中的处理函数"""
        self.callback_func = func

    def _trigger(self, message):
        """内部触发器"""
        print(f"\n[Sentinel System]: {message}")
        if self.callback_func:
            self.callback_func(message)

    # --- 持久化 ---
    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 恢复配置但不立即启动（start时启动）
                    self.sentinels = data
            except Exception as e:
                print(f"[Sentinel] Error loading config: {e}")

    def save_config(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.sentinels, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Sentinel] Error saving config: {e}")

    # --- 启动与停止 ---
    def start(self):
        if self.running: return
        self.running = True
        self.load_config()
        
        # 1. 启动文件监控 Observer
        self.file_observer = Observer()
        self._restore_file_sentinels()
        self.file_observer.start()

        # 2. 恢复时间哨兵
        self._restore_time_sentinels()

        # 3. 恢复行为哨兵
        self._restore_behavior_sentinels()

        # 4. 启动主循环线程 (用于 schedule)
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("[System]: Sentinel Engine Started (Time, File, Behavior monitors active).")

    def _run_loop(self):
        while self.running:
            schedule.run_pending()
            time.sleep(1)

    def stop(self):
        self.running = False
        if self.file_observer:
            self.file_observer.stop()
            self.file_observer.join()
        # keyboard 不需要显式 stop，程序退出会自动清理钩子

    # --- 注册逻辑 (带恢复) ---

    def _restore_time_sentinels(self):
        schedule.clear()
        for s_id, data in self.sentinels.get("time", {}).items():
            self._schedule_time_job(s_id, data['interval'], data['unit'], data['description'])

    def _schedule_time_job(self, s_id, interval, unit, description):
        """实际将任务加入 schedule"""
        def job():
            self._trigger(f"[Time Sentinel Triggered] ID: {s_id} | Task: {description}")

        if unit == 'seconds':
            schedule.every(interval).seconds.do(job).tag(s_id)
        elif unit == 'minutes':
            schedule.every(interval).minutes.do(job).tag(s_id)
        elif unit == 'hours':
            schedule.every(interval).hours.do(job).tag(s_id)
        elif unit == 'days':
             schedule.every(interval).days.do(job).tag(s_id)

    def add_time_sentinel(self, interval, unit, description):
        s_id = f"time_{int(time.time())}"
        self.sentinels["time"][s_id] = {
            "interval": int(interval),
            "unit": unit,
            "description": description
        }
        self._schedule_time_job(s_id, int(interval), unit, description)
        self.save_config()
        return s_id

    def _restore_file_sentinels(self):
        if not self.file_observer: return
        self.file_observer.unschedule_all()
        for s_id, data in self.sentinels.get("file", {}).items():
            path = data['path']
            if os.path.exists(path):
                event_handler = SentinelEventHandler(self._trigger, data['description'])
                # 监控目录，recursive=False 稍微安全点，视需求而定
                # 这里如果是文件，监控其父目录；如果是目录，监控目录
                if os.path.isfile(path):
                    watch_path = os.path.dirname(path)
                else:
                    watch_path = path
                
                try:
                    self.file_observer.schedule(event_handler, watch_path, recursive=False)
                except Exception as e:
                    print(f"[Sentinel] Failed to restore file watcher for {path}: {e}")

    def add_file_sentinel(self, path, description):
        if not os.path.exists(path):
            return "Error: Path does not exist."
        
        s_id = f"file_{int(time.time())}"
        self.sentinels["file"][s_id] = {
            "path": path,
            "description": description
        }
        self.save_config()
        # 立即生效
        self._restore_file_sentinels()
        return s_id

    def _restore_behavior_sentinels(self):
        keyboard.unhook_all()
        for s_id, data in self.sentinels.get("behavior", {}).items():
            key_combo = data['key_combo']
            self._hook_keyboard(s_id, key_combo, data['description'])

    def _hook_keyboard(self, s_id, key_combo, description):
        try:
            # 使用 lambda 捕获闭包变量
            keyboard.add_hotkey(key_combo, lambda: self._trigger(f"[Behavior Sentinel Triggered] Hotkey '{key_combo}' pressed. | Action: {description}"))
        except Exception as e:
            print(f"[Sentinel] Failed to hook keys {key_combo}: {e}")

    def add_behavior_sentinel(self, key_combo, description):
        s_id = f"behavior_{int(time.time())}"
        self.sentinels["behavior"][s_id] = {
            "key_combo": key_combo,
            "description": description
        }
        self._hook_keyboard(s_id, key_combo, description)
        self.save_config()
        return s_id

    def list_sentinels(self):
        return self.sentinels

    def remove_sentinel(self, s_type, s_id):
        if s_type in self.sentinels and s_id in self.sentinels[s_type]:
            del self.sentinels[s_type][s_id]
            self.save_config()
            
            # 重新加载以应用删除
            if s_type == "time":
                self._restore_time_sentinels()
            elif s_type == "file":
                self._restore_file_sentinels()
            elif s_type == "behavior":
                self._restore_behavior_sentinels()
                
            return True
        return False