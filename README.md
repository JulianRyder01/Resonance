# 💠 Resonance AI Host

### Leverage the power of Large Language Models (LLMs) with your local machine's capabilities.

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![Streamlit](https://img.shields.io/badge/Framework-Streamlit-red?logo=streamlit)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Active-success)

[English](#english) | [中文](#chinese)

---

<a name="english"></a>
## 🌍 English Introduction

**Resonance** is an advanced **Local AI Host Agent** designed for Windows. It acts as an intelligent operating system layer that connects LLMs (Local or Cloud) with your local machine's capabilities.

Instead of just chatting, Resonance can **see** your files, **run** your scripts, and **evolve** by learning new skills.

### ✨ Key Features

*   **🧠 Hybrid Brain**: Seamlessly switch between Local LLMs (Ollama, etc.) for privacy and Cloud LLMs (GPT-4, DeepSeek) for complex reasoning.
*   **⚡ Skills System**: Register local automation scripts (Python, PowerShell) as "Skills". The Agent can call them intelligently with parameters.
*   **📂 File Awareness**: Scan project directories to understand your workspace and read file contents directly.
*   **🔋 System Monitor**: Real-time monitoring of CPU, RAM, and Battery via the dashboard.
*   **💾 Long-term Memory**: Remembers your projects, preferences, and facts across sessions.
*   **🖥️ Dual Interface**: Use it via a beautiful Web UI (Streamlit) or a geeky Command Line Interface (CLI).

---

### 🛠️ Configuration & Environment Setup

Follow this guide to set up the robust Conda environment and configuration files.

#### 1. Create Conda Environment
Ensure you have Anaconda or Miniconda installed. Open your terminal:

```bash
# Create a fresh environment with Python 3.11
conda create -n resonance python=3.11 -y

# Activate the environment
conda activate resonance

# Install dependencies
pip install -r requirements.txt
```

#### 2. Initialize Configuration
You need to create the configuration file `config/config.yaml`.

Two equivalent ways to create a config:

**Option A: Leverage Quick Start Template**  
Run the following command in the project root to create a default config:

```powershell
# Windows PowerShell
copy config\config.yaml.template config\config.yaml
```

**Option B: Manual Configuration (Template Content)**
If `config.yaml.template` does not exist, create a file named `config/config.yaml` and paste the following content:

```yaml
# config/config.yaml
active_profile: openai_main  # The profile ID to use by default

system:
  name: Resonance
  version: 2.3.0
  log_dir: ./logs
  user_profile_path: config/user_profile.yaml
  system_prompt: "" # Leave empty to use default internal prompt

scripts:
  # Example Skill
  say_hello:
    command: Write-Host "Hello from Resonance!"
    description: Print a greeting message
    cwd: null
    timeout: 30
    delay: 0
```


---

### 3. 🚀 Usage Guide

#### 1. Run Web Interface
The main dashboard for monitoring and interaction.
```bash
python main.py
```
*Access via browser (usually http://localhost:8501).*

#### 2. Run CLI Mode(Need a model profile configured)
Quickly execute tasks without opening the UI.
```bash
python main.py "Check my battery status and scan D:\Projects"
```
### 4. Setup Model Profiles

#### It's a must for Resonance to work properly.

**Run the Web Interface, and you will see a side panel, configure your model profiles there.**

If above method fails, please:

Manually edit `config/profiles.yaml` to add your API keys.

```yaml
# config/profiles.yaml
profiles:
  openai_main:
    name: OpenAI GPT-4
    provider: openai
    model: gpt-4
    api_key: sk-YOUR_KEY_HERE
    base_url: https://api.openai.com/v1
    temperature: 0.7
  
  local_ollama:
    name: Local Llama3
    provider: openai
    model: llama3
    api_key: ollama
    base_url: http://localhost:11434/v1
    temperature: 0.7
```

[![Star History Chart](https://api.star-history.com/svg?repos=JulianRyder01/Resonance&type=Date)](https://star-history.com/JulianRyder01/Resonance&Date)

---

<a name="chinese"></a>
## 🇨🇳 中文介绍

**Resonance** 是一个专为 Windows 设计的高级**本地智能体主机 (AI Host)**。它不仅仅是一个聊天机器人，更是一个连接大模型（本地或云端）与你电脑底层能力的智能操作系统层。

它不仅能陪你聊天，还能**看懂**你的文件，**执行**你的脚本，并通过学习新技能不断**进化**。

### ✨ 核心特性

*   **🧠 混合大脑架构**：无缝切换本地模型（如 Ollama，保护隐私）和云端模型（如 GPT-4, DeepSeek，处理复杂任务）。
*   **⚡ 技能 (Skills) 系统**：将你的本地自动化流程脚本（Python, PowerShell）注册为“技能”。Agent 可以智能调用它们并传递参数。
*   **📂 文件感知能力**：支持扫描项目目录结构，并能直接读取文件内容进行分析。
*   **🔋 系统监控**：通过仪表盘实时监控 CPU、内存和电池状态。
*   **💾 长时记忆**：跨会话记住你的项目路径、个人偏好和关键事实。
*   **🖥️ 双模交互**：既有美观的 Web UI (Streamlit)，也有极客风的命令行接口 (CLI)。

### 🛠️ 环境搭建与配置指南

请按照以下步骤创建 Conda 环境并初始化配置。

#### 1. 创建 Conda 环境
确保已安装 Anaconda 或 Miniconda。在终端执行：

```bash
# 创建 Python 3.11 环境
conda create -n resonance python=3.11 -y

# 激活环境
conda activate resonance

# 安装依赖
pip install -r requirements.txt
```

#### 2. 初始化配置文件
你需要创建 `config/config.yaml` 才能运行程序。

**使用模板命令**
在项目根目录运行以下命令快速复制模板：

```powershell
# Windows PowerShell
copy config\config.yaml.template config\config.yaml
```

**如果以上方法失效：**

请手动新建 `config/config.yaml` 并填入以下内容：

```yaml
# config/config.yaml
active_profile: openai_main  # 默认使用的模型配置ID

system:
  name: Resonance
  version: 2.3.0
  log_dir: ./logs
  user_profile_path: config/user_profile.yaml
  system_prompt: "" # 留空则使用内置默认提示词

scripts:
  # 示例技能
  info_box:
    command: Write-Host "Resonance Online"
    description: 显示系统在线状态
    cwd: null
    timeout: 60
    delay: 0
```


### 3. 🚀 运行

```bash
# 启动 Web 图形界面
python main.py

# 或者使用命令行模式快速执行
python main.py "帮我看看 D盘 有什么项目"
```

### 4. 配置模型密钥

#### Resonance 必须配置好LLM才能使用！

请按上一步的指引运行起来，你会在浏览器界面看见Resonance UI。

左侧栏选择配置模型，可以在这里输入你的模型与密钥。

**如果以上方法失效：**
编辑 `config/profiles.yaml` 填入你的模型信息：

```yaml
# config/profiles.yaml
profiles:
  openai_main:
    name: OpenAI GPT-4
    provider: openai
    model: gpt-4
    api_key: sk-你的密钥
    base_url: https://api.openai.com/v1
    temperature: 0.7
  
  local_ollama:
    name: 本地 Ollama
    provider: openai
    model: qwen2
    api_key: ollama
    base_url: http://localhost:11434/v1
    temperature: 0.7
```
---

**Resonance** - *Echoing Intelligence Locally.*
