// frontend/src/components/MemoryManager.jsx
import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { 
  Trash2, 
  Search, 
  Database, 
  RefreshCw, 
  Tag, 
  Activity, 
  Zap, 
  ArrowUpDown,
  Calendar,
  Layers
} from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

const API_BASE = "http://localhost:8000/api";

export default function MemoryManager() {
  const { t } = useTranslation();
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sortMode, setSortMode] = useState("time"); // 'time', 'relevance', 'accessed'
  
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
      setMemories(data);
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

  // --- 数据处理与排序 ---
  const processedData = useMemo(() => {
    let data = [...memories];

    // 1. 搜索过滤
    if (search) {
        const lowerQ = search.toLowerCase();
        data = data.filter(m => 
            (m.content || "").toLowerCase().includes(lowerQ) || 
            (m.type || "").toLowerCase().includes(lowerQ)
        );
    }

    // 2. 排序
    if (sortMode === 'relevance') {
        data.sort((a, b) => b.access_count - a.access_count);
    } else if (sortMode === 'accessed') {
        data.sort((a, b) => new Date(b.last_accessed) - new Date(a.last_accessed));
    } else {
        // default: time (created/updated)
        data.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    }

    return data;
  }, [memories, search, sortMode]);

  // --- 统计数据 ---
  const stats = useMemo(() => {
    if (!memories.length) return null;
    const total = memories.length;
    
    // 最近7天活跃
    const now = new Date();
    const activeRecent = memories.filter(m => {
        const d = new Date(m.last_accessed);
        const diffTime = Math.abs(now - d);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)); 
        return diffDays <= 7;
    }).length;

    // 计算最大访问次数（用于可视化比例）
    const maxHits = Math.max(...memories.map(m => m.access_count || 0), 1);

    return { total, activeRecent, maxHits };
  }, [memories]);

  return (
    <div className="p-8 max-w-7xl mx-auto h-full flex flex-col">
      <header className="flex justify-between items-end mb-6 shrink-0">
        <div>
          <h1 className="text-3xl font-bold text-slate-800 flex items-center gap-3">
            <Database className="text-primary" /> {t('memory.title')}
          </h1>
          <p className="text-slate-500 mt-1">{t('memory.subtitle')}</p>
        </div>
        
        <div className="flex gap-3">
            {/* 策略切换器 */}
            <div className="flex items-center gap-2 bg-slate-100 p-1 rounded-lg border border-slate-200">
                <button 
                    onClick={() => updateStrategy('semantic')}
                    disabled={strategyLoading}
                    className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${currentStrategy === 'semantic' ? 'bg-white text-primary shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                >
                    {t('memory.strategy.semantic')}
                </button>
                <button 
                    onClick={() => updateStrategy('hybrid_time')}
                    disabled={strategyLoading}
                    className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all ${currentStrategy === 'hybrid_time' ? 'bg-white text-purple-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                >
                    {t('memory.strategy.hybrid')}
                </button>
            </div>

            <button 
            onClick={fetchMemories} 
            className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 hover:text-primary transition shadow-sm font-medium text-sm"
            >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} /> {t('common.refresh')}
            </button>
        </div>
      </header>

      {/* --- Dashboard Stats --- */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8 shrink-0">
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4 relative overflow-hidden">
            <div className="absolute right-0 top-0 opacity-[0.05] -mr-4 -mt-4 text-blue-600">
                <Database size={100} />
            </div>
            <div className="p-3 bg-blue-50 text-blue-500 rounded-lg"><Layers size={24} /></div>
            <div>
              <div className="text-sm text-slate-500 font-medium uppercase tracking-wider">Total Vectors</div>
              <div className="text-3xl font-bold text-slate-800">{stats.total}</div>
            </div>
          </div>

          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4 relative overflow-hidden">
            <div className="absolute right-0 top-0 opacity-[0.05] -mr-4 -mt-4 text-emerald-600">
                <Activity size={100} />
            </div>
            <div className="p-3 bg-emerald-50 text-emerald-500 rounded-lg"><Activity size={24} /></div>
            <div>
              <div className="text-sm text-slate-500 font-medium uppercase tracking-wider">Active (7 Days)</div>
              <div className="text-3xl font-bold text-slate-800">{stats.activeRecent}</div>
            </div>
          </div>
        </div>
      )}

      {/* 搜索与排序 */}
      <div className="mb-4 flex gap-4 shrink-0">
        <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
            <input 
            className="w-full pl-11 pr-4 py-2.5 bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition shadow-sm text-sm"
            placeholder={t('memory.search_placeholder')}
            value={search}
            onChange={e => setSearch(e.target.value)}
            />
        </div>
        
        {/* 排序下拉菜单 */}
        <div className="relative">
            <select 
                value={sortMode}
                onChange={(e) => setSortMode(e.target.value)}
                className="appearance-none bg-white border border-slate-200 text-slate-600 py-2.5 pl-4 pr-10 rounded-xl text-sm font-medium shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20 hover:bg-slate-50 cursor-pointer"
            >
                <option value="time">{t('memory.sort.time')}</option>
                <option value="relevance">{t('memory.sort.relevance')}</option>
                <option value="accessed">{t('memory.sort.accessed')}</option>
            </select>
            <ArrowUpDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto bg-white rounded-2xl border border-slate-200 shadow-sm">
        <table className="w-full text-left border-collapse">
          <thead className="bg-slate-50 sticky top-0 z-10 border-b border-slate-200">
            <tr>
              <th className="px-6 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider w-32">{t('memory.table.type')}</th>
              <th className="px-6 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider">{t('memory.table.content')}</th>
              <th className="px-6 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider w-48">{t('memory.table.strength')}</th>
              <th className="px-6 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider w-40 text-right">{t('memory.table.last_access')}</th>
              <th className="px-6 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider w-20"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
               <tr><td colSpan="5" className="px-6 py-12 text-center text-slate-400 flex flex-col items-center gap-2">
                   <RefreshCw className="animate-spin" /> {t('common.loading')}
               </td></tr>
            ) : processedData.length === 0 ? (
              <tr><td colSpan="5" className="px-6 py-12 text-center text-slate-400">{t('memory.no_data')}</td></tr>
            ) : (
                processedData.map((item) => {
                    const hitPercent = Math.min((item.access_count / (stats?.maxHits || 1)) * 100, 100);
                    
                    return (
                        <tr key={item.id} className="hover:bg-slate-50/80 transition-colors group">
                        {/* Type Label */}
                        <td className="px-6 py-4 align-top">
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-bold uppercase bg-slate-100 text-slate-600 border border-slate-200">
                            <Tag size={10} /> {item.type}
                            </span>
                        </td>
                        
                        {/* Content */}
                        <td className="px-6 py-4">
                            <div className="text-sm text-slate-700 leading-relaxed font-mono text-[13px] line-clamp-3 group-hover:line-clamp-none transition-all">
                                {item.content}
                            </div>
                            <div className="text-[10px] text-slate-300 mt-1 flex items-center gap-2">
                                {t('memory.id')}: {item.id.substring(0,8)}... • {t('memory.created')}: {new Date(item.timestamp).toLocaleDateString()}
                            </div>
                        </td>

                        {/* Recall Strength (Visual Bar) */}
                        <td className="px-6 py-4 align-middle">
                            <div className="flex flex-col gap-1 w-full">
                                <div className="flex justify-between text-[10px] font-bold text-slate-500">
                                    <span>{item.access_count} Hits</span>
                                    {hitPercent > 80 && <Zap size={10} className="text-amber-500 fill-amber-500" />}
                                </div>
                                <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                                    <div 
                                        className={`h-full rounded-full transition-all duration-500 ${
                                            hitPercent > 75 ? 'bg-amber-500' : 
                                            hitPercent > 40 ? 'bg-blue-500' : 'bg-slate-300'
                                        }`}
                                        style={{ width: `${Math.max(hitPercent, 5)}%` }}
                                    />
                                </div>
                            </div>
                        </td>

                        {/* Time */}
                        <td className="px-6 py-4 text-xs text-slate-500 font-mono whitespace-nowrap text-right align-middle">
                            <div className="flex items-center justify-end gap-1.5">
                                {new Date(item.last_accessed).toLocaleDateString()} <Calendar size={12} className="text-slate-300" />
                            </div>
                            <div className="text-[10px] text-slate-400 mt-0.5">
                                {new Date(item.last_accessed).toLocaleTimeString()}
                            </div>
                        </td>

                        {/* Actions */}
                        <td className="px-6 py-4 text-right align-middle">
                            <button 
                            onClick={() => deleteMemory(item.id)}
                            className="p-2 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition opacity-0 group-hover:opacity-100"
                            title={t('memory.delete_tooltip')}
                            >
                            <Trash2 size={16} />
                            </button>
                        </td>
                        </tr>
                    );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}