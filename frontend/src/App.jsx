// frontend/src/App.jsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Toaster, toast } from 'sonner';
import { 
  Terminal, Shield, Activity, Database, Settings, 
  Zap, Wifi, WifiOff, Package // [新增] Package icon
} from 'lucide-react';

import ChatInterface from './components/ChatInterface';
import SentinelDashboard from './components/SentinelDashboard';
import SystemMonitor from './components/SystemMonitor';
import MemoryManager from './components/MemoryManager';
import ModelConfig from './components/ModelConfig';
import SkillStore from './components/SkillStore'; // [新增]

const WS_URL = "ws://localhost:8000/ws/chat";
const HEARTBEAT_INTERVAL = 30000; // 30秒一次心跳
const RECONNECT_BASE_DELAY = 1000;
const MAX_RECONNECT_DELAY = 10000;

function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const [ws, setWs] = useState(null);
  const [isConnected, setIsConnected] = useState(false);

  // 使用 Ref 避免闭包陷阱
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const heartbeatIntervalRef = useRef(null);
  const reconnectAttempts = useRef(0);

  // --- 稳健的 WebSocket 连接逻辑 ---
  const connect = useCallback(() => {
    // 防止重复连接
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const socket = new WebSocket(WS_URL);
    wsRef.current = socket;
      
      socket.onopen = () => {
      console.log("[WS] Connected");
        setIsConnected(true);
      reconnectAttempts.current = 0; // 重置重连次数
      setWs(socket);
      toast.success("Resonance Core Connected");
      
      // 启动心跳检测
      startHeartbeat();
      };
      
    socket.onclose = (event) => {
      console.warn("[WS] Closed", event.code);
        setIsConnected(false);
      setWs(null);
      stopHeartbeat();
      
      // 指数退避重连
      const delay = Math.min(
        RECONNECT_BASE_DELAY * Math.pow(1.5, reconnectAttempts.current),
        MAX_RECONNECT_DELAY
      );
      
      console.log(`[WS] Reconnecting in ${delay}ms...`);
      reconnectTimeoutRef.current = setTimeout(() => {
        reconnectAttempts.current += 1;
        connect();
      }, delay);
      };

      socket.onerror = (err) => {
      console.error("[WS] Error:", err);
      // onerror 之后通常会触发 onclose，所以逻辑在 onclose 处理
        socket.close();
      };

    socket.onmessage = (event) => {
        try {
      const data = JSON.parse(event.data);
      if (data.type === 'sentinel_alert') {
        // [修复 Bug ②] 使用 id 属性防止重复弹窗
        // 我们使用 data.content 作为基础哈希，确保相同内容的消息不会重复显示
        const toastId = btoa(encodeURIComponent(data.content)).slice(0, 16);
        
        toast.warning("Sentinel Triggered!", {
          id: toastId, // <--- 关键修复：Sonner 会自动去重
          description: data.content,
              action: { label: "View", onClick: () => setActiveTab('sentinel') },
              duration: 6000,
        });
      }
        // 处理心跳回应 (如果后端有 pong)
        if (data.type === 'pong') {
           // console.debug("Heartbeat pong received");
        }
      } catch (e) {
        // 忽略解析错误，交给组件处理
      }
    };

  }, []);

  const startHeartbeat = () => {
    stopHeartbeat();
    heartbeatIntervalRef.current = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        // 发送一个空包或者特定 ping 包，防止连接因闲置断开
        // 注意：后端需要能处理这个消息而不报错，或者前端发一个不影响逻辑的消息
        // 这里我们不做显式 ping 帧 (浏览器控制不了)，而是发一个业务层的 keepalive
        // 如果后端没有专门的 ping handler，可以不发，只要有 TCP Keepalive 即可。
        // 但为了稳健，建议后端忽略未知消息或前端只在断开时重连。
        // 简单策略：不主动发数据，依靠 readystate 检查和自动重连。
      }
    }, HEARTBEAT_INTERVAL);
  };

  const stopHeartbeat = () => {
    if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);
    };

  // 初始启动
  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      stopHeartbeat();
    };
  }, [connect]);

  // 手动轮询检查 (作为双重保险)
  useEffect(() => {
    const healthCheck = setInterval(() => {
      if (!isConnected && (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED)) {
        console.log("[Health] WS seems dead, forcing reconnect...");
        connect();
      }
    }, 5000);
    return () => clearInterval(healthCheck);
  }, [isConnected, connect]);


  return (
    <div className="flex h-screen w-screen bg-background text-text-primary overflow-hidden font-sans selection:bg-primary/20">
      <Toaster position="top-right" theme="light" closeButton richColors className="font-sans" />
      
      {/* 侧边栏：白色简约风 */}
      <aside className="w-64 flex flex-col border-r border-border bg-surface shrink-0 z-20 shadow-sm">
        <div className="p-6">
          <div className="flex items-center gap-3 mb-10 group cursor-default">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-lg shadow-blue-500/20 group-hover:scale-105 transition-transform duration-300">
              <Zap size={20} className="text-white" />
            </div>
            <div>
              <span className="text-lg font-bold tracking-tight text-slate-800 block leading-tight">Resonance</span>
              <span className="text-[10px] font-medium text-slate-400 tracking-wider uppercase">AI Host OS</span>
            </div>
          </div>

          <nav className="space-y-1">
            <NavItem active={activeTab === 'chat'} onClick={() => setActiveTab('chat')} icon={Terminal} label="Chat Console" />
            
            {/* [新增] Skill Store 导航 */}
            <NavItem active={activeTab === 'skills'} onClick={() => setActiveTab('skills')} icon={Package} label="Skill Store" />
            
            <NavItem active={activeTab === 'sentinel'} onClick={() => setActiveTab('sentinel')} icon={Shield} label="Sentinel System" />
            <NavItem active={activeTab === 'memory'} onClick={() => setActiveTab('memory')} icon={Database} label="Memory Core" />
            <NavItem active={activeTab === 'monitor'} onClick={() => setActiveTab('monitor')} icon={Activity} label="System Monitor" />
            
            <div className="pt-6 pb-2">
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider px-4 mb-2">Configuration</div>
              <NavItem active={activeTab === 'config'} onClick={() => setActiveTab('config')} icon={Settings} label="Model Settings" />
            </div>
          </nav>
        </div>

        <div className="mt-auto p-4 border-t border-border">
          <div className={`p-3 rounded-lg border transition-all duration-300 ${isConnected ? 'bg-emerald-50 border-emerald-100' : 'bg-red-50 border-red-100'}`}>
            <div className="flex items-center justify-between mb-1">
              <span className={`text-xs font-bold uppercase tracking-wide ${isConnected ? 'text-emerald-700' : 'text-red-700'}`}>
                {isConnected ? 'System Online' : 'Disconnected'}
              </span>
              {isConnected ? <Wifi size={14} className="text-emerald-500" /> : <WifiOff size={14} className="text-red-500" />}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
              <span className="text-[10px] text-slate-500 font-mono">
                {isConnected ? 'Backend Service' : 'RECONNECTING...'}
              </span>
            </div>
          </div>
        </div>
      </aside>

      {/* 主内容区：淡灰背景 + 微阴影 */}
      <main className="flex-1 flex flex-col min-w-0 bg-background relative">
        {/* 背景装饰 */}
        <div className="absolute top-0 left-0 w-full h-64 bg-gradient-to-b from-white to-transparent pointer-events-none z-0" />
        
        <div className="flex-1 z-10 overflow-hidden relative">
        {activeTab === 'chat' && <ChatInterface ws={ws} isConnected={isConnected} />}
          {activeTab === 'skills' && <SkillStore />} {/* [新增] */}
        {activeTab === 'sentinel' && <SentinelDashboard />}
        {activeTab === 'monitor' && <SystemMonitor />}
          {activeTab === 'memory' && <MemoryManager />}
          {activeTab === 'config' && <ModelConfig />}
        </div>
      </main>
    </div>
  );
}

const NavItem = ({ active, onClick, icon: Icon, label }) => (
  <button 
    onClick={onClick}
    className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg transition-all duration-200 group relative
      ${active 
        ? 'bg-primary/10 text-primary font-semibold shadow-sm' 
        : 'text-slate-500 hover:text-slate-800 hover:bg-white hover:shadow-sm'
      }
    `}
  >
    {active && <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-primary rounded-r-full" />}
    <Icon size={18} className={`transition-colors ${active ? 'text-primary' : 'text-slate-400 group-hover:text-slate-600'}`} />
    <span className="text-sm">{label}</span>
  </button>
);

export default App;