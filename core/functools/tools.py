# core/functools/tools.py
# [新增文件] 将工具逻辑与定义从 HostAgent 解耦
import os
import subprocess
import time
import json
import glob
from openai import OpenAI

class Toolbox:
    def __init__(self, agent):
        """
        初始化工具箱
        :param agent: HostAgent 实例，用于访问 config, profiles, memory 等
        """
        self.agent = agent

    def get_tool_definitions(self):
        """
        获取传递给 LLM 的 tools 定义 (JSON Schema)
        """
        # 动态获取当前可用脚本以生成描述
        available_scripts = self.agent.config.get('scripts', {})
        scripts_desc = ", ".join([f"'{k}' ({v.get('description', '')})" for k, v in available_scripts.items()])

        return [
            # 工具 1: 运行预定义技能 (Invoke Skill)
            {
                "type": "function",
                "function": {
                    "name": "invoke_skill", 
                    "description": f"Execute a specific pre-configured 'Skill' (automation script). Available skills: {scripts_desc}",
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
                    "description": "Execute a raw Windows PowerShell command for general tasks.",
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
        ]

    # --- 具体实现 ---

    def execute_shell(self, command, cwd=None, timeout=120):
        """执行 PowerShell 命令"""
        try:
            # 强制使用 UTF-8 编码解码，防止中文乱码
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            result = subprocess.run(
                ["powershell", "-Command", command],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout,
                encoding='gbk', # Windows PowerShell 默认输出通常是 GBK
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env
            )
            
            output = result.stdout
            if result.stderr:
                output += f"\n[STDERR]: {result.stderr}"
            
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
        
        # 拼接参数
        final_command = base_command
        if args_str:
            final_command = f"{base_command} {args_str}"
        
        # 处理延迟
        delay_sec = script_info.get('delay', 0)
        if delay_sec and delay_sec > 0:
            time.sleep(delay_sec)
            
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
    def list_directory_files(self, directory_path, recursive=True, depth=2):
        """
        递归列出目录文件，返回类似于 tree 命令的结构字符串。
        """
        if not os.path.exists(directory_path):
            return f"Error: Directory '{directory_path}' does not exist."

        if not os.path.isdir(directory_path):
            return f"Error: '{directory_path}' is not a directory."

        # 忽略列表
        IGNORE_DIRS = {'.git', '.idea', '.vscode', '__pycache__', 'node_modules', 'venv', '.obsidian'}
        IGNORE_EXTS = {'.exe', '.dll', '.so', '.dylib', '.class', '.pyc', '.png', '.jpg', '.jpeg', '.zip', '.tar', '.gz'}

        output_lines = []
        root_level = directory_path.rstrip(os.path.sep).count(os.path.sep)
        
        max_files_limit = 100 # 防止 context 爆炸
        file_count = 0

        for root, dirs, files in os.walk(directory_path):
            # 控制深度
            current_level = root.count(os.path.sep)
            if current_level - root_level > depth:
                continue
                
            # 过滤目录
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            # 计算缩进
            indent_level = current_level - root_level
            indent = "  " * indent_level
            
            folder_name = os.path.basename(root)
            if indent_level == 0:
                 output_lines.append(f"📂 {directory_path}")
            else:
                 output_lines.append(f"{indent}📂 {folder_name}/")

            # 列出文件
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in IGNORE_EXTS:
                    continue
                
                output_lines.append(f"{indent}  📄 {f}")
                file_count += 1
                
                if file_count >= max_files_limit:
                    output_lines.append(f"{indent}  ... [Truncated: Too many files]")
                    return "\n".join(output_lines)
            
            if not recursive:
                break
        
        if file_count == 0:
            return f"Directory '{directory_path}' is empty or contains only ignored file types."

        return "\n".join(output_lines)

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
            return f"No files found containing '{keyword}' (Scanned {scanned_count} files)."
        
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
            with open(self.agent.user_profile_path, 'w', encoding='utf-8') as f:
                json.dump(self.agent.user_data, f, ensure_ascii=False, indent=2) # 兼容 yaml 加载，但这里保持原逻辑写入yaml更好，这里为了Tools解耦，需要Agent提供保存接口，或者直接操作文件。
                # 修正：HostAgent 用的是 yaml，这里为了稳健，直接复用 Agent 的逻辑会更好。
                # 由于这是 Tool，直接操作文件可能不一致。
                # 更好的方式是修改 self.agent.user_data 后调用 agent.load_all_configs 刷新，但持久化需要写入。
                # 重新调用 yaml dump
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
