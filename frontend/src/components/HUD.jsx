// frontend/src/components/HUD.jsx
import React, { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { 
  Send, Bot, StopCircle, 
  Terminal, Sparkles
} from 'lucide-react';

const API_BASE = "http://localhost:8000/api";

export default function HUD({ ws, isConnected }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [currentPlan, setCurrentPlan] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  
  // HUD 默认使用主会话
  const sessionId = "resonance_main";
  const messagesEndRef = useRef(null);

  // 1. 初始化加载任务和最新消息
  useEffect(() => {
    const fetchContext = async () => {
      try {
        const res = await axios.get(`${API_BASE}/history?session_id=${sessionId}`);
        const history = res.data;
        
        // 提取最新的 Plan
        const lastPlanMsg = [...history].reverse().find(m => m.role === 'assistant' && m.content.includes('<plan>'));
        if (lastPlanMsg) {
          extractPlan(lastPlanMsg.content);
        }

        // 只保留最近的一条 AI 回复（和随后的工具调用）用于显示，避免刷屏
        // 或者保留最后 2-3 条
        setMessages(history.slice(-3));
      } catch (err) {
        console.error(err);
      }
    };
    fetchContext();
  }, []);

  const extractPlan = (text) => {
    const planMatch = text.match(/<plan>([\s\S]*?)<\/plan>/);
    if (planMatch) {
      setCurrentPlan(planMatch[1]);
    }
  };

  // 2. 解析任务列表
  const tasks = useMemo(() => {
    if (!currentPlan) return [];
    const regex = /- \[(x|X| )\] (.*)/g;
    const items = [];
    let match;
    while ((match = regex.exec(currentPlan)) !== null) {
      items.push({
        completed: match[1].toLowerCase() === 'x',
        text: match[2].trim()
      });
    }
    return items;
  }, [currentPlan]);

  const completedCount = tasks.filter(t => t.completed).length;
  const progress = tasks.length > 0 ? Math.round((completedCount / tasks.length) * 100) : 0;

  // 3. WS 监听
  useEffect(() => {
    if (!ws) return;

    const handleMsg = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.session_id && data.session_id !== sessionId) return;

        if (data.type === 'delta') {
          const deltaContent = data.content ?? "";
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant' && !last.complete) {
              const newContent = (last.content || "") + deltaContent;
              const updated = [...prev];
              updated[updated.length - 1] = { ...last, content: newContent };
              extractPlan(newContent);
              return updated;
            }
            return [...prev, { role: 'assistant', content: deltaContent, complete: false }];
          });
          setIsTyping(true);
        } else if (data.type === 'done') {
          setMessages(prev => prev.map(m => ({ ...m, complete: true })));
          setIsTyping(false);
        } else if (data.type === 'tool') {
          // HUD 中我们只显示简短的工具执行提示
          setMessages(prev => [...prev, { 
            role: 'tool', 
            name: data.name, 
            content: "Executed." 
          }]);
        }
      } catch (err) {}
    };

    ws.addEventListener('message', handleMsg);
    return () => ws.removeEventListener('message', handleMsg);
  }, [ws]);

  // 自动滚动到最新
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const handleSend = () => {
    if (!input.trim() || !isConnected) return;
    
    const msg = input;
    // 如果正在生成，先打断
    if (isTyping) {
        ws.send(JSON.stringify({ message: "/stop", session_id: sessionId }));
        // 稍微延迟一下发送新消息，确保后端重置状态
        setTimeout(() => {
            ws.send(JSON.stringify({ message: msg, session_id: sessionId }));
        }, 500);
    } else {
        ws.send(JSON.stringify({ message: msg, session_id: sessionId }));
    }
    
    // HUD 本地乐观更新
    setMessages(prev => [...prev, { role: 'user', content: msg }]);
    setInput("");
    setIsTyping(true);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 深色透明主题
  return (
    <div className="h-screen w-screen flex flex-col bg-slate-900/95 text-slate-200 border border-slate-700/50 shadow-2xl overflow-hidden font-sans">
      
      {/* 1. Header & Progress */}
      <div className="shrink-0 bg-slate-950/80 border-b border-slate-800 p-3">
        <div className="flex justify-between items-center mb-2">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-blue-400" />
            <span className="font-bold text-sm tracking-wide">Resonance HUD</span>
          </div>
          <span className="text-[10px] font-mono text-slate-500">
            {isConnected ? 'ONLINE' : 'OFFLINE'}
          </span>
        </div>
        
        {tasks.length > 0 ? (
          <div className="space-y-1">
            <div className="flex justify-between text-[10px] text-slate-400 uppercase">
              <span>Current Task</span>
              <span>{progress}%</span>
            </div>
            <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
              <div 
                className="h-full bg-blue-500 transition-all duration-500 ease-out" 
                style={{ width: `${progress}%` }}
              />
            </div>
            {/* 只显示第一个未完成的任务 */}
            <div className="text-xs text-slate-300 truncate mt-1">
              {tasks.find(t => !t.completed)?.text || "All tasks completed"}
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-500 italic">No active plan detected.</div>
        )}
      </div>

      {/* 2. Chat Stream */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 scrollbar-hide">
        {messages.length === 0 && (
            <div className="h-full flex items-center justify-center text-slate-700 text-sm">
                Waiting for commands...
            </div>
        )}
        
        {messages.map((m, i) => (
          <div key={i} className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
            <div className={`
              max-w-[95%] px-3 py-2 rounded-lg text-xs leading-relaxed
              ${m.role === 'user' 
                ? 'bg-blue-600/20 text-blue-100 border border-blue-500/30' 
                : m.role === 'tool'
                  ? 'bg-slate-800/50 text-slate-400 font-mono italic border border-slate-800'
                  : 'bg-slate-800/80 text-slate-200 border border-slate-700'}
            `}>
              {m.role === 'tool' ? (
                <span className="flex items-center gap-1">
                    <Terminal size={10} /> Tool: {m.name}
                </span>
              ) : (
                /* [修复点] 移除 ReactMarkdown 的 className，改用外层 div 包裹 */
                <div className="prose prose-invert prose-xs max-w-none">
                  <ReactMarkdown>
                  {m.content?.replace(/<plan>[\s\S]*?<\/plan>/g, '') || ""}
                </ReactMarkdown>
                </div>
              )}
            </div>
          </div>
        ))}
        {isTyping && (
            <div className="flex items-center gap-2 text-xs text-blue-400 animate-pulse px-2">
                <Bot size={12} /> Thinking...
            </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 3. Input Area */}
      <div className="shrink-0 p-3 bg-slate-950 border-t border-slate-800">
        <div className="relative">
          <textarea
            autoFocus
            rows={2}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-3 pr-10 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 resize-none placeholder-slate-600"
            placeholder="Chat with Resonance... (Ctrl+Enter)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button 
            onClick={handleSend}
            className="absolute right-2 top-2 p-1.5 text-slate-400 hover:text-blue-400 transition"
          >
            {isTyping ? <StopCircle size={16} className="text-red-400" /> : <Send size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}