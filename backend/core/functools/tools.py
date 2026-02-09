# core/functools/tools.py
# [修改说明] 修复了Windows下subprocess读取输出时的UnicodeDecodeError (GBK编码崩溃)
# [修改说明] 增强了 execute_shell 的鲁棒性，采用“混合解码”策略
import os
import sys
import subprocess
import time
import json
from core.functools.web_engine import WebEngine

class Toolbox:
    def __init__(self, agent):
        """
        初始化工具箱
        :param agent: HostAgent 实例，用于访问 config, profiles, memory 等
        """
        self.agent = agent
        # [修改点] 初始化联网引擎
        self.web_engine = WebEngine()

    def get_tool_definitions(self):
        """
        获取传递给 LLM 的 tools 定义 (JSON Schema)
        [优化] 为每个工具增加了详细的用法指导和 Context，特别是哨兵系统。
        """
        # 动态获取当前可用脚本以生成描述
        available_scripts = self.agent.config.get('scripts', {})
        scripts_desc = ", ".join([f"'{k}' ({v.get('description', '')})" for k, v in available_scripts.items()])

        return [
            # --- 核心能力 ---
            {
                "type": "function",
                "function": {
                    "name": "internet_search",
                    "description": "Perform a real-time internet search using DuckDuckGo. Use this when you need current events, news, documentation, or solutions to technical errors that are not in your memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search keywords."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "browse_website",
                    "description": "Visit a specific URL and extract its text content. Use this AFTER 'internet_search' provides you with URLs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL to visit (must start with http/https)."
                            }
                        },
                        "required": ["url"]
                    }
                }
            },

            # 工具 1: 运行预定义技能 (Invoke Skill)
            {
                "type": "function",
                "function": {
                    "name": "invoke_skill",
                    "description": f"Execute a pre-registered automation skill (script). PRIORITIZE this over raw shell commands if a matching skill exists. Available skills: {scripts_desc}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_alias": {
                                "type": "string",
                                "description": "The exact alias name of the skill to run."
                            },
                            "args": {
                                "type": "string",
                                "description": "Optional arguments/parameters to pass to the skill. e.g. '--target 127.0.0.1'"
                            }
                        },
                        "required": ["skill_alias"]
                    }
                }
            },
            # 工具 2: 通用 Shell
            {
                "type": "function",
                "function": {
                    "name": "execute_shell_command",
                    "description": "Execute a raw Windows PowerShell command. Use this for general tasks, installing pip packages, or running python scripts.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The PowerShell command string."
                            }
                        },
                        "required": ["command"]
                    }
                }
            },
            # 工具 3: 注册新技能
            {
                "type": "function",
                "function": {
                    "name": "add_automation_skill",
                    "description": "Register a NEW reusable Skill/Tool to the system for future use.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "alias": {"type": "string", "description": "Short unique name (e.g., 'backup_docs')."},
                            "command": {"type": "string", "description": "The full PowerShell command."},
                            "description": {"type": "string", "description": "What this skill does."}
                        },
                        "required": ["alias", "command", "description"]
                    }
                }
            },
            # 工具 4: 记忆项目路径
            {
                "type": "function",
                "function": {
                    "name": "scan_directory_projects",
                    "description": "Scan a folder to find and remember user projects (Top-level folders only). Updates Long-term Memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Full Windows path to scan."}
                        },
                        "required": ["path"]
                    }
                }
            },

            # 工具 5: 记忆通用事实
            {
                "type": "function",
                "function": {
                    "name": "remember_user_fact",
                    "description": "Save a fact about the user or system to long-term memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Category (e.g., 'name', 'ssh_key_path')."},
                            "value": {"type": "string", "description": "The information to save."}
                        },
                        "required": ["key", "value"]
                    }
                }
            },
            
            # ---------------------------------------------------------------------
            # [新增工具 / 修改工具] 增强文件系统能力
            # ---------------------------------------------------------------------
            
            # 工具: 递归列出文件 (File Explorer Awareness)
            {
                "type": "function",
                "function": {
                    "name": "list_directory_files",
                    "description": "List files in a directory recursively. Use this to understand project structure or find specific files when you don't know the exact name. It filters out binary/hidden files automatically.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory_path": {
                                "type": "string",
                                "description": "The absolute path to the directory."
                            },
                            "recursive": {
                                "type": "boolean",
                                "description": "Whether to list subdirectories. Default is True."
                            },
                            "depth": {
                                "type": "integer", 
                                "description": "Max recursion depth. Default is 2 to prevent token overflow."
                            }
                        },
                        "required": ["directory_path"]
                    }
                }
            },

            # 工具: 搜索文件内容 (Grep Capability)
            {
                "type": "function",
                "function": {
                    "name": "search_files_by_keyword",
                    "description": "Search for a text keyword INSIDE files within a directory. Useful when looking for specific information (e.g. 'research', 'todo') but you don't know which file contains it.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory_path": {
                                "type": "string", 
                                "description": "Directory to search in."
                            },
                            "keyword": {
                                "type": "string", 
                                "description": "The text to search for."
                            }
                        },
                        "required": ["directory_path", "keyword"]
                    }
                }
            },

            # 工具: 读取文件 (增强描述)
            {
                "type": "function",
                "function": {
                    "name": "read_file_content",
                    "description": "Read the full text content of a specific file. Use this AFTER finding interesting files via 'list_directory_files' or 'search_files_by_keyword'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "The absolute path of the file to read."}
                        },
                        "required": ["file_path"]
                    }
                }
            },

            # ---------------------------------------------------------------------
            # [新增工具] 哨兵系统 (Sentinel System)
            # ---------------------------------------------------------------------
            {
                "type": "function",
                "function": {
                    "name": "add_time_sentinel",
                    "description": "Set a delayed trigger (Timer). Use this when the user says 'Remind me in 10 mins' or 'Check the download later'. When the time is up, the system will wake up and notify the user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "interval": {"type": "integer", "description": "Numeric value (e.g. 30)."},
                            "unit": {"type": "string", "enum": ["seconds", "minutes", "hours", "days"]},
                            "description": {"type": "string", "description": "The message/task to execute when time is up."}
                        },
                        "required": ["interval", "unit", "description"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "add_file_sentinel",
                    "description": "Monitor a specific file or folder for ANY changes (modify/delete/create). Use this when the user says 'Watch this file' or 'Tell me when the log updates'. Alerts represent real-time feedback.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Absolute Windows path to watch."},
                            "description": {"type": "string", "description": "Reason for watching (e.g. 'Alert if build log updates')."}
                        },
                        "required": ["path", "description"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "add_behavior_sentinel",
                    "description": "Register a global hotkey (keyboard shortcut). When pressed by the user, you will be woken up to perform an action.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key_combo": {"type": "string", "description": "Key combination (e.g. 'ctrl+shift+a', 'f9')."},
                            "description": {"type": "string", "description": "What to do when this key is pressed."}
                        },
                        "required": ["key_combo", "description"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_active_sentinels",
                    "description": "List all currently active Sentinels (Time, File, Behavior).",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_sentinel",
                    "description": "Stop and remove a specific sentinel.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["time", "file", "behavior"]},
                            "id": {"type": "string", "description": "The Sentinel ID found in 'list_active_sentinels'."}
                        },
                        "required": ["type", "id"]
                    }
                }
            }
        ]

    # --- 具体实现 ---

    def _safe_decode(self, byte_data):
        """
        [新增] 安全解码函数：解决 Windows 终端 GBK 与 UTF-8 混杂导致的崩溃问题
        """
        if not byte_data:
            return ""
        
        # 1. 优先尝试 UTF-8 (最通用)
        try:
            return byte_data.decode('utf-8')
        except UnicodeDecodeError:
            pass
        
        # 2. 尝试 GBK (Windows 默认)
        try:
            return byte_data.decode('gbk')
        except UnicodeDecodeError:
            pass
        
        # 3. 最后尝试忽略错误的 UTF-8
        return byte_data.decode('utf-8', errors='ignore')

    def execute_shell(self, command, cwd=None, timeout=120):
        """
        执行 PowerShell 命令 (支持实时中断版)
        [修改点] 使用 Popen + Polling 替代 run，以便在 stop_flag 为 True 时 kill 进程
        """
        try:
            # 环境准备：强制子进程使用 UTF-8，防止乱码
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["LANG"] = "C.UTF-8"
            
            # 使用 Popen 启动进程
            process = subprocess.Popen(
                ["powershell", "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env
            )
            
            start_time = time.time()
            
            # 轮询检查循环
            while True:
                # 1. 检查是否被中断 (Bug ③ Fix)
                if self.agent.stop_flag:
                    process.kill()
                    return "[System]: Command execution was interrupted by user."
                
                # 2. 检查是否超时
                if time.time() - start_time > timeout:
                    process.kill()
                    return f"[Error]: Command timed out after {timeout}s."
                
                # 3. 检查进程是否结束
                retcode = process.poll()
                if retcode is not None:
                    break
                
                # 避免 CPU 空转
                time.sleep(0.1)
            
            # 获取输出
            stdout_data, stderr_data = process.communicate()
            
            # 手动安全解码
            stdout_str = self._safe_decode(stdout_data)
            stderr_str = self._safe_decode(stderr_data)
            
            output = stdout_str
            if stderr_str:
                output += f"\n[STDERR]: {stderr_str}"
            
            if not output.strip():
                return "[System]: Command executed successfully (No visual output)."
                
            return output
        except subprocess.TimeoutExpired:
            return f"[Error]: Command timed out after {timeout}s."
        except Exception as e:
            return f"[System Error]: {str(e)}"

    def invoke_registered_skill(self, skill_alias, args_str=""):
        """运行 Config 中预定义的技能"""
        scripts = self.agent.config.get('scripts', {})
        
        if skill_alias not in scripts:
            return f"Error: Skill '{skill_alias}' not found in configuration."
        
        script_info = scripts[skill_alias]
        base_command = script_info.get('command')
        cwd = script_info.get('cwd', None)
        
        # [修改点] 修复产物堆积问题：如果 cwd 为空，强制使用 ./logs/workspace
        if not cwd:
            # 获取日志目录，默认为 ./logs
            log_dir = self.agent.config.get('system', {}).get('log_dir', './logs')
            # 构造 workspace 路径
            workspace_dir = os.path.abspath(os.path.join(log_dir, 'workspace'))
            if not os.path.exists(workspace_dir):
                os.makedirs(workspace_dir, exist_ok=True)
            
            cwd = workspace_dir
            # print(f"[System]: Skill execution redirected to workspace: {cwd}")
        
        # 拼接参数
        final_command = base_command
        if args_str:
            final_command = f"{base_command} {args_str}"
        
        # 处理延迟
        delay_sec = script_info.get('delay', 0)
        if delay_sec and delay_sec > 0:
            # 支持延迟期间中断
            for _ in range(int(delay_sec * 10)):
                if self.agent.stop_flag: return "[System]: Skill delayed execution interrupted."
                time.sleep(0.1)
            
        # 获取超时配置
        timeout_sec = script_info.get('timeout', 120)
        
        return self.execute_shell(final_command, cwd=cwd, timeout=timeout_sec)

    # [修改点] 增强文件读取逻辑
    def read_file_content(self, file_path):
        """读取文件内容，带安全限制与多编码尝试"""
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' does not exist."
            
        # 简单判断是否是常见的二进制文件
        ext = os.path.splitext(file_path)[1].lower()
        binary_exts = ['.exe', '.dll', '.png', '.jpg', '.zip', '.pdf', '.docx']
        if ext in binary_exts:
             return f"[System Warning]: File '{os.path.basename(file_path)}' appears to be binary or requires special parsing ({ext}). Reading raw text is skipped."

        MAX_SIZE = 50 * 1024 # 50KB Limit
        try:
            file_size = os.path.getsize(file_path)
            content = ""
            
            # 尝试 UTF-8
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    if file_size > MAX_SIZE:
                        content = f.read(MAX_SIZE)
                        content += f"\n\n[System Warning]: File content truncated (Size: {file_size} bytes). Read first {MAX_SIZE} bytes."
                    else:
                        content = f.read()
            except UnicodeDecodeError:
                # 失败则尝试 GBK
                with open(file_path, 'r', encoding='gbk', errors='replace') as f:
                    if file_size > MAX_SIZE:
                        content = f.read(MAX_SIZE)
                        content += f"\n\n[System Warning]: File content truncated. (Read with GBK fallback)"
                    else:
                        content = f.read()
            
            return content
        except Exception as e:
            return f"Error reading file: {str(e)}"

    # [新增] 目录列表工具
    # [修改后] 增强版目录列表工具：支持树状结构显示，确保文件夹不遗漏
    def list_directory_files(self, directory_path, recursive=True, depth=2):
        """
        列出目录下的文件和文件夹结构。
        :param directory_path: 绝对路径
        :param recursive: 是否递归遍历
        :param depth: 递归深度限制
        """
        if not os.path.exists(directory_path):
            return f"Error: Directory '{directory_path}' does not exist."

        if not os.path.isdir(directory_path):
            return f"Error: '{directory_path}' is not a directory."

        # 忽略列表
        IGNORE_DIRS = {'.git', '.idea', '.vscode', '__pycache__', 'node_modules', 'venv', '.obsidian'}
        IGNORE_EXTS = {'.exe', '.dll', '.so', '.dylib', '.class', '.pyc', '.png', '.jpg', '.jpeg', '.zip', '.tar', '.gz'}

        results = []
        self.file_count = 0
        self.max_files_limit = 150  # 适当增加上限，防止遗漏关键结构

        def _build_tree(current_dir, current_depth, prefix=""):
            if current_depth > depth:
                return

            try:
                # 获取目录下所有项并排序（文件夹在前，文件在后）
                entries = os.listdir(current_dir)
                entries.sort(key=lambda x: (not os.path.isdir(os.path.join(current_dir, x)), x.lower()))
            except Exception as e:
                results.append(f"{prefix}[Permission Denied: {e}]")
                return

            for i, entry in enumerate(entries):
                if self.file_count >= self.max_files_limit:
                    if i == 0: results.append(f"{prefix}... [Output truncated due to limit]")
                    break

                full_path = os.path.join(current_dir, entry)
                is_last = (i == len(entries) - 1)
                connector = "└── " if is_last else "├── "
                
                # 检查是否在忽略名单
                if entry in IGNORE_DIRS:
                    continue

                if os.path.isdir(full_path):
                    # 添加文件夹标识
                    results.append(f"{prefix}{connector}📂 {entry}/")
                    
                    # 如果允许递归且未达深度限制，继续向下走
                    if recursive and current_depth < depth:
                        new_prefix = prefix + ("    " if is_last else "│   ")
                        _build_tree(full_path, current_depth + 1, new_prefix)
                else:
                    # 检查文件后缀过滤
                    ext = os.path.splitext(entry)[1].lower()
                    if ext in IGNORE_EXTS:
                        continue
                        
                    results.append(f"{prefix}{connector}📄 {entry}")
                    self.file_count += 1

        # 开始构建
        results.append(f"📂 {directory_path}")
        _build_tree(directory_path, 0)

        if len(results) <= 1:
            return f"Directory '{directory_path}' is empty or contains only ignored items."

        return "\n".join(results)

    # [新增] 关键词搜索工具
    def search_files_by_keyword(self, directory_path, keyword):
        """
        简单粗暴的 grep 逻辑：遍历目录下所有文本文件，查找包含 keyword 的文件。
        """
        if not os.path.exists(directory_path):
            return f"Error: Path '{directory_path}' not found."

        found_files = []
        scanned_count = 0
        MAX_SCAN = 50 # 限制扫描文件数，防止性能卡顿
        
        # 忽略配置
        IGNORE_DIRS = {'.git', '.obsidian', 'node_modules', '__pycache__'}
        TEXT_EXTS = {'.md', '.txt', '.py', '.json', '.yaml', '.csv', '.log', '.xml', '.html', '.css', '.js'}

        for root, dirs, files in os.walk(directory_path):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                if scanned_count > MAX_SCAN:
                    break
                    
                ext = os.path.splitext(file)[1].lower()
                if ext not in TEXT_EXTS:
                    continue
                
                full_path = os.path.join(root, file)
                scanned_count += 1
                
                # 尝试读取并查找
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if keyword.lower() in content.lower():
                            found_files.append(full_path)
                except:
                    pass
            
            if scanned_count > MAX_SCAN:
                break
        
        if not found_files:
            return f"{directory_path}: No files found containing '{keyword}' (Scanned {scanned_count} files)."
        
        # 返回结果列表
        result_text = f"Found '{keyword}' in the following files:\n"
        for path in found_files:
            result_text += f"- {path}\n"
        result_text += "\n(You can now use 'read_file_content' to read specific files from this list.)"
        return result_text

    def add_new_script(self, alias, command, description):
        """动态添加新工具到 config"""
        try:
            current_scripts = self.agent.config.get('scripts', {})
            current_scripts[alias] = {
                "command": command,
                "description": description,
                "cwd": None,
                "timeout": 120,
                "delay": 0
            }
            self.agent.config['scripts'] = current_scripts
            self.agent.update_config(new_config=self.agent.config)
            return f"Success: New Skill '{alias}' added. I can now use it to: {description}"
        except Exception as e:
            return f"Error adding script: {e}"

    def scan_and_remember(self, target_path, scan_type="projects"):
        """扫描文件夹并记忆路径"""
        try:
            if not os.path.exists(target_path):
                return f"Error: Path '{target_path}' does not exist."

            found_items = {}
            if scan_type == "projects":
                # 只扫描一级子目录
                subdirs = [os.path.join(target_path, d) for d in os.listdir(target_path) if os.path.isdir(os.path.join(target_path, d))]
                
                for d in subdirs:
                    dir_name = os.path.basename(d)
                    if any(os.path.exists(os.path.join(d, marker)) for marker in ['.git', 'package.json', 'requirements.txt', 'pom.xml', '.obsidian']):
                        found_items[dir_name] = d
                
                # 更新 Agent 的 user_data
                if 'known_projects' not in self.agent.user_data:
                    self.agent.user_data['known_projects'] = {}
                
                self.agent.user_data['known_projects'].update(found_items)
                
            # 保存到文件
            import yaml
            with open(self.agent.user_profile_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.agent.user_data, f, allow_unicode=True)
            
            # 刷新 Agent 内存
            self.agent.load_all_configs()
            self.agent._init_client() # 刷新 System Prompt
            
            return f"Scan complete. Remembered {len(found_items)} projects/notes in '{target_path}'. Memory updated."
            
        except Exception as e:
            return f"Error processing memory: {e}"

    def remember_user_fact(self, key, value):
        """记录事实"""
        try:
            if 'user_info' not in self.agent.user_data:
                self.agent.user_data['user_info'] = {}
            
            self.agent.user_data['user_info'][key] = value
            
            import yaml
            with open(self.agent.user_profile_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.agent.user_data, f, allow_unicode=True)
                
            self.agent.load_all_configs()
            self.agent._init_client()
            return f"Memory updated: {key} = {value}"
        except Exception as e:
            return f"Error saving fact: {e}"
    
    # [新增] 联网能力实现方法
    def run_internet_search(self, query):
        results = self.web_engine.search(query)
        if not results:
            return "No results found."
        
        # 格式化为可读字符串
        output = f"Search Results for '{query}':\n\n"
        for i, res in enumerate(results, 1):
            output += f"{i}. {res['title']}\n   URL: {res['url']}\n   Snippet: {res['snippet']}\n\n"
        output += "(Use 'browse_website' with a specific URL to read full content)"
        return output

    def run_browse_website(self, url):
        data = self.web_engine.fetch_page(url)
        if "error" in data:
            return f"Error browsing page: {data['error']}"
        
        return f"Title: {data['title']}\nURL: {data['url']}\n\n[Page Content]:\n{data['content']}"

    # --- 哨兵系统方法 ---
    def add_time_sentinel(self, interval, unit, description):
        s_id = self.agent.sentinel_engine.add_time_sentinel(interval, unit, description)
        return f"✅ Time Sentinel Set! (ID: {s_id})\nI will trigger every {interval} {unit} to: {description}"

    def add_file_sentinel(self, path, description):
        s_id = self.agent.sentinel_engine.add_file_sentinel(path, description)
        if "Error" in str(s_id): return s_id
        return f"✅ File Sentinel Set! (ID: {s_id})\nWatching: {path}\nReason: {description}"

    def add_behavior_sentinel(self, key_combo, description):
        s_id = self.agent.sentinel_engine.add_behavior_sentinel(key_combo, description)
        return f"✅ Behavior Sentinel Set! (ID: {s_id})\nHotkey: {key_combo}\nAction: {description}"

    def list_sentinels(self):
        data = self.agent.sentinel_engine.list_sentinels()
        return json.dumps(data, indent=2, ensure_ascii=False)

    def remove_sentinel(self, s_type, s_id):
        if self.agent.sentinel_engine.remove_sentinel(s_type, s_id):
            return f"Sentinel {s_id} removed."
        return "Error: Sentinel not found."