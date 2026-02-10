# backend/core/skill_manager.py
import os
import sys
import yaml
import json
import shutil
import subprocess
import venv
import logging
import platform
import hashlib
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger("SkillManager")

class SkillManager:
    """
    Resonance Skill Engine (MCP-like Implementation)
    负责动态技能的发现、环境隔离、依赖安装和元数据解析。
    """
    def __init__(self, agent):
        self.agent = agent
        # 获取 backend 根目录
        self.backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # [修改] 读取配置中的技能存储路径，若无则默认 ../SKILLS
        config_path = self.agent.config.get('system', {}).get('skill_storage_path', '../SKILLS')
        if os.path.isabs(config_path):
            self.skills_root = config_path
        else:
            self.skills_root = os.path.abspath(os.path.join(self.backend_root, config_path))
        
        if not os.path.exists(self.skills_root):
            try:
                os.makedirs(self.skills_root, exist_ok=True)
                logger.info(f"Created Skills Root: {self.skills_root}")
            except Exception as e:
                logger.error(f"Failed to create skills directory: {e}")

        # 缓存已加载的技能定义
        self.loaded_skills: Dict[str, Any] = {}
        self._load_all_skills()

    def _load_all_skills(self):
        """启动时加载 config 中记录的所有已导入技能，并进行文件系统校验"""
        imported = self.agent.config.get('imported_skills', {})
        valid_skills = {}
        
        # 扫描 config 中记录的技能
        for skill_name, skill_info in imported.items():
            path = skill_info.get('path')
            # 修正路径：如果是相对路径，基于 skills_root
            if not os.path.isabs(path):
                full_path = os.path.join(self.skills_root, skill_name)
            else:
                full_path = path

            if os.path.exists(full_path):
                try:
                    self._parse_and_register(full_path, skill_name)
                    valid_skills[skill_name] = skill_info
                except Exception as e:
                    logger.error(f"Failed to load skill '{skill_name}': {e}")
            else:
                logger.warning(f"Skill '{skill_name}' path not found at {full_path}. Marking for removal.")
        
        # 更新 config，移除无效技能
        if len(valid_skills) != len(imported):
            self.agent.config['imported_skills'] = valid_skills
            self.agent.update_config(new_config=self.agent.config)

    def learn_skill(self, url_or_path: str) -> str:
        """
        [核心入口] 学习新技能
        1. 识别是 URL 还是本地路径
        2. 下载/复制到 SKILLS 目录
        3. 创建隔离环境 (venv)
        4. 安装依赖
        5. 注册到系统
        """
        try:
            skill_name = self._generate_skill_name(url_or_path)
            target_dir = os.path.join(self.skills_root, skill_name)

            logger.info(f"Learning skill: {skill_name} from {url_or_path}")

            # 1. 获取代码
            if url_or_path.startswith("http"):
                # Git Clone
                if os.path.exists(target_dir):
                    return f"Skill '{skill_name}' already exists. Please delete it first if you want to update."
                
                logger.info(f"Cloning {url_or_path}...")
                # 检查 git 是否安装
                try:
                    subprocess.check_call(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    return "Error: 'git' command not found. Please install Git."

                subprocess.check_call(["git", "clone", url_or_path, target_dir])
            else:
                # Local Path Copy
                if not os.path.exists(url_or_path):
                    return f"Error: Source path '{url_or_path}' does not exist."
                
                # 如果源路径就是目标路径（原地加载），则不复制
                if os.path.abspath(url_or_path) == os.path.abspath(target_dir):
                    logger.info("Loading skill in-place.")
                else:
                    if os.path.exists(target_dir):
                        shutil.rmtree(target_dir)
                    # 忽略 venv 和 .git 目录防止递归复制
                    shutil.copytree(url_or_path, target_dir, ignore=shutil.ignore_patterns('venv', '.git', '__pycache__'))

            # 2. 环境设置 (Venv + Requirements)
            env_setup_log = self._setup_environment(target_dir)

            # 3. 解析元数据并注册
            meta_log = self._parse_and_register(target_dir, skill_name)

            # 4. 持久化到 Config
            self._persist_skill(skill_name, target_dir, url_or_path)

            return f"✅ Successfully learned skill '{skill_name}'!\n\n[Environment]: {env_setup_log}\n[Registry]: {meta_log}"

        except Exception as e:
            logger.error(f"Failed to learn skill: {e}")
            import traceback
            return f"❌ Failed to learn skill: {str(e)}\nTrace: {traceback.format_exc()}"

    def delete_skill(self, skill_name: str) -> bool:
        """删除技能"""
        if skill_name in self.agent.config.get('imported_skills', {}):
            # 1. 从内存移除
            if skill_name in self.loaded_skills:
                del self.loaded_skills[skill_name]
            
            # 2. 从配置移除
            del self.agent.config['imported_skills'][skill_name]
            self.agent.update_config(new_config=self.agent.config)
            
            # 3. 删除文件
            target_dir = os.path.join(self.skills_root, skill_name)
            if os.path.exists(target_dir):
                try:
                    shutil.rmtree(target_dir)
                except Exception as e:
                    logger.error(f"Failed to delete directory {target_dir}: {e}")
            
            return True
        return False

    def _setup_environment(self, skill_dir: str) -> str:
        """
        为技能创建独立的 Python 虚拟环境并安装依赖。
        防止依赖冲突 (Dependency Hell)。
        """
        venv_dir = os.path.join(skill_dir, "venv")
        req_file = os.path.join(skill_dir, "requirements.txt")
        log = []

        # 1. 创建 venv
        if not os.path.exists(venv_dir):
            log.append("Creating virtual environment...")
            try:
                venv.create(venv_dir, with_pip=True)
            except Exception as e:
                # Fallback: try using subprocess if venv module fails (sometimes happens in conda)
                subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
        
        # 获取 venv 中的 python 可执行文件路径
        if platform.system() == "Windows":
            python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
        else:
            python_exe = os.path.join(venv_dir, "bin", "python")

        if not os.path.exists(python_exe):
            raise FileNotFoundError(f"Virtual environment creation failed. Cannot find: {python_exe}")

        # 2. 安装依赖
        if os.path.exists(req_file):
            log.append(f"Installing dependencies from {os.path.basename(req_file)}...")
            try:
                # 使用 check_output 捕获输出，合并 stderr 到 stdout
                # 添加 pip 升级和超时设置
                subprocess.check_call([python_exe, "-m", "pip", "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL)
                
                output = subprocess.check_output(
                    [python_exe, "-m", "pip", "install", "-r", req_file, "--timeout", "60"],
                    stderr=subprocess.STDOUT,
                    cwd=skill_dir
                )
                log.append("Dependencies installed successfully.")
            except subprocess.CalledProcessError as e:
                err_msg = e.output.decode('utf-8', errors='ignore')
                log.append(f"Dependency installation failed:\n{err_msg}")
                raise RuntimeError(f"Failed to install dependencies: {err_msg}")
        else:
            log.append("No requirements.txt found. Skipping dependency installation.")

        return " | ".join(log)

    def _parse_and_register(self, skill_dir: str, skill_name: str) -> str:
        """
        解析 skill.yaml (Anthropic Format) 或 mcp.json，并注册到内存。
        """
        # 尝试寻找定义文件
        yaml_path = os.path.join(skill_dir, "skill.yaml")
        json_path = os.path.join(skill_dir, "mcp.json")
        
        definition = None
        
        if os.path.exists(yaml_path):
            with open(yaml_path, 'r', encoding='utf-8') as f:
                definition = yaml.safe_load(f)
        elif os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                definition = json.load(f)
        
        # 自动推断 (Fallback)
        if not definition:
            # 尝试自动推断 (Fallback): 如果没有定义文件，查看是否有 main.py
            if os.path.exists(os.path.join(skill_dir, "main.py")):
                definition = {
                    "name": skill_name,
                    "description": f"Auto-detected skill '{skill_name}'. Runs main.py. Pass arguments as --key value.",
                    "entry_point": "main.py",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "args": {"type": "string", "description": "Command line arguments string"}
                        },
                        "additionalProperties": True # Allow flexible args
                    }
                }
            else:
                raise FileNotFoundError("No skill.yaml, mcp.json, or main.py found in skill directory.")

        # 确定 Entry Point
        entry_point = definition.get('entry_point') or definition.get('main') or 'main.py'
        full_entry_path = os.path.join(skill_dir, entry_point)
        
        if not os.path.exists(full_entry_path):
             raise FileNotFoundError(f"Entry point '{entry_point}' defined but not found.")

        # 保存到内存
        self.loaded_skills[skill_name] = {
            "name": definition.get('name', skill_name),
            "description": definition.get('description', 'No description provided.'),
            "input_schema": definition.get('input_schema', {}),
            "root_dir": skill_dir,
            "entry_point": full_entry_path,
            "venv_python": self._get_venv_python(skill_dir)
        }
        
        return f"Registered Skill: {skill_name}"

    def _get_venv_python(self, skill_dir):
        if platform.system() == "Windows":
            return os.path.join(skill_dir, "venv", "Scripts", "python.exe")
        return os.path.join(skill_dir, "venv", "bin", "python")

    def _persist_skill(self, name, path, source):
        """更新 config.yaml"""
        if 'imported_skills' not in self.agent.config:
            self.agent.config['imported_skills'] = {}
        
        self.agent.config['imported_skills'][name] = {
            "path": path,
            "source": source,
            "added_at": str(time.time()),
            "description": self.loaded_skills[name]['description']
        }
        self.agent.update_config(new_config=self.agent.config)

    def _generate_skill_name(self, url_or_path):
        """根据 URL 或路径生成简洁的文件夹名"""
        if url_or_path.startswith("http"):
            # 取 URL 最后一段作为基础名
            base = url_or_path.rstrip('/').split('/')[-1].replace('.git', '')
            # 加个 hash 防止重名冲突
            h = hashlib.md5(url_or_path.encode()).hexdigest()[:5]
            return f"{base}_{h}"
        else:
            base = os.path.basename(os.path.normpath(url_or_path))
            return base.replace(" ", "_").lower()

    def get_tool_definitions_json(self) -> List[Dict]:
        """
        生成兼容 OpenAI 的 Tool Definition List
        """
        tools = []
        for name, data in self.loaded_skills.items():
            # OpenAI Schema Format
            # 这里的 name 必须唯一，我们加上前缀
            func_name = f"skill_{name}"
            
            tool_def = {
                "type": "function",
                "function": {
                    "name": func_name,
                    "description": f"[Imported Skill] {data['description']}",
                    "parameters": data['input_schema']
                }
            }
            tools.append(tool_def)
        return tools

    def execute_skill(self, skill_name_prefixed: str, args: Dict) -> str:
        """
        执行技能
        1. 找到对应的 venv python
        2. 构造命令行参数
        3. 调用 subprocess
        """
        # 移除前缀 skill_
        real_name = skill_name_prefixed.replace("skill_", "", 1)
        
        if real_name not in self.loaded_skills:
            return f"Error: Skill '{real_name}' not loaded."

        skill = self.loaded_skills[real_name]
        python_exe = skill['venv_python']
        script_path = skill['entry_point']
        cwd = skill['root_dir']

        if not os.path.exists(python_exe):
            return f"Error: Virtual environment python not found at {python_exe}. Try relearning the skill."

        # 构造调用参数
        # 策略：我们将所有参数序列化为一个 JSON 字符串，并通过 --input 传递
        # 这要求 skill 的 entry_point 能够处理 --input 参数
        # 或者，如果 skill.yaml 定义了特定的参数映射，我们需要在这里做适配
        # 为了通用性，我们采用 "Pass Input as JSON Env Var" 或 "Standard Input"
        
        # 这里使用比较通用的方式：将参数作为 JSON 字符串通过 stdin 传入，
        # 或者如果是 Anthropic 官方的某些 skill，它们可能期望 --arg value。
        # 作为一个通用 Host，我们尝试最稳健的方法：
        # 传递一个特殊的 wrapper 脚本逻辑，或者简单地将 args 转为 key-value pair 传参。
        
        # 假设：Import 的 Skill 是标准的 Python 脚本，接收 argparse。
        # 我们尝试将 JSON 展平为命令行参数
        
        cmd_args = [python_exe, script_path]
        
        # 策略：简单的参数展开 key=value -> --key value
        # 对于复杂对象，有些 skill 可能期望 JSON 字符串
        for k, v in args.items():
            cmd_args.append(f"--{k}")
            if isinstance(v, (dict, list)):
                cmd_args.append(json.dumps(v))
            else:
                cmd_args.append(str(v))

        logger.info(f"Executing Skill: {' '.join(cmd_args)}")

        try:
            # 设置环境变量，确保无缓冲输出
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            process = subprocess.Popen(
                cmd_args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,  # Auto decode
                encoding='utf-8',
                errors='replace'
            )
            
            stdout, stderr = process.communicate(timeout=240) # 4分钟超时
            
            result = ""
            if stdout:
                result += f"[Output]:\n{stdout.strip()}\n"
            if stderr:
                result += f"[Stderr]:\n{stderr.strip()}"
                
            return result if result else "Skill executed successfully (No Visual Output)."

        except subprocess.TimeoutExpired:
            process.kill()
            return "Error: Skill execution timed out (2400s)."
        except Exception as e:
            return f"Error executing skill: {str(e)}"