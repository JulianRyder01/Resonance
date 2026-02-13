# backend/core/skill_manager.py
import os
import sys
import yaml
import json
import shutil
import subprocess
import logging
import re
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("SkillManager")

class SkillManager:
    """
    Resonance Skill Engine (Anthropic-style Implementation)
    负责动态技能的发现、学习、环境隔离、SOP加载和元数据解析。
    遵循 "Discovery -> Activation -> Execution" 的认知负荷管理原则。
    """
    def __init__(self, agent):
        self.agent = agent
        # 获取 backend 根目录
        self.backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 技能存储路径
        config_path = self.agent.config.get('system', {}).get('skill_storage_path', '../SKILLS')
        if os.path.isabs(config_path):
            self.skills_root = config_path
        else:
            self.skills_root = os.path.abspath(os.path.join(self.backend_root, config_path))
        
        if not os.path.exists(self.skills_root):
            try:
                os.makedirs(self.skills_root, exist_ok=True)
                logger.info(f"Skills Root: {self.skills_root}")
            except Exception as e:
                logger.error(f"Failed to create skills directory: {e}")

        # 缓存已加载的技能定义
        # 缓存：name -> {path, metadata, tools_schema}
        self.skill_registry: Dict[str, Any] = {}
        
        # 1. 迁移遗留脚本 (Legacy Scripts -> New Skills)
        self.migrate_legacy_scripts()
        
        # 2. 扫描加载所有可用技能的元数据
        self.scan_skills()

    def migrate_legacy_scripts(self):
        """
        [自动迁移] 将 config.yaml 中的 scripts 转换为标准的 Skill 文件夹结构。
        """
        legacy_scripts = self.agent.config.get('scripts', {})
        if not legacy_scripts:
            return

        logger.info(f"Found {len(legacy_scripts)} legacy scripts. Migrating to Skill structure...")

        for alias, script_data in legacy_scripts.items():
            skill_dir = os.path.join(self.skills_root, alias)
            
            # 如果目标 Skill 文件夹不存在，则创建
            if not os.path.exists(skill_dir):
                os.makedirs(skill_dir, exist_ok=True)
                
                command = script_data.get('command', '')
                desc = script_data.get('description', 'Migrated legacy script.')
                
                # 1. 创建 SKILL.md (SOP)
                skill_md_content = f"""---
name: {alias}
description: "{desc}"
---

# {alias} SOP

## Overview
This skill executes a legacy automation script originally defined in config.yaml.

## Usage
Trigger this skill when the user asks to: {desc}

## Execution
The system will run the underlying command:
`{command}`

## Validation
After execution, check the output logs to ensure the script ran without errors (Exit Code 0).
"""
                with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                    f.write(skill_md_content)

                # 2. 创建 tools.json (Tool Definition)
                # 为遗留脚本生成一个通用的执行包装器
                tool_def = [{
                    "type": "function",
                    "function": {
                        "name": f"run_{alias}",
                        "description": f"Execute the {alias} script. {desc}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "additional_args": {
                                    "type": "string",
                                    "description": "Optional arguments to append to the command."
                                }
                            },
                            "required": []
                        }
                    }
                }]
                with open(os.path.join(skill_dir, "tools.json"), "w", encoding="utf-8") as f:
                    json.dump(tool_def, f, indent=2)

                # 3. 创建执行脚本 (wrapper.py)
                wrapper_content = f"""
import subprocess
import sys
import os

def main():
    base_cmd = r'{command}'
    args = sys.argv[1:]
    
    # 简单的命令拼接
    full_cmd = base_cmd + " " + " ".join(args)
    
    print(f"Executing: {{full_cmd}}")
    try:
        # 使用 shell=True 兼容复杂的 PowerShell 命令
        result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(result.stdout)
        if result.stderr:
            print(f"[STDERR]: {{result.stderr}}")
    except Exception as e:
        print(f"Execution Error: {{e}}")

if __name__ == "__main__":
    main()
"""
                with open(os.path.join(skill_dir, "wrapper.py"), "w", encoding="utf-8") as f:
                    f.write(wrapper_content)

        # 迁移完成后，清空 config 中的 scripts 以避免重复，但保留备份
        if legacy_scripts:
            self.agent.config['scripts_backup'] = legacy_scripts
            self.agent.config['scripts'] = {}
            self.agent.update_config(new_config=self.agent.config)
            logger.info("Legacy scripts migrated and removed from main config.")

    def scan_skills(self):
        """
        扫描 SKILLS 目录，解析 Frontmatter，建立索引。
        不加载全部内容，只加载元数据。
        """
        self.skill_registry.clear()
        
        if not os.path.exists(self.skills_root):
            return

        for dirname in os.listdir(self.skills_root):
            dir_path = os.path.join(self.skills_root, dirname)
            if not os.path.isdir(dir_path):
                continue

            skill_md_path = os.path.join(dir_path, "SKILL.md")
            if not os.path.exists(skill_md_path):
                continue

            try:
                # 解析 Frontmatter (YAML in header)
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 简单的 Frontmatter 解析器
                match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
                if match:
                    metadata = yaml.safe_load(match.group(1))
                    description = metadata.get('description', 'No description.')
                    
                    self.skill_registry[dirname] = {
                        "name": dirname,
                        "description": description,
                        "path": dir_path,
                        "metadata": metadata
                    }
            except Exception as e:
                logger.error(f"Error scanning skill {dirname}: {e}")
                
    # 找到 backend/core/skill_manager.py，在类中添加以下方法：

    def get_tool_definitions_json(self) -> List[Dict]:
        """
        [Discovery] 返回所有可用技能的工具定义列表。
        该方法遍历注册表，加载每个技能的 tools.json。
        """
        all_tools = []
        for skill_name in self.skill_registry:
            # 利用现有的 load_skill_context 获取工具定义
            res = self.load_skill_context(skill_name)
            if res:
                _, tools_def = res
                if tools_def:
                    all_tools.extend(tools_def)
        return all_tools
    def get_skill_index(self) -> str:
        """
        [Discovery] 返回所有可用技能的轻量级索引。
        格式: name: description
        """
        if not self.skill_registry:
            return "No specialized skills found."
        
        index_lines = []
        for name, data in self.skill_registry.items():
            index_lines.append(f"- {name}: {data['description']}")
        return "\n".join(index_lines)

    def load_skill_context(self, skill_name: str) -> Optional[Tuple[str, List[Dict]]]:
        """
        [Activation] 加载指定技能的完整上下文 (JIT Loading)。
        Returns: (SOP_Text, Tool_Definitions_List)
        """
        if skill_name not in self.skill_registry:
            return None
        
        skill_data = self.skill_registry[skill_name]
        dir_path = skill_data['path']
        
        # 1. 读取 SOP (去除 frontmatter 的剩余部分)
        sop_text = ""
        try:
            with open(os.path.join(dir_path, "SKILL.md"), 'r', encoding='utf-8') as f:
                content = f.read()
                # 移除 frontmatter，保留正文
                sop_text = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL).strip()
        except Exception as e:
            sop_text = f"Error loading SOP: {e}"

        # 2. 读取 Tools (tools.json)
        tools_def = []
        tools_path = os.path.join(dir_path, "tools.json")
        if os.path.exists(tools_path):
            try:
                with open(tools_path, 'r', encoding='utf-8') as f:
                    tools_def = json.load(f)
            except Exception as e:
                logger.error(f"Error loading tools.json for {skill_name}: {e}")
        
        return sop_text, tools_def

    def execute_skill_tool(self, skill_name: str, tool_name: str, args: Dict) -> str:
        """
        [Execution] 执行技能内部的具体工具。
        这里我们假设大多数工具是调用 python 脚本。
        """
        if skill_name not in self.skill_registry:
            return f"Error: Skill '{skill_name}' not found."

        skill_dir = self.skill_registry[skill_name]['path']
        
        # 简单的映射逻辑：如果是 run_<skill_name>，且存在 wrapper.py，则运行 wrapper
        # 在更复杂的实现中，tools.json 应该包含 execution configuration
        
        # 默认尝试运行 wrapper.py
        wrapper_path = os.path.join(skill_dir, "wrapper.py")
        
        if os.path.exists(wrapper_path):
            # 构建参数
            cmd_args = [sys.executable, wrapper_path]
            
            # 将 args 展平传入
            for k, v in args.items():
                if v:
                    cmd_args.append(str(v))
            
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                
                result = subprocess.run(
                    cmd_args, 
                    cwd=skill_dir, 
                    capture_output=True, 
                    text=True, 
                    encoding='utf-8',
                    errors='replace',
                    env=env
                )
                
                output = result.stdout
                if result.stderr:
                    output += f"\n[STDERR]: {result.stderr}"
                return output
            except Exception as e:
                return f"Execution failed: {e}"
        else:
            return f"Error: No executable 'wrapper.py' found for skill {skill_name}."

    # --- 以下为保留的辅助功能 (learn/delete) ---

    # [修复Bug 4] 修改返回类型为元组 (success: bool, message: str)
    def learn_skill(self, url_or_path: str) -> tuple:
        """
        [修复Bug 4] 动态学习技能
        支持 GitHub URL 或 本地绝对路径。
        返回: (success: bool, message: str)
        """
        try:
            skill_name = os.path.basename(url_or_path.rstrip("/\\")).replace(".git", "")
            target_dir = os.path.join(self.skills_root, skill_name)

            if os.path.exists(target_dir):
                return (False, f"Error: Skill '{skill_name}' already exists.")

            # 1. Fetch Source
            if url_or_path.startswith("http"):
                # Git Clone
                logger.info(f"Cloning {url_or_path}...")
                subprocess.run(["git", "clone", url_or_path, target_dir], check=True, capture_output=True)
            elif os.path.exists(url_or_path):
                # Local Copy
                logger.info(f"Copying from {url_or_path}...")
                shutil.copytree(url_or_path, target_dir)
            else:
                return (False, "Error: Invalid URL or Path. Please check if the path exists or the URL is correct.")

            # 2. Validate Structure - 检查SKILL.md是否存在
            if not os.path.exists(os.path.join(target_dir, "SKILL.md")):
                # 回滚：删除创建的文件
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
                return (False, "Error: Invalid Skill format. 'SKILL.md' is missing in the skill folder.")

            # 3. Install Dependencies (Optional)
            req_path = os.path.join(target_dir, "requirements.txt")
            if os.path.exists(req_path):
                try:
                    logger.info("Installing dependencies...")
                    subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path],
                                   check=True, capture_output=True, timeout=300)
                except subprocess.TimeoutExpired:
                    logger.warning("Dependency installation timed out, but continuing...")
                except Exception as e:
                    logger.warning(f"Failed to install dependencies: {e}")

            # 4. Refresh Registry - 重新扫描SKILLS目录
            self.scan_skills()

            # 验证skill是否被正确添加
            if skill_name in self.skill_registry:
                logger.info(f"Skill '{skill_name}' successfully learned and registered.")
                return (True, f"Success: Skill '{skill_name}' learned and registered.")
            else:
                logger.warning(f"Skill '{skill_name}' added but not found in registry after scan.")
                return (False, f"Warning: Skill folder created but failed to load. Please check the skill format.")

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"Git/pip operation failed: {error_msg}")
            return (False, f"Error during git/pip operation: {error_msg}")
        except shutil.Error as e:
            logger.error(f"File copy error: {e}")
            return (False, f"Error copying files: {str(e)}")
        except Exception as e:
            logger.error(f"Learn skill error: {e}")
            return (False, f"Error learning skill: {str(e)}")

    def delete_skill(self, skill_name: str) -> bool:
        if skill_name in self.skill_registry:
            try:
                shutil.rmtree(self.skill_registry[skill_name]['path'])
                self.scan_skills()
                return True
            except Exception as e: 
                logger.error(f"Error deleting skill {skill_name}: {e}")
                return False
        return False