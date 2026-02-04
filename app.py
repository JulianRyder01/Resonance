# app.py
import streamlit as st
import time
import pandas as pd
import yaml
import os
import uuid
from core.host_agent import HostAgent
from core.memory import ConversationMemory
from utils.monitor import SystemMonitor
import plotly.express as px
import plotly.graph_objects as go

# --- 页面配置 ---
st.set_page_config(
    page_title="Resonance Console",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS 优化 ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .stMetric { background-color: #262730; border: 1px solid #464b5c; }
    div[data-testid="stChatMessage"] { background-color: #262730; border-radius: 10px; padding: 1rem; }
    /* 调整 Tab 样式 */
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #1e212b; border-radius: 4px; color: #fff; }
    .stTabs [aria-selected="true"] { background-color: #4facfe; color: white; }
    /* 过程日志美化 */
    .thought-container { border-left: 2px solid #4facfe; padding-left: 10px; margin: 5px 0; color: #888; font-style: italic; }
    
    /* [新增] 打断按钮样式 */
    .stButton button { width: 100%; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# --- State ---
if "session_id" not in st.session_state:
    st.session_state.session_id = "default"

# 始终确保 Agent 存在且是最新的
if "agent" not in st.session_state:
    st.session_state.agent = HostAgent(session_id=st.session_state.session_id)

# [新增] 状态管理：是否正在生成
if "is_generating" not in st.session_state:
    st.session_state.is_generating = False

# --- 辅助函数 ---
def switch_session(new_session_id):
    st.session_state.session_id = new_session_id
    # 重新实例化 Agent 以绑定新 Session
    st.session_state.agent = HostAgent(session_id=new_session_id)
    st.rerun()

def create_new_session():
    new_id = f"session_{uuid.uuid4().hex[:8]}"
    switch_session(new_id)

# ================= 侧边栏：状态与导航 =================
with st.sidebar:
    st.title("💠 Resonance")
    st.caption(f"Ver: {st.session_state.agent.config['system']['version']}")
    
    # 导航 [修改点] Scripts & Models -> Skills & Models
    nav = st.radio("Navigation", ["💬 聊天 Chat Console", "⚙️ 系统配置 System Config", "🧩 技能、记忆与模型提供商 Skills & Models", "🧠 记忆可视化 Memory Cortex", "📊 电脑状态监控 Monitor"], label_visibility="collapsed")
    
    st.divider()
    
    # Session 管理
    st.subheader("🗂 Sessions")
    col_n1, col_n2 = st.columns([4, 1])
    with col_n1:
        existing_sessions = ConversationMemory.list_sessions()
        if not existing_sessions: existing_sessions = ["default"]
        
        # 确保当前session在列表里
        if st.session_state.session_id not in existing_sessions:
            existing_sessions.insert(0, st.session_state.session_id)
            
        selected = st.selectbox("Switch Session", existing_sessions, 
                              index=existing_sessions.index(st.session_state.session_id), 
                              label_visibility="collapsed")
        
        if selected != st.session_state.session_id:
            switch_session(selected)
            
    with col_n2:
        if st.button("➕", help="New"): create_new_session()
    
    # 显示当前活跃模型
    active_profile = st.session_state.agent.config.get('active_profile', 'Unknown')
    st.info(f"🤖 Active Model: **{active_profile}**")

# ================= 页面：聊天控制台 =================
if nav == "💬 聊天 Chat Console":
    st.header(f"Chat: {st.session_state.session_id}")
    
    # 聊天记录显示区
    chat_container = st.container()
    
    # 获取完整日志（包含时间戳和工具调用）
    # 注意：这里直接读最新的，保证 CLI 写入后刷新网页能看到
    messages = st.session_state.agent.memory.get_full_log()
    
    with chat_container:
        if not messages:
            st.info("👋 Ready via Web or CLI.")
            
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            
            if role == "tool":
                with st.expander(f"🛠️ Tool Output (ID: {msg.get('tool_call_id', '?')[:6]})"):
                    st.code(content, language="powershell")
            elif role == "user":
                with st.chat_message("user", avatar="👤"):
                    st.write(content)
            elif role == "assistant":
                with st.chat_message("assistant", avatar="💠"):
                    if msg.get("content"):
                        st.markdown(msg["content"])
                    if msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            st.caption(f"🔧 Called: {tc['function']['name']}")
            elif role == "tool":
                with st.expander(f"🛠️ Tool Result: {msg.get('name', 'Output')}"):
                    st.code(msg["content"], language="powershell")
                    st.markdown(content)

    # [新增] 输入/打断区域逻辑
    # 如果正在生成，显示 Stop 按钮，否则显示 Input 框
    
    # 容器用于放置输入控件
    input_container = st.container()
    
    with input_container:
        # [修改点] 打断按钮逻辑
        # 注意：Streamlit 是单线程运行。当 Python 在执行循环时，UI 是冻结的，除非使用特定的异步或 fragment 技术。
        # 但标准的 st.button 点击会触发 Rerun。
        # 我们利用这个 Rerun 机制：当 Agent 运行时，如果用户设法点击了（或按了停止），
        # 下一次运行时我们会捕捉到 session_state 的变化或者直接中断。
        # 为了更好的体验，我们在此处放置一个始终可见的 Stop 按钮（仅在处理时有效）。
        
        user_input = st.chat_input("Command or Question...", disabled=st.session_state.is_generating)
        
        # 处理逻辑
        if user_input:
            st.session_state.is_generating = True
            
            # 1. 立即显示用户输入
            with chat_container:
                with st.chat_message("user", avatar="👤"):
                    st.write(user_input)
            
            # 2. 机器人响应容器
            with chat_container:
                with st.chat_message("assistant", avatar="💠"):
                    status_container = st.status("Initializing...", expanded=True)
                    response_placeholder = st.empty()
                    
                    # [新增] 在生成过程中渲染一个停止按钮
                    # 注意：Streamlit 脚本一旦进入循环，这里的按钮点击响应会延迟到循环结束或 yield 间隙。
                    # 为了实现真正的“即时打断”，我们在 sidebar 放置一个中断按钮，或者在 Agent 内部 check 状态。
                    # 这里我们模拟：生成开始前设置状态。
                    
                    full_response = ""
                    
                    # 遍历生成器
                    try:
                        for event in st.session_state.agent.chat(user_input):
                            # [修改点] 每次循环都检查外部中断（虽然 Web UI 很难直接注入，但如果未来加了 socket 就可以）
                            # 也可以在此处加入 st.button 但这会导致 duplicate id 报错，需要 careful design.
                            
                            etype = event["type"]
                            content = event.get("content", "")

                            if etype == "status":
                                status_container.update(label=content)
                            
                            elif etype == "delta":
                                full_response += content
                                response_placeholder.markdown(full_response + "▌")
                            
                            elif etype == "tool":
                                with status_container:
                                    st.write(f"✅ **Tool [{event['name']}] output:**")
                                    st.code(content, language="powershell")
                            
                            elif etype == "error":
                                st.error(f"Error: {content}")
                    except Exception as e:
                        st.error(f"Runtime Error: {e}")
                    finally:
                        st.session_state.is_generating = False
                        # 最终渲染
                        response_placeholder.markdown(full_response)
                        status_container.update(label="Task Completed", state="complete", expanded=False)
                        st.rerun() # 刷新状态以重新启用输入框

# ================= 页面：配置管理 (0代码) =================
elif nav == "⚙️ 系统配置 System Config":
    st.header("⚙️ General Settings")
    
    current_conf = st.session_state.agent.config
    current_user = st.session_state.agent.user_data
    
    tab1, tab2 = st.tabs(["System Preferences", "User Profile"])
    
    with tab1:
        with st.form("sys_conf"):
            st.subheader("System")
            # 这里只展示一部分核心配置，避免改坏路径
            log_dir = st.text_input("Log Directory", value=current_conf['system'].get('log_dir', './logs'))
            
            submitted = st.form_submit_button("Save System Config")
            if submitted:
                current_conf['system']['log_dir'] = log_dir
                st.session_state.agent.update_config(new_config=current_conf)
                st.toast("Saved!", icon="✅")

    with tab2:
        st.caption("These preferences are injected into the Agent's brain.")
        # 使用 JSON 编辑器来编辑用户画像，比纯文本更安全一点
        updated_user_data = st.data_editor(current_user, num_rows="dynamic", height=400)
        
        if st.button("💾 Save User Profile"):
            # 保存到 user_profile.yaml
            with open("config/user_profile.yaml", 'w', encoding='utf-8') as f:
                yaml.dump(updated_user_data, f, allow_unicode=True)
            st.session_state.agent.load_all_configs() # 刷新
            st.toast("User Profile Updated!", icon="🧠")

# ================= 页面：模型与技能 (0代码核心) =================
elif nav == "🧩 技能、记忆与模型提供商 Skills & Models":
    st.header("🧩 Extensions Manager")
    
    tab_m, tab_s = st.tabs(["🤖 LLM Profiles", "⚡ Skills Library"])
    
    # --- 模型管理 ---
    with tab_m:
        st.subheader("Model Profiles")
        
        profiles = st.session_state.agent.profiles
        active_p = st.session_state.agent.config.get('active_profile')
        
        # 1. 切换主模型
        col1, col2 = st.columns([3, 1])
        with col1:
            new_active = st.selectbox("Select Active Profile", list(profiles.keys()), index=list(profiles.keys()).index(active_p) if active_p in profiles else 0)
        with col2:
            if st.button("⚡ Activate"):
                st.session_state.agent.update_config(new_active_profile=new_active)
                st.toast(f"Switched to {new_active}", icon="🔁")
                st.rerun()

        st.divider()
        
        # 2. 编辑/添加模型
        st.caption("Edit existing profiles or add new ones (Type in the key name to add).")
        
        # 将字典转换为 DataFrame 方便编辑，或者直接用 JSON 编辑器
        # 为了更直观，我们用 Expander 列表
        
        with st.expander("➕ Add New Profile"):
            with st.form("add_model"):
                new_id = st.text_input("Profile ID (e.g. gpt4_backup)")
                p_name = st.text_input("Display Name", "My New Model")
                p_model = st.text_input("Model Name", "gpt-4")
                p_key = st.text_input("API Key", type="password")
                p_base = st.text_input("Base URL (Optional)")
                
                if st.form_submit_button("Add Profile"):
                    if new_id and p_key:
                        profiles[new_id] = {
                            "name": p_name, "provider": "openai", "model": p_model,
                            "api_key": p_key, "base_url": p_base if p_base else None, "temperature": 0.7
                        }
                        st.session_state.agent.update_config(new_profiles=profiles)
                        st.toast(f"Profile {new_id} added!", icon="✅")
                        st.rerun()
        
        for pid, pdata in profiles.items():
            with st.expander(f"📝 {pdata.get('name', pid)} ({pid})"):
                c1, c2 = st.columns(2)
                pdata['model'] = c1.text_input("Model", pdata['model'], key=f"m_{pid}")
                pdata['base_url'] = c2.text_input("Base URL", pdata.get('base_url', ''), key=f"b_{pid}")
                # Key 就不回显了，为了安全，或者显式覆盖
                new_key_input = st.text_input("Update API Key (Leave empty to keep)", type="password", key=f"k_{pid}")
                if new_key_input:
                    pdata['api_key'] = new_key_input
                
                if st.button("Update This Profile", key=f"btn_{pid}"):
                    profiles[pid] = pdata
                    st.session_state.agent.update_config(new_profiles=profiles)
                    st.toast("Updated!", icon="✅")

    # --- 技能/脚本管理 ---
    with tab_s:
        st.subheader("Registered Skills")
        st.info("Agent uses these 'Skills' to perform complex tasks. You can now pass arguments to them.")
        
        current_scripts = st.session_state.agent.config.get('scripts', {})
        
        # 使用 Data Editor 比较直观
        # 将 Dict 转为 List of Dicts
        script_list = []
        for k, v in current_scripts.items():
            script_list.append({
                "Alias": k,
                "Description": v.get("description", ""),
                "Command": v.get("command", ""),
                "CWD": v.get("cwd", ""),
                "Timeout": v.get("timeout", 120),  # 新增
                "Delay": v.get("delay", 0)         # 新增
            })
            
        # [修改点] 配置 st.data_editor 的列属性，确保数字输入
        edited_df = st.data_editor(
            script_list, 
            num_rows="dynamic", 
            use_container_width=True,
            column_config={
                "Timeout": st.column_config.NumberColumn("Timeout (s)", min_value=1, max_value=3600, step=1, help="Default 120s"),
                "Delay": st.column_config.NumberColumn("Delay (s)", min_value=0, max_value=600, step=1, help="Default 0s (Immediate)"),
                "Alias": st.column_config.TextColumn("Skill Alias", help="Unique ID for calling this skill"),
                "Command": st.column_config.TextColumn("Command", help="Base command (args will be appended)")
            }
        )
        
        if st.button("💾 Save Skills Configuration"):
            # 将 List 转回 Dict
            new_scripts = {}
            for item in edited_df:
                alias = item.get("Alias")
                if alias:
                    # [修改点] 写入新字段
                    new_scripts[alias] = {
                        "description": item.get("Description", ""),
                        "command": item.get("Command", ""),
                        "cwd": item.get("CWD") if item.get("CWD") else None,
                        "timeout": int(item.get("Timeout", 120)),
                        "delay": int(item.get("Delay", 0))
                    }
            
            # 更新 Config
            full_conf = st.session_state.agent.config
            full_conf['scripts'] = new_scripts
            st.session_state.agent.update_config(new_config=full_conf)
            st.toast("Skills updated! Agent can now use them.", icon="✅")
# ================= 页面：记忆皮层 (Memory Cortex) =================
elif nav == "🧠 记忆可视化 Memory Cortex":
    st.header("🧠 Memory Cortex (RAG Visualization)")
    
    # 1. 获取数据
    df = st.session_state.agent.rag_store.get_all_memories_as_df()
    
    if df.empty:
        st.warning("No memories found in the Vector Database yet. Start chatting to build memories!")
    else:
        # --- 顶部 KPI ---
        total_mem = len(df)
        total_access = df['access_count'].sum() if 'access_count' in df.columns else 0
        most_active_type = df.groupby('type')['access_count'].sum().idxmax() if not df.empty else "None"
        last_activity = df['last_accessed'].max().strftime('%Y-%m-%d %H:%M') if 'last_accessed' in df.columns else "N/A"

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Memories", total_mem, help="Number of vectors stored")
        k2.metric("Total Retrievals", int(total_access), help="How many times memories were successfully recalled")
        k3.metric("Dominant Context", most_active_type, help="Most accessed memory category")
        k4.metric("Last Activity", last_activity)
        
        st.divider()
        
        # --- 图表区 ---
        col_charts_1, col_charts_2 = st.columns([1, 1])
        
        with col_charts_1:
            st.subheader("Memory Composition")
            # 旭日图：展示记忆类型分布，大小由“被访问次数”或“数量”决定
            if 'type' in df.columns:
                # 填充空类型
                df['type'] = df['type'].fillna('unknown')
                fig_sun = px.sunburst(
                    df, 
                    path=['type', 'content'], # 层级：先看类型，再看具体内容(截断)
                    values='access_count' if total_access > 0 else None,
                    title="Memory Activation Map (Size = Retrieval Count)",
                    color='type',
                    height=400
                )
                # 只显示 content 的前20个字，避免图表太乱
                fig_sun.update_traces(textinfo="label+percent entry")
                st.plotly_chart(fig_sun, use_container_width=True)

        with col_charts_2:
            st.subheader("Memory Timeline & Value")
            # 散点图：X轴=创建时间，Y轴=访问次数，颜色=类型，大小=访问次数
            if 'timestamp' in df.columns and 'access_count' in df.columns:
                fig_scat = px.scatter(
                    df,
                    x='timestamp',
                    y='access_count',
                    color='type',
                    size='access_count',
                    hover_data=['content'],
                    title="Memory Evolution (Time vs. Utility)",
                    height=400
                )
                st.plotly_chart(fig_scat, use_container_width=True)
        
        st.divider()

        # --- RAG 实验室 (Debugger) ---
        st.subheader("🧪 RAG Laboratory")
        st.info("Test your retrieval effectiveness here. See what the Agent 'remembers' for a given query.")
        
        test_query = st.text_input("Enter a test query (e.g., 'Who am I?', 'project path')", "")
        
        if test_query:
            # 直接调用 Chroma 底层查询以获取距离
            col_res1, col_res2 = st.columns([1, 1])
            with col_res1:
                st.markdown("#### 🔍 Retrieval Results")
                # 我们手动调底层 collection query 来拿 distance，因为 rag_store.search_memory 封装掉了
                collection = st.session_state.agent.rag_store.collection
                if collection:
                    results = collection.query(
                        query_texts=[test_query],
                        n_results=5,
                        include=['documents', 'metadatas', 'distances']
                    )
                    
                    if results['ids']:
                        for i in range(len(results['ids'][0])):
                            doc = results['documents'][0][i]
                            meta = results['metadatas'][0][i]
                            dist = results['distances'][0][i]
                            
                            # 卡片展示
                            with st.container():
                                st.markdown(f"""
                                **Memory #{i+1}** (Distance: `{dist:.4f}`)  
                                📂 Type: `{meta.get('type', 'N/A')}` | 🔥 Retrieves: `{meta.get('access_count', 0)}`
                                """)
                                st.code(doc, language="text")
                                st.divider()
                    else:
                        st.caption("No matches found.")
            
            with col_res2:
                st.markdown("#### 📊 Metric Analysis")
                st.caption("""
                - **Distance**: 越小越好 (Cosine Distance). 通常 < 1.0 表示相关.
                - **Retrieves**: 该记忆被系统自动调用的次数. 次数高说明它是核心记忆.
                """)
                # 这里可以加个 Gauge 图或者简单的分析建议
        
        st.divider()

        # --- 数据矩阵 ---
        st.subheader("💾 The Vault (Raw Data)")
        st.dataframe(
            df[['type', 'content', 'access_count', 'timestamp', 'last_accessed', 'id']], 
            use_container_width=True,
            column_config={
                "content": st.column_config.TextColumn("Content", width="large"),
                "access_count": st.column_config.ProgressColumn("Usage", format="%d", min_value=0, max_value=int(df['access_count'].max()) if not df.empty else 100),
                "timestamp": st.column_config.DatetimeColumn("Created", format="D MMM YYYY, HH:mm"),
            }
        )
# ================= 页面：监控 =================
elif nav == "📊 电脑状态监控 Monitor":
    st.header("🖥️ System Monitor")
    metrics = SystemMonitor.get_system_metrics()
    
    c1, c2, c3 = st.columns(3)
    c1.metric("CPU Usage", f"{metrics['cpu_percent']}%")
    c2.metric("Memory Usage", f"{metrics['memory_percent']}%", f"{metrics['memory_used_gb']} GB")
    c3.metric("Battery", f"{metrics['battery_percent']}%", "Plugged" if metrics['power_plugged'] else "On Battery")
    
    st.subheader("Top Processes")
    st.dataframe(SystemMonitor.get_process_list(15), use_container_width=True)