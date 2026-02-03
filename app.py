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
</style>
""", unsafe_allow_html=True)

# --- State ---
if "session_id" not in st.session_state:
    st.session_state.session_id = "default"

# 始终确保 Agent 存在且是最新的
if "agent" not in st.session_state:
    st.session_state.agent = HostAgent(session_id=st.session_state.session_id)

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
    nav = st.radio("Navigation", ["💬 Chat Console", "⚙️ System Config", "🧩 Skills & Models", "📊 Monitor"], label_visibility="collapsed")
    
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
if nav == "💬 Chat Console":
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
                    st.markdown(content)

    # 输入框
    if prompt := st.chat_input("Command or Question..."):
        # UI 立即反馈
        with chat_container:
            with st.chat_message("user", avatar="👤"):
                st.write(prompt)
        
        with chat_container:
            with st.chat_message("assistant", avatar="💠"):
                status = st.empty()
                status.markdown("Thinking...")
                
                def ui_callback(txt):
                    status.info(txt)
                
                # 调用 Agent
                response = st.session_state.agent.chat(prompt, ui_callback=ui_callback)
                
                status.empty()
                st.markdown(response)
        
        # 刷新以确保工具调用的 log 也能正确渲染出来
        # st.rerun() 

# ================= 页面：配置管理 (0代码) =================
elif nav == "⚙️ System Config":
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
# [修改点] 名称更新
elif nav == "🧩 Skills & Models":
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

# ================= 页面：监控 =================
elif nav == "📊 Monitor":
    st.header("🖥️ System Monitor")
    metrics = SystemMonitor.get_system_metrics()
    
    c1, c2, c3 = st.columns(3)
    c1.metric("CPU Usage", f"{metrics['cpu_percent']}%")
    c2.metric("Memory Usage", f"{metrics['memory_percent']}%", f"{metrics['memory_used_gb']} GB")
    c3.metric("Battery", f"{metrics['battery_percent']}%", "Plugged" if metrics['power_plugged'] else "On Battery")
    
    st.subheader("Top Processes")
    st.dataframe(SystemMonitor.get_process_list(15), use_container_width=True)