import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { Trash2, Search, Database, RefreshCw, Clock, Tag, BarChart3, Zap, BrainCircuit, Filter } from 'lucide-react';
import { toast } from 'sonner';

const API_BASE = "http://localhost:8000/api";

export default function MemoryManager() {
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  
  // RAG 策略状态
  const [currentStrategy, setCurrentStrategy] = useState("semantic");
  const [strategyLoading, setStrategyLoading] = useState(false);

  // 1. 获取配置
  const fetchConfig = async () => {
    try {
      const res = await axios.get(`${API_BASE}/config/rag`);
      setCurrentStrategy(res.data.strategy);
    } catch (e) {
      console.error("Failed to fetch RAG strategy");
    }
  };

  // 2. 获取记忆数据
  const fetchMemories = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/memory`);
      const data = Array.isArray(res.data) ? res.data : [];
      const sorted = data.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      setMemories(sorted);
    } catch (err) {
      console.error(err);
      toast.error("Failed to load memories (Check backend logs)");
      setMemories([]); 
    } finally {
      setLoading(false);
    }
  };

  const updateStrategy = async (newStrat) => {
    setStrategyLoading(true);
    try {
      await axios.post(`${API_BASE}/config/rag`, { strategy: newStrat });
      setCurrentStrategy(newStrat);
      toast.success(`RAG Strategy updated to: ${newStrat}`);
    } catch (e) {
      toast.error("Failed to update strategy");
    } finally {
      setStrategyLoading(false);
    }
  };

  const deleteMemory = async (id) => {
    if (!confirm("Are you sure you want to delete this memory permanently?")) return;
    try {
      await axios.delete(`${API_BASE}/memory/${id}`);
      toast.success("Memory deleted");
      setMemories(prev => prev.filter(m => m.id !== id));
    } catch (err) {
      toast.error("Failed to delete");
    }
  };

  useEffect(() => {
    fetchConfig();
    fetchMemories();
  }, []);

  const filtered = memories.filter(m => 
    (m.content || "").toLowerCase().includes(search.toLowerCase()) || 
    (m.type || "").toLowerCase().includes(search.toLowerCase())
  );

  // 数据统计逻辑
  const stats = useMemo(() => {
    if (!memories.length) return null;
    const total = memories.length;
    
    // 最近30天活跃
    const now = new Date();
    const activeRecent = memories.filter(m => {
        const d = new Date(m.last_accessed);
        const diffTime = Math.abs(now - d);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)); 
        return diffDays <= 7;
    }).length;

    // 最热门
    const mostAccessed = [...memories].sort((a, b) => b.access_count - a.access_count)[0];

    return { total, activeRecent, mostAccessed };
  }, [memories]);

  return (
    <div className="p-8 max-w-7xl mx-auto h-full flex flex-col">
      <header className="flex justify-between items-end mb-6 shrink-0">
        <div>
          <h1 className="text-3xl font-bold text-slate-800 flex items-center gap-3">
            <Database className="text-primary" /> Memory Core
          </h1>
          <p className="text-slate-500 mt-1">Manage long-term vector knowledge base (RAG).</p>
        </div>
        
        <div className="flex gap-3">
            {/* 策略切换器 */}
            <div className="flex items-center gap-2 bg-slate-100 p-1 rounded-lg border border-slate-200">
                <button 
                    onClick={() => updateStrategy('semantic')}
                    disabled={strategyLoading}
                    className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${currentStrategy === 'semantic' ? 'bg-white text-primary shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                >
                    Semantic
                </button>
                <button 
                    onClick={() => updateStrategy('hybrid_time')}
                    disabled={strategyLoading}
                    className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${currentStrategy === 'hybrid_time' ? 'bg-white text-purple-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                >
                    Hybrid (Time-Weighted)
                </button>
            </div>

            <button 
            onClick={fetchMemories} 
            className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 hover:text-primary transition shadow-sm"
            >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh
            </button>
        </div>
      </header>

      {/* --- Dashboard Stats --- */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8 shrink-0">
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
            <div className="p-3 bg-blue-50 text-blue-500 rounded-lg"><Database size={24} /></div>
            <div>
              <div className="text-sm text-slate-500 font-medium">Total Vectors</div>
              <div className="text-2xl font-bold text-slate-800">{stats.total}</div>
            </div>
          </div>

          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
            <div className="p-3 bg-emerald-50 text-emerald-500 rounded-lg"><Activity size={24} /></div>
            <div>
              <div className="text-sm text-slate-500 font-medium">Active (7 Days)</div>
              <div className="text-2xl font-bold text-slate-800">{stats.activeRecent}</div>
            </div>
          </div>

          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
            <div className="p-3 bg-amber-50 text-amber-500 rounded-lg"><Zap size={24} /></div>
            <div className="min-w-0 flex-1">
              <div className="text-sm text-slate-500 font-medium">Top Memory</div>
              <div className="text-xs font-bold text-slate-800 truncate" title={stats.mostAccessed?.content}>
                {stats.mostAccessed?.content?.substring(0, 40) || "N/A"}
              </div>
              <div className="text-[10px] text-slate-400 mt-0.5">Recalled {stats.mostAccessed?.access_count || 0} times</div>
            </div>
          </div>
        </div>
      )}

      {/* 搜索 */}
      <div className="mb-6 relative shrink-0">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
        <input 
          className="w-full pl-12 pr-4 py-3 bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition shadow-sm"
          placeholder="Search memory contents, types..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto bg-white rounded-2xl border border-slate-200 shadow-sm">
        <table className="w-full text-left border-collapse">
          <thead className="bg-slate-50 sticky top-0 z-10 border-b border-slate-200">
            <tr>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider w-24">Type</th>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider">Content</th>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider w-40">Updated</th>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider w-20 text-center">Hits</th>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider w-20">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
               <tr><td colSpan="5" className="px-6 py-12 text-center text-slate-400">Loading database...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan="5" className="px-6 py-12 text-center text-slate-400">Database is empty or no matches found.</td></tr>
            ) : (
              filtered.map((item) => (
                <tr key={item.id} className="hover:bg-slate-50/80 transition-colors group">
                  <td className="px-6 py-4 align-top">
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase bg-blue-50 text-blue-600 border border-blue-100">
                      <Tag size={10} /> {item.type}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-700 leading-relaxed max-w-3xl font-mono text-[13px]">
                    {item.content}
                  </td>
                  <td className="px-6 py-4 text-xs text-slate-500 font-mono whitespace-nowrap">
                    <div>{new Date(item.last_accessed).toLocaleDateString()}</div>
                    <div className="text-slate-400">{new Date(item.last_accessed).toLocaleTimeString()}</div>
                  </td>
                  <td className="px-6 py-4 text-center">
                    <span className="px-2 py-1 bg-slate-100 rounded text-xs font-mono font-medium text-slate-600">
                      {item.access_count}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button 
                      onClick={() => deleteMemory(item.id)}
                      className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition opacity-0 group-hover:opacity-100"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}