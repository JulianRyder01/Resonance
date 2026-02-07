import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Trash2, Search, Database, RefreshCw, Clock, Tag } from 'lucide-react';
import { toast } from 'sonner';

const API_BASE = "http://localhost:8000/api";

export default function MemoryManager() {
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const fetchMemories = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/memory`);
      // 按时间倒序
      const sorted = res.data.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      setMemories(sorted);
    } catch (err) {
      toast.error("Failed to load memories");
    } finally {
      setLoading(false);
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
    fetchMemories();
  }, []);

  const filtered = memories.filter(m => 
    m.content.toLowerCase().includes(search.toLowerCase()) || 
    m.type.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-8 max-w-7xl mx-auto h-full flex flex-col">
      <header className="flex justify-between items-end mb-8 shrink-0">
        <div>
          <h1 className="text-3xl font-bold text-slate-800 flex items-center gap-3">
            <Database className="text-primary" /> Memory Core
          </h1>
          <p className="text-slate-500 mt-1">Manage long-term vector knowledge base (RAG).</p>
        </div>
        <button 
          onClick={fetchMemories} 
          className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 hover:text-primary transition shadow-sm"
        >
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </header>

      {/* 搜索栏 */}
      <div className="mb-6 relative shrink-0">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={20} />
        <input 
          className="w-full pl-12 pr-4 py-3 bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition shadow-sm"
          placeholder="Search memory contents, types..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {/* 列表内容 */}
      <div className="flex-1 overflow-y-auto bg-white rounded-2xl border border-slate-200 shadow-sm">
        <table className="w-full text-left border-collapse">
          <thead className="bg-slate-50 sticky top-0 z-10 border-b border-slate-200">
            <tr>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider w-24">Type</th>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider">Content</th>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider w-40">Last Access</th>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider w-20 text-center">Hits</th>
              <th className="px-6 py-4 text-xs font-bold text-slate-500 uppercase tracking-wider w-20">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan="5" className="px-6 py-12 text-center text-slate-400">
                  {loading ? "Loading..." : "No memories found matching criteria."}
                </td>
              </tr>
            ) : (
              filtered.map((item) => (
                <tr key={item.id} className="hover:bg-slate-50/80 transition-colors group">
                  <td className="px-6 py-4 align-top">
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase bg-blue-50 text-blue-600 border border-blue-100">
                      <Tag size={10} /> {item.type}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-700 leading-relaxed max-w-3xl">
                    {item.content}
                  </td>
                  <td className="px-6 py-4 text-xs text-slate-500 font-mono whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <Clock size={12} />
                      {new Date(item.last_accessed).toLocaleDateString()}
                    </div>
                    <div className="text-slate-400 ml-5">
                      {new Date(item.last_accessed).toLocaleTimeString()}
                    </div>
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
                      title="Delete"
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