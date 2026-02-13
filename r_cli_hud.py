# r_cli.py
import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import sys
import requests
import json
import time

# --- Configuration ---
API_URL = "http://localhost:8000/api/chat/sync"
HISTORY_URL = "http://localhost:8000/api/history"
SESSION_ID = "resonance_main" # CLI HUD targets the main session

class ResonanceHUD:
    def __init__(self):
        self.root = tk.Tk()
        self.setup_window()
        self.setup_ui()
        self.running = True
        self.is_processing = False
        
        # Start background poller for task updates
        self.poll_thread = threading.Thread(target=self.poll_updates, daemon=True)
        self.poll_thread.start()

    def setup_window(self):
        """Configure the HUD window style"""
        self.root.title("Resonance HUD")
        
        # Dark theme colors
        self.bg_color = "#1e1e2e"
        self.fg_color = "#cdd6f4"
        self.accent_color = "#89b4fa"
        self.input_bg = "#313244"
        
        self.root.configure(bg=self.bg_color)
        
        # Position: Bottom Right, Floating
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = 450
        height = 350
        x_pos = screen_width - width - 20
        y_pos = screen_height - height - 60 # Above taskbar
        
        self.root.geometry(f"{width}x{height}+{x_pos}+{y_pos}")
        self.root.attributes('-topmost', True) # Always on top
        self.root.attributes('-alpha', 0.95)   # Slight transparency
        
        # Remove standard title bar (Frameless feel)
        self.root.overrideredirect(True)
        
        # Allow moving window by dragging bg
        self.root.bind("<Button-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.do_move)

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def setup_ui(self):
        # 1. Header (Title + Close)
        header = tk.Frame(self.root, bg=self.bg_color, height=30)
        header.pack(fill='x', padx=10, pady=5)
        
        lbl = tk.Label(header, text="💠 Resonance AI Host", bg=self.bg_color, fg=self.accent_color, font=("Segoe UI", 10, "bold"))
        lbl.pack(side='left')
        
        close_btn = tk.Button(header, text="✕", bg=self.bg_color, fg="#ff5555", bd=0, command=self.root.destroy, font=("Arial", 10))
        close_btn.pack(side='right')

        # 2. Output Area (Display progress/response)
        self.display = scrolledtext.ScrolledText(
            self.root, 
            bg=self.input_bg, 
            fg=self.fg_color, 
            font=("Consolas", 9), 
            bd=0, 
            padx=10, 
            pady=10,
            state='disabled'
        )
        self.display.pack(expand=True, fill='both', padx=10, pady=(0, 10))
        self.display.tag_config('user', foreground='#a6e3a1') # Green
        self.display.tag_config('ai', foreground='#cdd6f4')   # White
        self.display.tag_config('tool', foreground='#fab387') # Orange
        self.display.tag_config('system', foreground='#7f849c', font=("Consolas", 8, "italic")) # Grey

        # 3. Input Area
        input_frame = tk.Frame(self.root, bg=self.bg_color)
        input_frame.pack(fill='x', padx=10, pady=10)
        
        self.input_field = tk.Text(
            input_frame, 
            height=2, 
            bg=self.input_bg, 
            fg="white", 
            bd=0, 
            font=("Segoe UI", 10),
            insertbackground="white"
        )
        self.input_field.pack(side='left', fill='x', expand=True)
        self.input_field.bind("<Control-Return>", self.send_message)
        
        send_btn = tk.Button(
            input_frame, 
            text="➤", 
            bg=self.accent_color, 
            fg=self.bg_color, 
            bd=0, 
            command=lambda: self.send_message(None),
            font=("Arial", 12, "bold")
        )
        send_btn.pack(side='right', padx=(5, 0))
        
        # Tip label
        tk.Label(self.root, text="Ctrl+Enter to send | /stop to interrupt", bg=self.bg_color, fg="#585b70", font=("Segoe UI", 8)).pack(side='bottom', pady=(0, 5))

    def log(self, text, tag='ai'):
        self.display.configure(state='normal')
        self.display.insert(tk.END, text + "\n", tag)
        self.display.see(tk.END)
        self.display.configure(state='disabled')

    def send_message(self, event):
        msg = self.input_field.get("1.0", tk.END).strip()
        if not msg: return
        
        self.input_field.delete("1.0", tk.END)
        self.log(f"You: {msg}", 'user')
        
        # If stop command, handle specifically
        if msg.strip() == "/stop":
            # Send stop command async
            threading.Thread(target=self._send_stop, args=(msg,)).start()
            return

        self.is_processing = True
        self.log("Thinking...", 'system')
        
        # Start request in thread
        threading.Thread(target=self._send_request, args=(msg,)).start()
        
        return "break" # Prevent newline in Text widget

    def _send_stop(self, msg):
        try:
            # Send stop signal to sync endpoint (backend handles /stop logic)
            requests.post(API_URL, json={"message": msg, "session_id": SESSION_ID})
            self.root.after(0, lambda: self.log("[System]: Interrupt signal sent.", 'system'))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"[Error]: {e}", 'system'))

    def _send_request(self, msg):
        try:
            payload = {
                "message": msg,
                "session_id": SESSION_ID
            }
            # This request blocks until completion (synchronous endpoint)
            # For a real HUD, ideally we'd use WebSocket here too, but to keep r_cli.py simple and compatible
            # with the provided requirements.txt (which lacks websocket-client lib typically), we use requests.
            # However, since the user asked for a HUD, the long-polling sync endpoint is okay for simple tasks.
            
            response = requests.post(API_URL, json=payload)
            data = response.json()
            
            if data.get("status") == "success":
                content = data.get("content", "")
                self.root.after(0, lambda: self.log(f"Resonance: {content}", 'ai'))
            else:
                err = data.get("content", "Unknown Error")
                self.root.after(0, lambda: self.log(f"[Error]: {err}", 'system'))
                
        except Exception as e:
            self.root.after(0, lambda: self.log(f"[Connection Error]: Is backend running? {e}", 'system'))
        finally:
            self.is_processing = False

    def poll_updates(self):
        """
        Since we use the sync endpoint for sending, we might miss intermediate tool outputs.
        This poller fetches the history every few seconds to update the UI with Tool outputs or async events.
        """
        last_len = 0
        while self.running:
            if self.is_processing:
                try:
                    res = requests.get(f"{HISTORY_URL}?session_id={SESSION_ID}", timeout=2)
                    history = res.json()
                    
                    if len(history) > last_len:
                        # Only show new messages (simplified logic)
                        # In a real app, you'd match IDs. Here we just grab the tail.
                        new_msgs = history[last_len:]
                        for m in new_msgs:
                            if m['role'] == 'tool':
                                self.root.after(0, lambda m=m: self.log(f"[Tool: {m.get('name')}] Output len: {len(m.get('content', ''))}", 'tool'))
                        
                        last_len = len(history)
                except:
                    pass
            else:
                # Sync length when idle to avoid dumping history on next start
                try:
                    res = requests.get(f"{HISTORY_URL}?session_id={SESSION_ID}", timeout=2)
                    last_len = len(res.json())
                except: pass
                
            time.sleep(2)

    def start(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = ResonanceHUD()
    app.start()