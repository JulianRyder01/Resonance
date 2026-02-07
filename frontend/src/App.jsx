import React, { useState, useEffect } from 'react';
import { Toaster, toast } from 'sonner';
import { 
  Terminal, Shield, Activity, Database, Settings, 
  Zap, Cpu, Wifi, WifiOff 
} from 'lucide-react';

import ChatInterface from './components/ChatInterface';
import SentinelDashboard from './components/SentinelDashboard';
import SystemMonitor from './components/SystemMonitor';
import MemoryManager from './components/MemoryManager';
import ModelConfig from './components/ModelConfig';

const WS_URL = "ws://localhost:8000/ws/chat";

function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const [ws, setWs] = useState(null);
  const [isConnected, setIsConnected] = useState(false);

  // WebSocket 连接管理
  useEffect(() => {
    let socket;
    let retryInterval;

    const connect = () => {
      socket = new WebSocket(WS_URL);
      
      socket.onopen = () => {
        setIsConnected(true);
        toast.success("Core Link Established");
        clearInterval(retryInterval);
      };
      
      socket.onclose = () => {
        setIsConnected(false);
        // 尝试重连
        retryInterval = setTimeout(connect, 3000);
      };

      socket.onerror = (err) => {
        console.error("WS Error", err);
        socket.close();
      };

    socket.onmessage = (event) => {
        try {
      const data = JSON.parse(event.data);
      if (data.type === 'sentinel_alert') {
        toast.warning("Sentinel Triggered!", {
          description: data.content,
              action: { label: "View", onClick: () => setActiveTab('sentinel') },
              duration: 8000,
        });
      }
        } catch (e) {
          console.error("WS Parse Error", e);
        }
    };
    setWs(socket);
    };

    connect();

    return () => {
      if (socket) socket.close();
      clearTimeout(retryInterval);
    };
  }, []);

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
              <span className="text-[10px] text-slate-500 font-mono">WS_LINK_V2</span>
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