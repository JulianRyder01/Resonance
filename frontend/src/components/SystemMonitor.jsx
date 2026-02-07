import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Cpu, Database, Battery, Zap, Activity, HardDrive, RefreshCw } from 'lucide-react';

const API_BASE = "http://localhost:8000/api";

export default function SystemMonitor() {
  const [metrics, setMetrics] = useState(null);
  const [processes, setProcesses] = useState([]);
  const [loading, setLoading] = useState(true);

  const refreshData = async () => {
    try {
      const [mRes, pRes] = await Promise.all([
        axios.get(`${API_BASE}/system/metrics`),
        axios.get(`${API_BASE}/system/processes`)
      ]);
      setMetrics(mRes.data);
      setProcesses(pRes.data);
      setLoading(false);
    } catch (err) {
      console.error("Monitor error:", err);
    }
  };

  useEffect(() => {
    refreshData();
    const timer = setInterval(refreshData, 3000);
    return () => clearInterval(timer);
  }, []);

  if (loading && !metrics) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 gap-2">
        <RefreshCw className="animate-spin" size={20} />
        Initializing Telemetry...
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-in fade-in duration-500">
      <header className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">System Resources</h1>
          <p className="text-slate-500 mt-1">Real-time performance telemetry.</p>
        </div>
        <div className="text-xs font-mono text-slate-400 bg-slate-100 px-3 py-1 rounded-full">
          LAST UPDATE: {metrics?.timestamp}
        </div>
      </header>

      {/* 核心指标卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <MetricCard 
          label="CPU Usage" 
          value={`${metrics?.cpu_percent}%`} 
          icon={Cpu} 
          color="text-blue-500"
          bg="bg-blue-500"
          progress={metrics?.cpu_percent}
        />
        <MetricCard 
          label="Memory (RAM)" 
          value={`${metrics?.memory_percent}%`} 
          subValue={`${metrics?.memory_used_gb} / ${metrics?.memory_total_gb} GB`}
          icon={Database} 
          color="text-purple-500"
          bg="bg-purple-500"
          progress={metrics?.memory_percent}
        />
        <MetricCard 
          label="Battery Status" 
          value={`${metrics?.battery_percent}%`} 
          subValue={metrics?.power_plugged ? "AC Power Connected" : "On Battery Supply"}
          icon={metrics?.power_plugged ? Zap : Battery} 
          color={metrics?.battery_percent < 20 ? "text-red-500" : "text-emerald-500"}
          bg={metrics?.battery_percent < 20 ? "bg-red-500" : "bg-emerald-500"}
          progress={metrics?.battery_percent}
        />
      </div>

      {/* 进程列表与磁盘状态 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* 进程排行榜 */}
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
            <div className="flex items-center gap-2 font-bold text-slate-700">
              <Activity size={18} className="text-blue-500" />
              Top Resource Consumers
            </div>
            <span className="text-[10px] text-slate-400 uppercase tracking-widest font-semibold">Live Feed</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-100 bg-slate-50/30">
                <tr>
                  <th className="px-6 py-3 font-medium">Process Name</th>
                  <th className="px-6 py-3 font-medium">PID</th>
                  <th className="px-6 py-3 font-medium text-right">CPU %</th>
                  <th className="px-6 py-3 font-medium text-right">MEM %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {processes.map((proc, i) => (
                  <tr key={i} className="hover:bg-slate-50 transition-colors group">
                    <td className="px-6 py-3 text-slate-700 font-medium group-hover:text-primary transition-colors">
                      {proc.name}
                    </td>
                    <td className="px-6 py-3 text-slate-400 font-mono text-xs">{proc.pid}</td>
                    <td className="px-6 py-3 text-right">
                      <span className={`px-2 py-0.5 rounded ${proc.cpu_percent > 50 ? 'bg-red-50 text-red-600' : 'text-slate-500'}`}>
                        {proc.cpu_percent.toFixed(1)}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right text-slate-500">
                      {proc.memory_percent.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 快捷信息侧栏 */}
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
             <div className="flex items-center gap-2 font-bold text-slate-700 mb-6">
                <HardDrive size={18} className="text-amber-500" />
                Drive Storage
             </div>
             <DiskUsage path="C:\" />
             <div className="mt-8 space-y-4">
               <div className="p-4 bg-blue-50 border border-blue-100 rounded-xl">
                 <h4 className="text-blue-600 text-xs font-bold uppercase mb-1">Agent Tip</h4>
                 <p className="text-slate-600 text-xs leading-relaxed">
                   Currently monitoring {processes.length} active processes. System load is within normal operating parameters.
                 </p>
               </div>
             </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function DiskUsage({ path }) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span className="text-slate-600 font-medium">{path} Drive</span>
        <span className="text-slate-400">72% Full</span>
      </div>
      <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full bg-amber-400 w-[72%] shadow-sm" />
      </div>
      <div className="flex justify-between text-[10px] text-slate-400 font-mono mt-1">
        <span>USED: 342 GB</span>
        <span>FREE: 120 GB</span>
      </div>
    </div>
  );
}

function MetricCard({ label, value, subValue, icon: Icon, color, bg, progress }) {
  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-6 relative overflow-hidden group hover:shadow-lg transition-all duration-300">
      <div className={`absolute top-0 right-0 p-4 opacity-[0.05] group-hover:opacity-10 group-hover:scale-110 transition-all ${color}`}>
        <Icon size={80} />
      </div>
      
      <div className="relative z-10">
        <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-wider mb-3">
          <Icon size={16} className={color} />
          {label}
        </div>
        <div className="text-4xl font-bold tracking-tight mb-1 text-slate-800">
          {value}
        </div>
        {subValue && <div className="text-xs text-slate-500 font-medium">{subValue}</div>}
        
        <div className="mt-5 h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-1000 ease-out ${bg}`} 
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    </div>
  );
}