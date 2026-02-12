# core/functools/tools.py
# [修改说明] 修复了Windows下subprocess读取输出时的UnicodeDecodeError (GBK编码崩溃)
# [修改说明] 增强了 execute_shell 的鲁棒性，采用“混合解码”策略
# [修改说明] 集成 SkillManager 实现动态工具列表
import os
import sys
import subprocess
import time
import json
import threading
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
        [Visibility Control] 动态返回工具定义。
        逻辑：Native Tools + (Active Skill Tools OR Discovery Tool)
        """
        # 1. 始终可见的基础工具 (Native)
        tools = self._get_native_tools()

        # 2. [关键逻辑] 仅当 Skill 激活时，才暴露其专属工具
        if hasattr(self.agent, 'active_skill') and self.agent.active_skill:
            res = self.agent.skill_manager.load_skill_context(self.agent.active_skill)
            if res:
                _, skill_tools = res
                if skill_tools:
                    # 避免重复添加：检查工具名是否已存在
                    existing_names = {t['function']['name'] for t in tools if t['type'] == 'function'}
                    for st in skill_tools:
                        if st['function']['name'] not in existing_names:
                            tools.append(st)
        

        return tools
    
    def _get_native_tools(self):
        # 1. 基础内置工具
        tools = [
            # --- 技能管理 (认知负荷管理的核心) ---
            {
                "type": "function",
                "function": {
                    "name": "manage_skills",
                    "description": "Manage AI Skills. Use 'list_available' to see the index of skills. Use 'activate' to load a specific skill's SOP and tools.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["list_available", "activate", "deactivate_all"]},
                            "skill_name": {"type": "string", "description": "Required if action is 'activate'."}
                        },
                        "required": ["action"]
                    }
                }
            },
            # --- 核心能力 ---
            {
                "type": "function",
                "function": {
                    "name": "browse_url",
                    "description": "Visit a specific URL and extract its text content. Use this with URLs.",
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
            
            # --- [新增] 技能学习能力 ---
            {
                "type": "function",
                "function": {
                    "name": "learn_new_skill",
                    "description": "Dynamically learn a new skill from a GitHub URL or local path. Use this when the user asks you to 'learn' something or provides a link to an MCP tool/python script.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url_or_path": {
                                "type": "string",
                                "description": "The GitHub URL (starts with http) or absolute local file path to the skill folder."
                            }
                        },
                        "required": ["url_or_path"]
                    }
                }
            },

            # --- 文件系统能力 ---
            {
                "type": "function",
                "function": {
                    "name": "list_directory_files",
                    "description": "List files in a directory recursively. Use this to understand project structure or find specific files.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory_path": {"type": "string", "description": "The absolute path."},
                            "recursive": {"type": "boolean", "description": "Default True."},
                            "depth": {"type": "integer", "description": "Max depth (default 2)."}
                        },
                        "required": ["directory_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_files_by_keyword",
                    "description": "Grep search inside files.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory_path": {"type": "string"},
                            "keyword": {"type": "string"}
                        },
                        "required": ["directory_path", "keyword"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file_content",
                    "description": "Read text content of a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"}
                        },
                        "required": ["file_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_shell_command",
                    "description": "Execute a raw Windows PowerShell command. Use cautiously.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"}
                        },
                        "required": ["command"]
                    }
                }
            },
            
            # --- 记忆与配置 ---
            {
                "type": "function",
                "function": {
                    "name": "remember_user_fact",
                    "description": "Save a fact to long-term memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"}
                        },
                        "required": ["key", "value"]
                    }
                }
            }
        ]

        # 2. 动态加载 Legacy Scripts (config.yaml)
        available_scripts = self.agent.config.get('scripts', {})
        if available_scripts:
            scripts_desc = ", ".join([f"'{k}' ({v.get('description', '')})" for k, v in available_scripts.items()])
            tools.append({
                "type": "function",
                "function": {
                    "name": "invoke_legacy_script",
                    "description": f"Execute a pre-registered legacy automation script. Available: {scripts_desc}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "alias": {"type": "string", "description": "The exact script alias name."},
                            "args": {"type": "string", "description": "Optional arguments."}
                        },
                        "required": ["alias"]
                    }
                }
            })


        # 4. 哨兵系统工具
        tools.extend(self._get_sentinel_tools())


        return tools

    def _get_sentinel_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "add_time_sentinel",
                    "description": "Set a timer trigger.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "interval": {"type": "integer"},
                            "unit": {"type": "string", "enum": ["seconds", "minutes", "hours", "days"]},
                            "description": {"type": "string"}
                        },
                        "required": ["interval", "unit", "description"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "add_file_sentinel",
                    "description": "Watch a file/folder for changes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "description": {"type": "string"}
                        },
                        "required": ["path", "description"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "add_behavior_sentinel",
                    "description": "Register global hotkey.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key_combo": {"type": "string"},
                            "description": {"type": "string"}
                        },
                        "required": ["key_combo", "description"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_active_sentinels",
                    "description": "List sentinels.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_sentinel",
                    "description": "Remove sentinel.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "id": {"type": "string"}
                        },
                        "required": ["type", "id"]
                    }
                }
            }
        ]

    # --- 具体实现 ---

    def manage_skills(self, action, skill_name=None):
        """
        认知负荷管理工具的实现。
        """
        if action == "list_available":
            return self.agent.skill_manager.get_skill_index()
        
        elif action == "activate":
            if not skill_name:
                return "Error: skill_name is required for activation."
            # 调用 Agent 的方法来改变状态 (HostAgent 会处理 SOP 注入)
            return self.agent.activate_skill(skill_name)
            
        elif action == "deactivate_all":
            self.agent.active_skill = None
            return "All skills deactivated. Context cleaned."
            
        return "Unknown action."

    def route_skill_tool(self, tool_name, args):
        """
        如果 active_skill 存在，尝试在其中寻找并执行该工具。
        """
        if not self.agent.active_skill:
            return None # 没有激活的技能
        
        skill_name = self.agent.active_skill
        # 检查该工具是否属于当前技能 (简单检查：直接尝试执行)
        # 在更严谨的实现中，应该检查 tools.json
        return self.agent.skill_manager.execute_skill_tool(skill_name, tool_name, args)
    
    def learn_new_skill(self, url_or_path):
        """
        连接到 SkillManager 的学习方法
        """
        if not self.agent.skill_manager:
            return "Error: Skill Manager is not initialized."
        return self.agent.skill_manager.learn_skill(url_or_path)

    def _safe_decode(self, byte_data):
        """安全解码函数"""
        if not byte_data: return ""
        try: return byte_data.decode('utf-8')
        except: 
            try: return byte_data.decode('gbk')
            except: return byte_data.decode('utf-8', errors='ignore')

    def execute_shell(self, command, cwd=None, timeout=120, stop_event=None):
        """
        执行 PowerShell 命令 (支持实时中断版)
        [修改点] 支持传入 stop_event (threading.Event) 进行即时中断检测
        """
        try:
            # 环境准备：强制子进程使用 UTF-8，防止乱码
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["LANG"] = "C.UTF-8"
            
            # [修改点] 启动前检查
            if stop_event and stop_event.is_set():
                return "[System]: Command cancelled before execution."

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
                # 1. 检查是否被中断 (Robust Interrupt)
                if stop_event and stop_event.is_set():
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

    def invoke_registered_skill(self, alias, args_str="", stop_event=None):
        """运行 Config 中预定义的 Legacy Scripts"""
        scripts = self.agent.config.get('scripts', {})
        if alias not in scripts:
            return f"Error: Legacy Script '{alias}' not found."
        
        script_info = scripts[alias]
        base_command = script_info.get('command')
        cwd = script_info.get('cwd', None)
        
        # 修复产物堆积问题：如果 cwd 为空，强制使用 ./logs/workspace
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
                if stop_event and stop_event.is_set(): 
                    return "[System]: Skill delayed execution interrupted."
                time.sleep(0.1)
            
        # 获取超时配置
        timeout_sec = script_info.get('timeout', 120)
        
        return self.execute_shell(final_command, cwd=cwd, timeout=timeout_sec, stop_event=stop_event)

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
    def search_files_by_keyword(self, directory_path, keyword, stop_event=None):
        """
        简单粗暴的 grep 逻辑：遍历目录下所有文本文件，查找包含 keyword 的文件。
        [修改点] 支持 stop_event 中断
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
            if stop_event and stop_event.is_set():
                return "[System]: Search interrupted."

            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                if stop_event and stop_event.is_set():
                    return "[System]: Search interrupted."

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

    def run_browse_url(self, url):
        data = self.web_engine.fetch_page(url)
        if "error" in data:
            return f"Error browsing page: {data['error']}"
        
        return f"Title: {data['title']}\nURL: {data['url']}\n\n[Page Content]:\n{data['content']}"

    def sentinel_proxy(self, func_name, kwargs):
        """哨兵系统代理"""
        engine = self.agent.sentinel_engine
        if func_name == "add_time_sentinel":
            return engine.add_time_sentinel(kwargs['interval'], kwargs['unit'], kwargs['description'])
        elif func_name == "add_file_sentinel":
            return engine.add_file_sentinel(kwargs['path'], kwargs['description'])
        elif func_name == "add_behavior_sentinel":
            return engine.add_behavior_sentinel(kwargs['key_combo'], kwargs['description'])
        elif func_name == "list_active_sentinels":
            return json.dumps(engine.list_sentinels(), indent=2)
        elif func_name == "remove_sentinel":
            return str(engine.remove_sentinel(kwargs['type'], kwargs['id']))
        return "Unknown sentinel command"
    
    # 增加直接访问方法供 router 调用
    def add_time_sentinel(self, interval, unit, description):
        return self.agent.sentinel_engine.add_time_sentinel(interval, unit, description)
    def add_file_sentinel(self, path, description):
        return self.agent.sentinel_engine.add_file_sentinel(path, description)
    def add_behavior_sentinel(self, key_combo, description):
        return self.agent.sentinel_engine.add_behavior_sentinel(key_combo, description)
    def list_sentinels(self):
        return self.agent.sentinel_engine.list_sentinels()
    def remove_sentinel(self, type, id):
        return self.agent.sentinel_engine.remove_sentinel(type, id)