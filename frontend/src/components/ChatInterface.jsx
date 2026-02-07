import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { Send, Bot, User, Command, Eraser, Play } from 'lucide-react';

export default function ChatInterface({ ws, isConnected }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!ws) return;
    const handleMsg = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'delta') {
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant' && !last.complete) {
              return [...prev.slice(0, -1), { ...last, content: last.content + data.content }];
            }
            return [...prev, { role: 'assistant', content: data.content, complete: false }];
          });
        } else if (data.type === 'user') {
          setMessages(prev => [...prev, { role: 'user', content: data.content }]);
          setIsTyping(true);
        } else if (data.type === 'done') {
          setMessages(prev => prev.map(m => ({ ...m, complete: true })));
          setIsTyping(false);
        } else if (data.type === 'tool') {
          setMessages(prev => [...prev, { role: 'tool', name: data.name, content: data.content }]);
        } else if (data.type === 'status') {
          // 可选：显示思考状态
        }
      } catch (err) {
        console.error("Msg Parse Error", err);
      }
    };
    ws.addEventListener('message', handleMsg);
    return () => ws.removeEventListener('message', handleMsg);
  }, [ws]);

  useEffect(() => { scrollRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const sendMessage = () => {
    if (!input.trim() || !isConnected) return;
    ws.send(JSON.stringify({ message: input }));
    setInput("");
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* 头部标题 */}
      <div className="h-16 border-b border-border bg-white/50 backdrop-blur-sm flex items-center justify-between px-8 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
          <span className="font-semibold text-slate-700">Interactive Session</span>
        </div>
        <button 
          onClick={() => setMessages([])}
          className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
          title="Clear History"
        >
          <Eraser size={18} />
        </button>
      </div>

      {/* 消息区域 */}
      <div className="flex-1 overflow-y-auto p-6 md:p-8 space-y-6">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-6 opacity-60">
            <div className="w-24 h-24 bg-slate-100 rounded-full flex items-center justify-center">
              <Command size={40} className="text-slate-300" />
            </div>
            <div className="text-center space-y-1">
              <p className="text-lg font-medium text-slate-600">Resonance Host Ready</p>
              <p className="text-sm">Awaiting commands or inquiries...</p>
            </div>
          </div>
        )}
        
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-4 ${m.role === 'user' ? 'flex-row-reverse' : ''} animate-in fade-in slide-in-from-bottom-2 duration-300`}>
            {/* 头像 */}
            <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 border shadow-sm
              ${m.role === 'user' ? 'bg-primary border-primary text-white' : 'bg-white border-slate-200 text-primary'}`}>
              {m.role === 'user' ? <User size={16} /> : <Bot size={16} />}
            </div>
            
            {/* 气泡 */}
            <div className={`max-w-[80%] md:max-w-[70%] px-5 py-3.5 rounded-2xl text-sm leading-relaxed shadow-sm
              ${m.role === 'user' 
                ? 'bg-primary text-white rounded-tr-none' 
                : m.role === 'tool'
                  ? 'bg-slate-50 border border-slate-200 text-slate-600 font-mono text-xs w-full'
                  : 'bg-white border border-slate-100 text-slate-800 rounded-tl-none'
              }`}>
              {m.role === 'tool' ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-blue-500 font-bold uppercase text-[10px] tracking-wider">
                    <Play size={10} /> Tool Output: {m.name}
                  </div>
                  <div className="overflow-x-auto whitespace-pre-wrap break-all">{m.content}</div>
                </div>
              ) : (
                <ReactMarkdown className="prose prose-sm max-w-none prose-slate">
                  {m.content}
                </ReactMarkdown>
              )}
            </div>
          </div>
        ))}
        {isTyping && (
          <div className="flex gap-4 animate-pulse">
            <div className="w-8 h-8 rounded-full bg-white border border-slate-200 flex items-center justify-center">
              <Bot size={16} className="text-slate-400" />
            </div>
            <div className="bg-white border border-slate-100 px-4 py-3 rounded-2xl rounded-tl-none text-slate-400 text-sm">
              Thinking...
            </div>
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      {/* 输入框 */}
      <div className="p-6 md:px-8 md:pb-8 bg-gradient-to-t from-background via-background to-transparent">
        <div className="max-w-4xl mx-auto relative shadow-soft rounded-2xl bg-white border border-slate-200 focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary transition-all duration-300">
          <textarea
            autoFocus
            rows={1}
            className="w-full bg-transparent pl-6 pr-14 py-4 text-sm text-slate-800 placeholder-slate-400 focus:outline-none resize-none overflow-hidden max-h-40"
            placeholder="Ask anything, or use /stop to interrupt..."
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
            disabled={!input.trim()}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-primary text-white rounded-xl hover:bg-primary-hover disabled:opacity-50 disabled:hover:bg-primary transition shadow-md"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}