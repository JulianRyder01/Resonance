# core/host_agent.py
import yaml
import json
import os
import time
import threading
from openai import OpenAI
from core.memory import ConversationMemory
# [修改点] 导入解耦后的工具箱
from core.functools.tools import Toolbox
from core.rag_store import RAGStore

class HostAgent:
    def __init__(self, session_id="default", config_path="config/config.yaml"):
        self.session_id = session_id
        
        # 路径定义
        self.config_path = config_path
        self.profiles_path = "config/profiles.yaml"
        self.user_profile_path = "config/user_profile.yaml"
        
        # 加载所有配置
        self.load_all_configs()
        
        # 初始化组件
        # 从 Config 读取 window_size，默认为 10
        win_size = self.config.get('system', {}).get('memory', {}).get('window_size', 10)
        self.memory = ConversationMemory(session_id=self.session_id, window_size=win_size)
        
        # 初始化向量数据库 (RAG)
        vec_path = self.config.get('system', {}).get('memory', {}).get('vector_store_path', './logs/vector_store')
        self.rag_store = RAGStore(persistence_path=vec_path)
        
        # 初始化工具箱
        self.toolbox = Toolbox(self)
        
        # 初始化 LLM 客户端
        self._init_client()

    def load_all_configs(self):
        """加载系统配置、模型配置和用户画像"""
        # 1. 加载主配置
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
            
        # 2. 加载模型 Profiles
        if os.path.exists(self.profiles_path):
            with open(self.profiles_path, 'r', encoding='utf-8') as f:
                self.profiles = yaml.safe_load(f).get('profiles', {})
        else:
            self.profiles = {}
            
        # 3. 加载用户画像
        if os.path.exists(self.user_profile_path):
            with open(self.user_profile_path, 'r', encoding='utf-8') as f:
                self.user_data = yaml.safe_load(f)
        else:
            self.user_data = {}

    def _init_client(self):
        """根据 active_profile 初始化 LLM 客户端"""
        active_id = self.config.get('active_profile')
        
        # 容错处理：如果找不到 profile，使用默认或空配置
        if active_id not in self.profiles:
            print(f"[Warning] Profile '{active_id}' not found. Using safe defaults.")
            self.current_model_config = {
                'api_key': self.config.get('agent', {}).get('openai_api_key', 'EMPTY'),
                'base_url': self.config.get('agent', {}).get('openai_base_url', None),
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7
            }
        else:
            self.current_model_config = self.profiles[active_id]
            
        self.client = OpenAI(
            api_key=self.current_model_config['api_key'],
            base_url=self.current_model_config.get('base_url')
        )

    def _build_dynamic_system_prompt(self, relevant_memories: list):
        """
        构建高级结构化 Prompt
        包含：身份、工具能力、用户画像、长期记忆(RAG)、当前对话摘要
        """
        # 1. 基础身份设定
        base_identity = """
Role: Resonance (Advanced AI Host for Windows)
Objective: Assist the user by executing local commands, managing files, and planning complex tasks.
Environment: Windows 11, PowerShell.

Core Principles:
1. **Think Before Acting.** When complex tasks arise, break them down.
2. **Explore then Act.** When asked to find information in files, DO NOT guess. Use 'list_directory_files' or 'search_files_by_keyword' first, then 'read_file_content'.
3. **Multi-Step Tool Use.** You can use multiple tools or use tools multiple times in a sequence to complete a task. Analyze the output of each tool before proceeding.
4. **Robustness.** If a command fails, analyze the error and try a different approach.
5. **Memory.** You have access to long-term memory. Use it to recall user preferences and past projects.
"""
        
        # 2. 用户画像注入
        user_section = "\n[User Profile & Preferences]\n"
        user_info = self.user_data.get('user_info', {})
        known_projects = self.user_data.get('known_projects', {})
        
        for k, v in user_info.items():
            user_section += f"- {k}: {v}\n"
        if known_projects:
            user_section += "- Known Projects/Paths:\n"
            for proj, path in known_projects.items():
                user_section += f"  * {proj}: {path}\n"

        # 3. 长期记忆注入 (RAG Results)
        rag_section = ""
        if relevant_memories:
            rag_section = "\n[Relevant Long-term Memories]\n"
            for mem in relevant_memories:
                rag_section += f"- {mem}\n"
            rag_section += "(Use these memories to answer contextually if applicable)\n"

        # 4. 对话摘要注入 (Summary)
        summary_text = self.memory.load_summary()
        summary_section = ""
        if summary_text:
            summary_section = f"\n[Previous Conversation Summary]\n{summary_text}\n(This is what happened before the current active window)\n"

        # 组合 Prompt
        full_prompt = base_identity + user_section + rag_section + summary_section
        
        return full_prompt

    def _update_summary_if_needed(self):
        """
        [摘要机制] 检查是否需要压缩历史记录
        如果历史记录超过一定长度，调用 LLM 生成摘要
        """
        if not self.config['system'].get('memory', {}).get('enable_summary', True):
            return

        # 策略：每隔 5 轮 (10条消息) 更新一次摘要
        full_log = self.memory.get_full_log()
        if len(full_log) > 0 and len(full_log) % 10 == 0:
            # 只有当有足够多的历史在窗口之外时才总结
            text_to_summarize = self.memory.get_messages_for_summarization()
            if not text_to_summarize:
                return

            current_summary = self.memory.load_summary()
            
            # 使用 LLM 生成摘要
            try:
                prompt = f"""
                You are a memory compressor.
                
                Current Summary:
                {current_summary}
                
                New Conversation Log to Append:
                {text_to_summarize}
                
                Task: Update the summary to include the key information from the new log. Keep it concise.
                Return ONLY the updated summary text.
                """
                
                response = self.client.chat.completions.create(
                    model=self.current_model_config['model'],
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3
                )
                
                new_summary = response.choices[0].message.content
                self.memory.save_summary(new_summary)
                # print(f"[System]: Memory summarized. Length: {len(new_summary)}")
            except Exception as e:
                print(f"[Warning] Failed to generate summary: {e}")

    # =========================================================================
    # [新增核心逻辑] 异步记忆萃取与存储
    # =========================================================================
    def _extract_and_save_memory_async(self, user_input, ai_output):
        """
        后台线程任务：分析对话，萃取有价值的信息存入向量库。
        避免将垃圾对话（"你好", "嗯"）存入。
        """
        try:
            # 1. 启发式过滤 (Heuristic Filter)
            # 如果内容太短，通常不具备长期记忆价值
            if len(user_input) < 5 and len(ai_output) < 10:
                return

            # 2. 调用 LLM 进行信息萃取 (Extraction)
            # 使用更便宜的模型或相同的模型，Prompt 侧重于"事实提取"
            extraction_prompt = f"""
Analyze the following interaction for Long-term Memory storage.
Extract meaningful facts, user preferences, specific project details, or technical solutions.
Ignore casual chitchat (greetings, thanks) or temporary command outputs.

Interaction:
User: {user_input}
AI: {ai_output}

Instructions:
- If the interaction contains useful facts worth remembering for future sessions, extract them into a concise statement.
- If the interaction is trivial or purely operational (e.g. "list files"), output "NO_INFO".
- Do not output "User said...", just the fact.

Output:
"""
            response = self.client.chat.completions.create(
                model=self.current_model_config['model'],
                messages=[{"role": "user", "content": extraction_prompt}],
                temperature=0.1, # 低温度确保准确
                max_tokens=150
            )
            
            extracted_info = response.choices[0].message.content.strip()
            
            # 3. 存储逻辑
            if extracted_info and "NO_INFO" not in extracted_info:
                # 存入向量库
                success = self.rag_store.add_memory(
                    text=extracted_info,
                    metadata={
                        "type": "conversation_insight",
                        "session": self.session_id,
                        "original_user_input": user_input[:50] # 方便追溯
                    }
                )
                if success:
                    # 在日志中静默记录，用于调试，不干扰主线程输出
                    # print(f"[Memory System]: Archived -> {extracted_info[:30]}...")
                    pass

        except Exception as e:
            # 这里的异常绝对不能影响主线程
            print(f"[Memory System Error]: {e}")

    # =========================================================================
    # [核心修改点] 正确实现的 ReAct 交互逻辑 (多工具支持 & 循环推理)
    # =========================================================================
    def chat(self, user_input, ui_callback=None):
        """
        主交互逻辑：遵循 OpenAI 工具调用协议，支持多步思考。
        """
        try:
            # 1. 初始化上下文
            top_k = self.config['system'].get('memory', {}).get('retrieve_top_k', 3)
            relevant_docs = self.rag_store.search_memory(user_input, n_results=top_k)
            
            # 2. 构建动态 System Prompt
            dynamic_sys_prompt = self._build_dynamic_system_prompt(relevant_docs)
            
            # messages 列表将作为我们在这一轮推理中的“工作区”
            messages = [{"role": "system", "content": dynamic_sys_prompt}]
            messages += self.memory.get_active_context() # 获取滑动窗口
            messages.append({"role": "user", "content": user_input})
            
            # 2. 准备工具
            tools = self.toolbox.get_tool_definitions()

            # 3. 记录初始用户消息
            self.memory.add_user_message(user_input)

            # 4. 进入 ReAct 循环
            max_iterations = 8  # 防止模型陷入死循环
            current_iteration = 0
            final_reply = ""

            while current_iteration < max_iterations:
                current_iteration += 1
                
                if ui_callback:
                    ui_callback(f"🧠 Thinking (Step {current_iteration})...")

                # LLM 推理
                response = self.client.chat.completions.create(
                    model=self.current_model_config['model'],
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=self.current_model_config['temperature']
                )

                response_message_obj = response.choices[0].message
                
                # [修改点] 将 OpenAI 的 Message 对象转换为 dict，防止后期属性访问报错
                # model_dump 是 Pydantic v2 (openai v1+) 的标准写法
                response_dict = response_message_obj.model_dump(exclude_none=True)
                
                # 将该消息加入本轮对话工作上下文
                messages.append(response_dict)
                
                # 同步记录到持久化 Memory
                if response_message_obj.tool_calls:
                    self.memory.add_ai_tool_call(response_message_obj.content, response_message_obj.tool_calls)
                else:
                    self.memory.add_ai_message(response_message_obj.content)

                # B. 检查是否有工具调用
                if not response_message_obj.tool_calls:
                    final_reply = response_message_obj.content
                    break
                
                # C. 执行工具调用
                tool_calls = response_message_obj.tool_calls
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except:
                        args = {}
                    
                    # 回调 UI
                    if ui_callback:
                        ui_callback(f"⚙️ Executing {function_name}...")
                    
                    # 调用 Toolbox (逻辑保持不变，但增加一个 update_memory 的特殊处理)
                    tool_result = self._route_tool_execution(function_name, args, ui_callback)
                    
                    # 记录结果
                    self.memory.add_tool_message(tool_result, tool_call.id)
                    
                    # 将工具结果加入当前对话上下文 (role="tool")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": str(tool_result)
                    })

                # 完成本轮所有工具执行，继续 while 循环让模型根据 tool 结果进行下一轮思考

            # 5. 后置处理逻辑
            # [修改点] 使用 .get('role') 访问字典，确保安全
            if not final_reply and len(messages) > 0:
                last_msg = messages[-1]
                if isinstance(last_msg, dict) and last_msg.get('role') == "assistant":
                    final_reply = last_msg.get('content', "")

            self._update_summary_if_needed()
            
            # 8. [修改点] 启动异步线程进行记忆萃取与向量存储
            # 使用守护线程 (daemon=True)，主程序退出时它自动结束，不会卡死进程
            memory_thread = threading.Thread(
                target=self._extract_and_save_memory_async,
                args=(user_input, final_reply),
                daemon=True
            )
            memory_thread.start()

            return final_reply if final_reply else "Task completed (No textual response)."

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return f"Resonance Core Error: {str(e)}"

    def _route_tool_execution(self, function_name, args, ui_callback):
        """路由工具调用到 Toolbox，保持代码整洁"""
        try:
            if function_name == "invoke_skill" or function_name == "run_registered_script":
                alias = args.get("skill_alias") or args.get("script_alias")
                extra = args.get("args", "")
                return self.toolbox.invoke_registered_skill(alias, extra)
                
            elif function_name == "execute_shell_command":
                return self.toolbox.execute_shell(args.get("command"))
                
            elif function_name == "add_automation_skill":
                return self.toolbox.add_new_script(args.get("alias"), args.get("command"), args.get("description"))
                
            elif function_name == "scan_directory_projects":
                res = self.toolbox.scan_and_remember(args.get("path"))
                self.rag_store.add_memory(res, {"type": "fact_project"})
                return res
                
            elif function_name == "read_file_content":
                return self.toolbox.read_file_content(args.get("file_path"))
                
            elif function_name == "remember_user_fact":
                key = args.get("key")
                val = args.get("value")
                res = self.toolbox.remember_user_fact(key, val)
                self.rag_store.add_memory(f"User Fact: {key} is {val}", {"type": "explicit_fact"})
                return res
                
            elif function_name == "list_directory_files":
                return self.toolbox.list_directory_files(
                    directory_path=args.get("directory_path"), 
                    recursive=args.get("recursive", True),
                    depth=args.get("depth", 2)
                )
                
            elif function_name == "search_files_by_keyword":
                return self.toolbox.search_files_by_keyword(
                    directory_path=args.get("directory_path"), 
                    keyword=args.get("keyword")
                )
            
            else:
                return f"Error: Unknown tool '{function_name}'"
        except Exception as e:
            return f"Error executing {function_name}: {str(e)}"

    def clear_memory(self):
        self.memory.clear()
    
    def update_config(self, new_config=None, new_profiles=None, new_active_profile=None):
        """运行时更新配置"""
        if new_config:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(new_config, f, allow_unicode=True, default_flow_style=False)
        
        if new_profiles:
            with open(self.profiles_path, 'w', encoding='utf-8') as f:
                yaml.dump({'profiles': new_profiles}, f, allow_unicode=True, default_flow_style=False)
                
        if new_active_profile:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                current = yaml.safe_load(f)
            current['active_profile'] = new_active_profile
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(current, f, allow_unicode=True, default_flow_style=False)

        self.load_all_configs()
        self._init_client()