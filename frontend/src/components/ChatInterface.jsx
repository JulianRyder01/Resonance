// frontend/src/components/ChatInterface.jsx
import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import axios from 'axios';
import { 
  Send, Bot, User, Command, Eraser, Play, Loader2, StopCircle, 
  MessageSquare, Plus, Trash2, Edit2, Check, X, ChevronDown, ChevronRight
} from 'lucide-react';
import { toast } from 'sonner';
import TaskMonitor from './TaskMonitor'; // [新增]

const API_BASE = "http://localhost:8000/api";

// [新增] 可折叠的 Tool Message 组件
const ToolMessage = ({ name, content }) => {
    const [expanded, setExpanded] = useState(false);
    // 确保 content 是字符串以便处理
    const safeContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
    const preview = safeContent.length > 100 ? safeContent.slice(0, 100) + "..." : safeContent;
    
    // [修复点] 确保工具名不为空时有显示，为空时显示 Unknown Tool
    const displayName = name || "system_call";
    
    return (
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden text-xs w-full max-w-full my-1">
            <button 
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center gap-2 px-3 py-2 bg-slate-950 hover:bg-slate-900 transition-colors text-blue-400 font-mono uppercase tracking-wider text-[10px]"
            >
                {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <Play size={10} /> 
                TOOL: {displayName}
                {!expanded && <span className="text-slate-500 normal-case tracking-normal ml-auto truncate max-w-[300px]">{preview}</span>}
            </button>
            {expanded && (
                <div className="p-3 border-t border-slate-800 bg-slate-900 overflow-x-auto">
                    <pre className="font-mono text-slate-300 whitespace-pre-wrap break-all">{safeContent}</pre>
                </div>
            )}
        </div>
    );
};

export default function ChatInterface({ ws, isConnected }) {
  const { t } = useTranslation();
  // 会话状态
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState("resonance_main");
  const [messages, setMessages] = useState([]);
  
  // 交互状态
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  
  // [新增] 任务监控状态
  const [currentPlan, setCurrentPlan] = useState("");
  
  const scrollRef = useRef(null);
  // [新增] 滚动容器引用
  const containerRef = useRef(null);
  // [新增] 标记用户是否在查看历史
  const isUserScrollingRef = useRef(false);

  // --- [新增] URL Deep Link 支持 ---
  useEffect(() => {
    // 检查 URL 是否有 ?session=xxx 参数
    const params = new URLSearchParams(window.location.search);
    const urlSession = params.get('session');
    if (urlSession) {
      console.log("Deep link to session:", urlSession);
      setActiveSessionId(urlSession);
      // 清除 URL 参数，防止刷新时滞留（可选）
      // window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  // --- 1. 会话管理逻辑 ---

  const fetchSessions = async () => {
    setLoadingSessions(true);
    try {
      const res = await axios.get(`${API_BASE}/sessions`);
      // 确保 resonance_main 始终存在
      const list = res.data;
      if (!list.find(s => s.id === "resonance_main")) {
        list.unshift({ id: "resonance_main", preview: t('chat.main_process'), updated_at: Date.now() }); // [修改点] 翻译
      }
      setSessions(list);
    } catch (err) {
      toast.error(t('chat.load_failed')); // [修改点] 翻译错误提示
    } finally {
      setLoadingSessions(false);
    }
  };

  const createSession = async () => {
    const newId = `session_${Date.now()}`;
    try {
      await axios.post(`${API_BASE}/sessions`, { session_id: newId });
      setActiveSessionId(newId);
      setMessages([]);
      fetchSessions();
    } catch (err) {
      toast.error(t('common.failed'));
    }
  };

  const deleteSession = async (e, id) => {
    e.stopPropagation();
    if (id === "resonance_main") {
      toast.error(t('chat.cannot_delete_main'));
      return;
    }
    if (!confirm(t('chat.delete_conversation'))) return;
    
    try {
      await axios.delete(`${API_BASE}/sessions/${id}`);
      if (activeSessionId === id) setActiveSessionId("resonance_main");
      fetchSessions();
    } catch (err) {
      toast.error(t('common.failed'));
    }
  };

  const startRename = (e, session) => {
    e.stopPropagation();
    setEditingSessionId(session.id);
    setRenameValue(session.id);
  };

  const confirmRename = async (e) => {
    e.stopPropagation();
    if (!renameValue.trim()) return;
    try {
      await axios.patch(`${API_BASE}/sessions/${editingSessionId}`, { new_name: renameValue });
      if (activeSessionId === editingSessionId) setActiveSessionId(renameValue);
      setEditingSessionId(null);
      fetchSessions();
    } catch (err) {
      toast.error("Rename failed (Duplicate name?)");
    }
  };

  // --- 2. 消息加载逻辑 ---

  const loadHistory = async (sid) => {
    try {
      const res = await axios.get(`${API_BASE}/history?session_id=${sid}`);
      setMessages(res.data);
      // [新增] 从历史记录中恢复 Plan
      const lastPlanMsg = [...res.data].reverse().find(m => m.role === 'assistant' && m.content.includes('<plan>'));
      if (lastPlanMsg) {
        extractPlan(lastPlanMsg.content);
      } else {
        setCurrentPlan("");
      }
      setTimeout(scrollToBottom, 100);
    } catch (err) {
      console.error("History load error", err);
    }
  };

  // [新增] 提取 Plan 的逻辑
  const extractPlan = (text) => {
    const planMatch = text.match(/<plan>([\s\S]*?)<\/plan>/);
    if (planMatch) {
      setCurrentPlan(planMatch[1]);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  useEffect(() => {
    loadHistory(activeSessionId);
  }, [activeSessionId]);

  // --- 3. WebSocket 消息处理 ---

  useEffect(() => {
    if (!ws) return;

    const handleMsg = (e) => {
      try {
        const data = JSON.parse(e.data);
      
      // [关键点] 检查消息是否属于当前打开的会话
      if (data.session_id && data.session_id !== activeSessionId) {
        // 如果是其他会话的消息，可以保持静默或在侧边栏显示红点
        return; 
      }
        
        if (data.type === 'delta') {
          const deltaContent = data.content ?? ""; 
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant' && !last.complete) {
              const updatedMessages = [...prev];
              const newContent = (last.content || "") + deltaContent;
              updatedMessages[updatedMessages.length - 1] = {
                ...last,
                content: newContent
              };
              // [新增] 实时解析 Plan
              extractPlan(newContent);
              return updatedMessages;
            }
            return [...prev, { role: 'assistant', content: deltaContent, complete: false }];
          });
        } 
        else if (data.type === 'user') {
          setMessages(prev => {
            // 检查 ID 是否已经存在于当前列表中
            const exists = prev.some(m => m.id === data.id);
            if (exists) return prev; // 如果已存在（本地已添加），则忽略回显
            
            // 如果不存在（比如是从另一个设备同步过来的消息），则添加
            return [...prev, { 
              role: 'user', 
              content: data.content, 
              id: data.id || Date.now().toString() 
            }];
          });
          setIsTyping(true);
          scrollToBottom(); // 如果是用户发的信息，强制滚动到底
        }
        else if (data.type === 'done') {
          setMessages(prev => prev.map(m => ({ ...m, complete: true })));
          setIsTyping(false);
          // 刷新列表以更新预览
          fetchSessions();
        } 
        else if (data.type === 'tool') {
          setMessages(prev => [...prev, { 
            role: 'tool', 
            name: data.name, 
            content: String(data.content ?? "No output") 
          }]);
        } 
        else if (data.type === 'status') {
            // 处理后端发来的状态信息，例如 Stop 确认
            if (data.content.includes("Aborted") || data.content.includes("Stop")) {
                 setIsTyping(false);
                 setMessages(prev => [...prev, { role: 'system', content: t('chat.aborted') }]);
             } else if (data.content.includes("Supervisor")) {
                 // [新增] 显示督战信息
                setMessages(prev => [...prev, { role: 'system', content: t('chat.supervisor') + ": " + data.content.split(":")[1]}]);
            }
        } 
        else if (data.type === 'error') {
          toast.error("AI Core Error", { description: data.content });
          setIsTyping(false);
        }
      } catch (err) {
        console.error("WS Message Parse Error:", err);
      }
    };

    ws.addEventListener('message', handleMsg);
    return () => ws.removeEventListener('message', handleMsg);
  }, [ws, activeSessionId]); // 依赖 activeSessionId 确保消息路由正确

  // [修改点] 智能滚动逻辑
  const scrollToBottom = () => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  };

  useEffect(() => {
    // 只有当用户没有向上滚动查看历史时，才自动滚动
    if (!isUserScrollingRef.current) {
        scrollToBottom();
    }
  }, [messages, isTyping]);

  // 监听滚动事件，判断用户是否在查看历史
  const handleScroll = (e) => {
      const { scrollTop, scrollHeight, clientHeight } = e.target;
      // 如果距离底部超过 100px，认为用户在查看历史
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
      isUserScrollingRef.current = !isNearBottom;
  };

  const sendMessage = () => {
  if (!input.trim() || !isConnected) return;
    const tempId = Date.now().toString();
    const msg = input.trim();

    // [修复Bug 1] 用户发送消息时，明确标记为打断操作
    // 这样可以确保之前的渲染流程被重置，新的输入能正确触发新的渲染流程
    try {
    if (msg !== "/stop") {
        // 在发送消息时设置打断标记，并重置渲染状态
        setMessages(prev => [...prev, { role: 'user', content: msg, id: tempId, isInterrupted: true }]);
        // 立即设置isTyping为true，重置渲染状态
        setIsTyping(true);
        // 发送消息时重置滚动锁定
        isUserScrollingRef.current = false;
        setTimeout(scrollToBottom, 50);
    }

    ws.send(JSON.stringify({
      message: msg, // 已修正：从 messageText 改为 msg
      session_id: activeSessionId,
      id: tempId, // 发送 ID 给后端
      // [新增] 标记此消息为打断操作，用于后端中断之前的处理流程
      interrupt: true
    }));
    setInput("");
  } catch (err) {
        // [修复点] 如果报错，将其转为字符串再提示，防止渲染对象报错
        console.error("Send failed:", err);
        toast.error("Send failed", { description: String(err.message || err) });
  }
  };

  const handleInterrupt = () => {
    if (ws && isConnected) {
      ws.send(JSON.stringify({ message: "/stop", session_id: activeSessionId }));
      
      // 立即在前端给予反馈，不要等待后端
      toast.info(t('chat.interrupting'));
      // 我们不在这里设置 isTyping(false)，因为我们要等待后端确认 'status' 消息
      // 这样可以确保后端确实收到了指令并停止了处理
    }
  };

  const clearCurrentSession = async () => {
    if (!confirm(t('chat.clear_all_messages'))) return;
    try {
      await axios.delete(`${API_BASE}/sessions/${activeSessionId}/messages`);
      setMessages([]);
      setCurrentPlan("");
    } catch(e) {
      toast.error(t('common.failed'));
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // [修复点] 确保渲染内容始终为有效节点
  const renderMessageContent = (m) => {
    if (m.role === 'tool') {
        return <ToolMessage name={m.name} content={m.content} />;
    }
    
    // 强制转换为字符串，防止“Objects are not valid as a React child”
    const text = typeof m.content === 'string' ? m.content : JSON.stringify(m.content);
    
    return (
        <div className="prose prose-sm max-w-none prose-slate">
            <ReactMarkdown>
                {text.replace(/<plan>[\s\S]*?<\/plan>/g, '*[Plan updated in Monitor]*') || ""}
            </ReactMarkdown>
        </div>
    );
  };

  return (
    <div className="flex h-full overflow-hidden bg-background">
      
      {/* [新增] 悬浮任务监控器 */}
      {currentPlan && <TaskMonitor planRaw={currentPlan} onClose={() => setCurrentPlan("")} />}

      {/* 左侧列表 (Keep Existing) */}
      <div className="w-64 border-r border-border bg-surface/50 flex flex-col shrink-0">
        <div className="p-4 border-b border-border">
          <button 
            onClick={createSession}
            className="w-full flex items-center justify-center gap-2 bg-white border border-border hover:border-primary text-slate-600 hover:text-primary py-2.5 rounded-lg transition-all shadow-sm font-medium text-sm"
          >
            <Plus size={16} /> {t('chat.new_chat')}
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.map(s => {
            const isActive = s.id === activeSessionId;
            const isEditing = editingSessionId === s.id;
            const isMain = s.id === "resonance_main";

            return (
              <div 
                key={s.id}
                onClick={() => !isEditing && setActiveSessionId(s.id)}
                className={`group flex items-center gap-3 px-3 py-3 rounded-lg cursor-pointer transition-all border border-transparent
                  ${isActive ? 'bg-white border-border shadow-sm' : 'hover:bg-white/50 text-slate-500'}
                `}
              >
                <div className={`p-1.5 rounded-md ${isMain ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-500'}`}>
                  {isMain ? <Bot size={14} /> : <MessageSquare size={14} />}
                </div>
                
                <div className="flex-1 min-w-0">
                  {isEditing ? (
                    <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                      <input 
                        autoFocus
                        className="w-full text-xs border rounded px-1 py-0.5"
                        value={renameValue}
                        onChange={e => setRenameValue(e.target.value)}
                      />
                      <button onClick={confirmRename} className="text-green-500"><Check size={12} /></button>
                      <button onClick={() => setEditingSessionId(null)} className="text-red-500"><X size={12} /></button>
                    </div>
                  ) : (
                    <>
                      <div className={`text-sm font-medium truncate ${isActive ? 'text-slate-800' : ''}`}>
                        {isMain ? t('chat.main_process') : s.id}
                      </div>
                      <div className="text-[10px] text-slate-400 truncate">
                        {s.preview ||  t('chat.empty_preview')}
                      </div>
                    </>
                  )}
                </div>

                {/* 操作按钮 (非主进程且非编辑状态) */}
                {!isMain && !isEditing && (
                  <div className="hidden group-hover:flex items-center gap-1">
                    <button onClick={(e) => startRename(e, s)} className="p-1 hover:text-blue-500 text-slate-300">
                      <Edit2 size={12} />
                    </button>
                    <button onClick={(e) => deleteSession(e, s.id)} className="p-1 hover:text-red-500 text-slate-300">
                      <Trash2 size={12} />
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* --- 右侧聊天主窗口 --- */}
      <div className="flex-1 flex flex-col min-w-0">
        
        {/* 头部状态栏 */}
        <div className="h-16 border-b border-border bg-surface/80 backdrop-blur-md flex items-center justify-between px-8 shrink-0 z-10">
          <div className="flex items-center gap-3">
            <span className="font-bold text-slate-700 text-lg">
              {activeSessionId === "resonance_main" ? t('chat.main_process') : activeSessionId}
            </span>
            <div className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider 
              ${isConnected ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
              {isConnected ? 'ONLINE' : 'OFFLINE'}
            </div>
          </div>
          <div className="flex gap-2">
            {/* Stop 按钮逻辑优化：只有在 typing 时显示 */}
            {isTyping && (
              <button 
                onClick={handleInterrupt}
                className="flex items-center gap-2 px-3 py-1.5 text-xs font-bold text-red-500 hover:bg-red-50 rounded-lg transition-colors border border-red-100"
              >
                <StopCircle size={14} /> {t('chat.stop')}
              </button>
            )}
            <button 
              onClick={clearCurrentSession}
              className="p-2 text-text-secondary hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
              title="Clear History"
            >
              <Eraser size={18} />
            </button>
          </div>
        </div>

        {/* [修改点] 消息滚动区 + onScroll 事件 */}
        <div 
            ref={containerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto p-6 md:p-8 space-y-6"
        >
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-text-secondary/40 space-y-6 opacity-60">
              <div className="w-24 h-24 bg-surface rounded-3xl shadow-soft flex items-center justify-center border border-border">
                <Command size={40} className="text-primary/40" />
              </div>
              <div className="text-center">
                <p className="text-lg font-bold text-text-primary/60 italic tracking-tight">{t('chat.system_ready')}</p>
                <p className="text-sm">Session: {activeSessionId}</p>
              </div>
            </div>
          )}
          
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-4 ${m.role === 'user' ? 'flex-row-reverse' : ''} animate-in fade-in slide-in-from-bottom-3 duration-500`}>
              {/* 头像 */}
              <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 border shadow-sm
                ${m.role === 'user' ? 'bg-primary border-primary text-white' : 'bg-surface border-border text-primary'}`}>
                {m.role === 'user' ? <User size={18} /> : <Bot size={18} />}
              </div>
              
              {/* 消息气泡 */}
              <div className={`max-w-[85%] md:max-w-[75%] px-5 py-3.5 rounded-2xl text-[14.5px] leading-relaxed shadow-soft
                ${m.role === 'user' 
                  ? 'bg-primary text-white rounded-tr-none' 
                  : m.role === 'tool'
                    ? 'bg-slate-900 border border-slate-800 text-slate-300 font-mono text-xs w-full'
                    : m.role === 'system'
                      ? 'bg-amber-50 border border-amber-200 text-amber-800 w-full italic'
                      : 'bg-surface border border-border text-text-primary rounded-tl-none'
                }`}>
                {renderMessageContent(m)}
              </div>
            </div>
          ))}
          
          {isTyping && (
            <div className="flex gap-4 animate-pulse">
              <div className="w-9 h-9 rounded-xl bg-surface border border-border flex items-center justify-center">
                <Loader2 size={18} className="text-primary animate-spin" />
              </div>
              <div className="bg-surface border border-border px-5 py-3.5 rounded-2xl rounded-tl-none text-text-secondary text-sm shadow-soft">
                {t('chat.typing')}
              </div>
            </div>
          )}
          <div ref={scrollRef} className="h-4" />
        </div>

        {/* 输入控制区 */}
        <div className="p-6 md:px-10 md:pb-10 bg-gradient-to-t from-background via-background to-transparent z-10">
          <div className="max-w-4xl mx-auto relative shadow-glow rounded-2xl bg-surface border border-border focus-within:ring-4 focus-within:ring-primary/10 focus-within:border-primary transition-all duration-500">
            <textarea
              autoFocus
              rows={1}
              className="w-full bg-transparent pl-6 pr-16 py-4 text-[15px] text-text-primary placeholder-text-secondary/50 focus:outline-none resize-none overflow-hidden max-h-48"
              placeholder={t('chat.placeholder', { session: activeSessionId })}
              value={input}
              onChange={e => {
                setInput(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = e.target.scrollHeight + 'px';
              }}
              onKeyDown={handleKeyDown}
            />
            <button 
              onClick={sendMessage}
              disabled={!input.trim() || !isConnected}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-2.5 bg-primary text-white rounded-xl hover:bg-primary-hover disabled:opacity-30 disabled:grayscale transition-all shadow-lg active:scale-95"
              aria-label={t('chat.send')}
            >
              <Send size={20} />
            </button>
          </div>
          <p className="text-center text-[10px] text-text-secondary mt-4 uppercase tracking-tighter opacity-50">
            {t('chat.footer')}
          </p>
        </div>
      </div>
    </div>
  );
}