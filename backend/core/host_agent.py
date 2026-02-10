# core/host_agent.py
import yaml
import json
import os
import time
import threading
from openai import OpenAI, APIConnectionError, APITimeoutError
from core.memory import ConversationMemory
# [修改点] 导入解耦后的工具箱
from core.functools.tools import Toolbox
from core.rag_store import RAGStore
# [修改点] 导入 SentinelEngine
from core.sentinel_engine import SentinelEngine

class HostAgent:
    def __init__(self, default_session="resonance_main", config_path="config/config.yaml"):
        # [修改点] 默认会话ID
        self.default_session_id = default_session
        self.active_session_id = default_session # 仅用于 backward compatibility
        
        # [新增] 会话级中断事件字典 {session_id: threading.Event}
        self.interrupt_events = {}
        
        # --- [关键修改开始] 路径锚定修复 ---
        # 获取当前 host_agent.py 的绝对路径: .../backend/core/host_agent.py
        current_file_path = os.path.abspath(__file__)
        # 获取 backend 目录: .../backend
        backend_root = os.path.dirname(os.path.dirname(current_file_path))
        
        # 强制将 config 路径锚定到 backend 目录
        self.config_path = os.path.join(backend_root, config_path)
        self.profiles_path = os.path.join(backend_root, "config/profiles.yaml")
        self.user_profile_path = os.path.join(backend_root, "config/user_profile.yaml")
        
        # 加载所有配置
        self.load_all_configs()

        # [关键修改] 强制计算 Vector Store 的绝对路径
        # 无论 config 写的是什么相对路径，我们都将其解析为基于 backend 的绝对路径
        raw_vec_path = self.config.get('system', {}).get('memory', {}).get('vector_store_path', './logs/vector_store')
        if not os.path.isabs(raw_vec_path):
            # 如果是相对路径，拼接到 backend_root 下
            vec_path = os.path.normpath(os.path.join(backend_root, raw_vec_path))
        else:
            vec_path = raw_vec_path

        print(f"[System]: Memory Database Path Anchored to: {vec_path}") # 打印出来确认

        self.stop_flag = False
        self.memory_cache = {}
        
        # 初始化向量数据库 (RAG)
        self.rag_store = RAGStore(persistence_path=vec_path)

        # [修复 Bug ①] 初始化 SentinelEngine，使其成为 HostAgent 的属性
        # 这里的路径也应该锚定到 backend
        sentinel_config_path = os.path.join(backend_root, "config/sentinels.json")
        self.sentinel_engine = SentinelEngine(config_path=sentinel_config_path)

        # 初始化工具箱 (传入 self 以便工具箱访问 stop_flag 和 config)
        self.toolbox = Toolbox(self)
        
        # 初始化 LLM Client
        self.client = None
        self._init_client()


    def get_memory(self, session_id=None) -> ConversationMemory:
        """[新增] 获取指定会话的内存对象，如果不存在则创建并缓存"""
        sid = session_id or self.active_session_id
        if sid not in self.memory_cache:
            win_size = self.config.get('system', {}).get('memory', {}).get('window_size', 10)
            self.memory_cache[sid] = ConversationMemory(session_id=sid, window_size=win_size)
        return self.memory_cache[sid]

    # [新增] 为了兼容旧代码引用 self.memory 的地方，使用 property 代理当前活动会话
    # 注意：在多线程环境中请尽量使用 get_memory(session_id) 明确指定
    @property
    def memory(self):
        return self.get_memory(self.active_session_id)

    def load_all_configs(self):
        """加载系统配置、模型配置和用户画像"""
        # 1. 加载主配置
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
        else:
            print(f"[Critical Warning] Config not found at {self.config_path}")
            self.config = {}
            
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
            print(f"[Warning] Profile '{active_id}' not found in profiles.yaml. Using safe defaults.")
            self.current_model_config = {
                'api_key': 'EMPTY',
                'base_url': None,
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7
            }
        else:
            self.current_model_config = self.profiles[active_id]
        
        self.base_url = self.current_model_config.get('base_url')
        self.api_key = self.current_model_config.get('api_key')

        # 初始化 OpenAI 客户端
        try:
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=60.0,  # 设置超时防止无限等待
                max_retries=2
            )
            print(f"[LLM Init]: Client configured. URL: {self.base_url}, Model: {self.current_model_config.get('model')}")
        except Exception as e:
            print(f"[LLM Error]: Failed to initialize OpenAI client: {e}")
            # 即使失败，也定义为 None，防止 AttributeError，并在 chat 中处理
            self.client = None


    def _build_dynamic_system_prompt(self, relevant_memories: list, memory_instance: ConversationMemory):
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
6. **Autonomy (Sentinels).** You have a 'Sentinel System'. You can set triggers of Time, File, Behavior to wake yourself up later. Use this to be proactive.
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

        # [修改点] 使用传入的 memory_instance
        summary_text = memory_instance.load_summary()
        summary_section = ""
        if summary_text:
            summary_section = f"\n[Previous Conversation Summary]\n{summary_text}\n(This is what happened before the current active window)\n"

        # 组合 Prompt
        full_prompt = base_identity + user_section + rag_section + summary_section
        
        return full_prompt

    def _update_summary_if_needed(self, memory_instance: ConversationMemory):
        """[摘要机制] 检查是否需要压缩历史记录"""
        if not self.config['system'].get('memory', {}).get('enable_summary', True):
            return

        full_log = memory_instance.get_full_log()
        if len(full_log) > 0 and len(full_log) % 10 == 0:
            text_to_summarize = memory_instance.get_messages_for_summarization()
            if not text_to_summarize:
                return

            current_summary = memory_instance.load_summary()
            
            # 使用 LLM 生成摘要
            try:
                # [BUG FIX Check] Ensure client exists before summarizing
                if not self.client:
                    return

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
                print(f"[System]: Memory summarized. Length: {len(new_summary)}")
                print(f"[System]: Memory preview: {new_summary}")
            except Exception as e:
                print(f"[Warning] Failed to generate summary: {e}")

    # =========================================================================
    # [新增核心逻辑] 异步记忆萃取与存储
    # =========================================================================
    def _extract_and_save_memory_async(self, turn_events_log, session_id):
        """
        后台线程任务：分析对话，萃取有价值的信息存入向量库。
        避免将垃圾对话（"你好", "嗯"）存入。
        """
        try:
            # [BUG FIX Check]
            if not self.client:
                return

            # 调用 LLM 进行信息萃取 (Extraction)
            # 使用更便宜的模型或相同的模型，Prompt 侧重于"事实提取"
            extraction_prompt = f"""
You are a Memory Extractor. Analyze the following interaction Turn (User input, AI thoughts, and Tool outputs).
Your goal is to extract NEW, PERMANENT facts about the user, their projects, or technical solutions found.

[Interaction Turn Log]:
{turn_events_log}

[Instructions]:
1. Focus on: Project paths, User preferences, recurring technical issues/solutions, specific facts.
2. Ignore: Transient states (e.g., current CPU usage), casual greetings, or "OK" messages.
3. If no permanent fact is found, output "NO_INFO".
4. If facts are found, output them as concise, independent statements.
5. Example Output: "The user's project 'Resonance' is located at D:\\Develop\\Resonance."

[Output]:
"""
            response = self.client.chat.completions.create(
                model=self.current_model_config['model'],
                messages=[{"role": "user", "content": extraction_prompt}],
                temperature=0.1,
                max_tokens=256
            )
            
            extracted_info = response.choices[0].message.content.strip()
            
            # 3. 存储逻辑
            if extracted_info and "NO_INFO" not in extracted_info:
                # 存入向量库
                success = self.rag_store.add_memory(
                    text=extracted_info,
                    metadata={
                        "type": "conversation_insight",
                        "session": session_id,
                        "original_user_input": turn_events_log[:50]
                    }
                )
                if success:
                    # 在日志中静默记录，用于调试，不干扰主线程输出
                    print(f"[Memory System]: Memory Extracted. Archived -> {extracted_info}")
                    pass

        except Exception as e:
            # 这里的异常绝对不能影响主线程
            print(f"[Memory System Error]: {e}")

    # [新增] 外部调用中断方法 (支持会话级中断)
    def interrupt(self, session_id=None):
        """触发中断信号"""
        if session_id:
            # 中断特定会话
            if session_id in self.interrupt_events:
                print(f"[System]: Interrupting session '{session_id}'")
                self.interrupt_events[session_id].set()
        else:
            # 中断所有 (保留旧行为)
            print("[System]: Interrupting ALL sessions.")
            for evt in self.interrupt_events.values():
                evt.set()

    def handle_sentinel_trigger(self, message):
        """
        当哨兵触发时调用。
        将消息作为 'system' 或 'tool' 结果写入 'resonance_main' 会话。
        """
        try:
            main_mem = self.get_memory("resonance_main")
            # 加上时间戳
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            formatted_msg = f"[Sentinel Alert {timestamp}]: {message}"
            main_mem.add_system_message(formatted_msg)
            print(f"[Core] Injected sentinel alert into 'resonance_main' session.")
        except Exception as e:
            print(f"[Core Error] Failed to inject sentinel memory: {e}")

    def chat(self, user_input, session_id="default"):
        """
        主交互逻辑 (Generator) - 线程安全版本
        Yields: dict -> {"type": "status"|"delta"|"tool", "content": ...}
        """
        # [并发安全] 初始化该会话的中断事件
        if session_id not in self.interrupt_events:
            self.interrupt_events[session_id] = threading.Event()
        stop_event = self.interrupt_events[session_id]
        stop_event.clear() # 重置状态

        # [并发安全] 获取会话专属内存
        session_memory = self.get_memory(session_id)
        
        # -------------------------------------------------------------
        # 检查 Client 是否已初始化
        # -------------------------------------------------------------
        if self.client is None:
            yield {"type": "error", "content": "LLM Client is not initialized. Check profiles.yaml."}
            return

        try:
            # 记录初始用户消息
            session_memory.add_user_message(user_input)
            
            # 2. 检索长期记忆
            top_k = self.config.get('system', {}).get('memory', {}).get('retrieve_top_k', 3)
            # [修改] 读取配置的策略，默认为 semantic
            rag_strategy = self.config.get('system', {}).get('memory', {}).get('rag_strategy', 'semantic')
            
            relevant_docs = self.rag_store.search_memory(
                user_input, 
                n_results=top_k, 
                strategy=rag_strategy  # <--- 传入参数
            )
            
            # 构建动态 System Prompt
            dynamic_sys_prompt = self._build_dynamic_system_prompt(relevant_docs, session_memory)
            
            # messages 列表将作为我们在这一轮推理中的“工作区”
            messages = [{"role": "system", "content": dynamic_sys_prompt}]
            messages += session_memory.get_active_context() 
            messages.append({"role": "user", "content": user_input})
            
            # 2. 准备工具
            tools = self.toolbox.get_tool_definitions()

            
            # 4. 进入 ReAct 循环
            # 用于萃取的全量日志记录（本轮对话）
            turn_log_for_extraction = f"User Input: {user_input}\n"
            max_iterations = 24  # 防止模型陷入死循环
            current_iteration = 0

            while current_iteration < max_iterations:
                # [修改点] 循环开始前检查打断
                if stop_event.is_set():
                    yield {"type": "status", "content": "⛔ Task Interrupted by User."}
                    break

                current_iteration += 1

                # [关键修改]：每一轮推理都重新从 memory 获取经清洗后的上下文
                # 不要相信上一个循环里的 messages 列表，因为它可能在打断后受损
                messages = [{"role": "system", "content": dynamic_sys_prompt}]
                messages += session_memory.get_active_context() 

                yield {"type": "status", "content": f"Thinking (Step {current_iteration})..."}

                # 调用 OpenAI Stream
                # 注意：如果此处 OpenAI 响应非常慢，依然会有 IO 阻塞，但 Python 线程可以响应 event
                try:
                    response = self.client.chat.completions.create(
                        model=self.current_model_config['model'],
                        messages=messages,
                        tools=self.toolbox.get_tool_definitions(),
                        tool_choice="auto",
                        temperature=self.current_model_config['temperature'],
                        stream=True
                    )
                except Exception as e:
                    yield {"type": "error", "content": f"LLM API Error: {str(e)}"}
                    break

                full_response_content = ""
                tool_calls_buffer = {} # 用于收集流式的 tool_calls

                # [修改点] 鲁棒性：Stream处理循环
                try:
                    for chunk in response:
                        # [修改点] 实时流检查打断
                        if stop_event.is_set():
                            response.close() # 显式切断 API 连接
                            yield {"type": "status", "content": "\n[Stopped]"}
                            break 

                        delta = chunk.choices[0].delta
                        
                        # [重要修复] 严格检查 content 且仅在有内容时 yield
                        if hasattr(delta, 'content') and delta.content is not None:
                            content_chunk = delta.content
                            full_response_content += content_chunk
                            yield {"type": "delta", "content": content_chunk}
                        
                        if delta.tool_calls:
                            for tc_chunk in delta.tool_calls:
                                idx = tc_chunk.index
                                if idx not in tool_calls_buffer:
                                    tool_calls_buffer[idx] = {
                                        "id": tc_chunk.id,
                                        "name": tc_chunk.function.name,
                                        "arguments": ""
                                    }
                                if tc_chunk.function.arguments:
                                    tool_calls_buffer[idx]["arguments"] += tc_chunk.function.arguments
                except Exception as e:
                    yield {"type": "error", "content": f"Stream context error: {str(e)}"}
                    break
                
                # 如果是被打断跳出 for loop 的，这里 full_response_content 可能只有一半
                # 我们依然记录它，避免下一次对话上下文丢失
                
                if full_response_content:
                    turn_log_for_extraction += f"AI Thought: {full_response_content}\n"

                # [关键修改] 如果已经打断，直接退出外层循环
                if stop_event.is_set():
                    break

                # 处理 Tool Calls
                active_tool_calls = []
                for _, tc_data in tool_calls_buffer.items():
                    # 模拟 OpenAI 的对象结构供逻辑复用
                    class Func:
                        def __init__(self, n, a): self.name, self.arguments = n, a
                    class TC:
                        def __init__(self, i, f): self.id, self.function = i, f
                    active_tool_calls.append(TC(tc_data["id"], Func(tc_data["name"], tc_data["arguments"])))

                # 记录到内存 (模拟原有非流式逻辑的保存)
                if active_tool_calls:
                    session_memory.add_ai_tool_call(full_response_content, active_tool_calls)
                    messages.append({
                        "role": "assistant",
                        "content": full_response_content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                            } for tc in active_tool_calls
                        ]
                    })
                else:
                    session_memory.add_ai_message(full_response_content)
                    messages.append({"role": "assistant", "content": full_response_content})

                # [修改点] 如果已经打断，且没有工具调用，直接退出外层循环
                if stop_event.is_set():
                    break

                # C. 执行工具
                if not active_tool_calls:
                    break
                
                for tc in active_tool_calls:
                    # [修改点] 工具执行前检查打断 - 立即停止即将发生的操作
                    if stop_event.is_set():
                        yield {"type": "status", "content": "⛔ Interrupted before tool execution."}
                        break

                    # [修复点] 获取工具函数名，防止下文 func_name 未定义引用
                    func_name = tc.function.name 
                    
                    try:
                        args = json.loads(tc.function.arguments)
                    except:
                        args = {}
                    
                    yield {"type": "status", "content": f"Executing tool: {func_name}..."}
                    
                    # [关键修改] 将 stop_event 传递给工具路由，支持工具内部中断
                    tool_result = self._route_tool_execution(func_name, args, stop_event)
                    
                    # 关键可视化：发送工具结果
                    yield {"type": "tool", "name": func_name, "content": tool_result}
                    
                    # 持久化记录
                    # 将工具结果也存入萃取日志
                    turn_log_for_extraction += f"Tool Output ({func_name}): {str(tool_result)[:1000]}\n" # 截断过长的输出以节省Token
                    
                    session_memory.add_tool_message(tool_result, tc.id)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": func_name,
                        "content": str(tool_result)
                    })

            self._update_summary_if_needed(session_memory)
            
            # 8. [修改点] 启动异步线程进行记忆萃取与向量存储
            # 使用守护线程 (daemon=True)，主程序退出时它自动结束，不会卡死进程
            memory_thread = threading.Thread(
                target=self._extract_and_save_memory_async,
                args=(turn_log_for_extraction, session_id), # 传递 session_id
                daemon=True
            )
            memory_thread.start()


        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(error_details) # 在控制台打印详细堆栈
            yield {"type": "error", "content": str(error_details)}
        finally:
            # 清理事件引用（可选，防止内存泄漏）
            if session_id in self.interrupt_events:
                # 任务结束后并不一定要删除 Event，可以留着复用，只要每次 chat start 时 clear 即可
                pass

    def _route_tool_execution(self, function_name, args, stop_event=None):
        """
        路由工具调用到 Toolbox
        [新增] stop_event 参数，传递给支持中断的工具
        """
        try:
            # 检查是否有高优先级的打断
            if stop_event and stop_event.is_set():
                return "[System]: Tool execution cancelled by user."

            if function_name in ["invoke_skill", "run_registered_script"]:
                alias = args.get("skill_alias") or args.get("script_alias")
                extra = args.get("args", "")
                # 传递 stop_event
                return self.toolbox.invoke_registered_skill(alias, extra, stop_event)
                
            elif function_name == "execute_shell_command":
                return self.toolbox.execute_shell(args.get("command"), stop_event=stop_event)
                
            elif function_name == "add_automation_skill":
                return self.toolbox.add_new_script(args.get("alias"), args.get("command"), args.get("description"))
                
            elif function_name == "scan_directory_projects":
                # 这里只负责返回扫描结果字符串
                return self.toolbox.scan_and_remember(args.get("path"))
                
            elif function_name == "read_file_content":
                return self.toolbox.read_file_content(args.get("file_path"))
                
            elif function_name == "remember_user_fact":
                # 只负责更新 UserProfile 文件
                return self.toolbox.remember_user_fact(args.get("key"), args.get("value"))
                
            elif function_name == "list_directory_files":
                return self.toolbox.list_directory_files(
                    directory_path=args.get("directory_path"), 
                    recursive=args.get("recursive", True),
                    depth=args.get("depth", 2)
                )
                
            elif function_name == "search_files_by_keyword":
                # 搜索也可能耗时，传递 stop_event
                return self.toolbox.search_files_by_keyword(
                    directory_path=args.get("directory_path"), 
                    keyword=args.get("keyword"),
                    stop_event=stop_event
                )
            
            # [修改点] 增加联网工具路由
            elif function_name == "internet_search":
                return self.toolbox.run_internet_search(args.get("query"))
            
            elif function_name == "browse_website":
                return self.toolbox.run_browse_website(args.get("url"))

            # [新增] 哨兵系统工具路由
            elif function_name == "add_time_sentinel":
                return self.toolbox.add_time_sentinel(
                    interval=args.get("interval"),
                    unit=args.get("unit"),
                    description=args.get("description")
                )
            elif function_name == "add_file_sentinel":
                return self.toolbox.add_file_sentinel(
                    path=args.get("path"),
                    description=args.get("description")
                )
            elif function_name == "add_behavior_sentinel":
                return self.toolbox.add_behavior_sentinel(
                    key_combo=args.get("key_combo"),
                    description=args.get("description")
                )
            elif function_name == "list_active_sentinels":
                return self.toolbox.list_sentinels()
            elif function_name == "remove_sentinel":
                return self.toolbox.remove_sentinel(args.get("type"), args.get("id"))

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