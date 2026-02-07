import React, { useEffect, useState } from 'react';
import { Trash2, Clock, FileText, Activity, RefreshCw } from 'lucide-react';
import axios from 'axios';
import { toast } from 'sonner';

const API_BASE = "http://localhost:8000/api";

export default function SentinelDashboard() {
  const [sentinels, setSentinels] = useState({ time: {}, file: {}, behavior: {} });
  const [loading, setLoading] = useState(false);

  const fetchSentinels = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/sentinels`);
      setSentinels(res.data);
    } catch (err) {
      toast.error("Failed to load sentinels");
    } finally {
      setLoading(false);
    }
  };

  const deleteSentinel = async (type, id) => {
    try {
      await axios.delete(`${API_BASE}/sentinels/${type}/${id}`);
      toast.success("Sentinel removed");
      fetchSentinels();
    } catch (err) {
      toast.error("Failed to remove sentinel");
    }
  };

  useEffect(() => {
    fetchSentinels();
    const interval = setInterval(fetchSentinels, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Sentinel System</h1>
          <p className="text-slate-500">Autonomous monitoring agents status.</p>
        </div>
        <button onClick={fetchSentinels} className="p-2 text-slate-400 hover:text-primary transition">
          <RefreshCw size={20} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
        <Section title="Time Triggers" icon={Clock} color="text-blue-500" bg="bg-blue-50">
          {Object.entries(sentinels.time || {}).map(([id, data]) => (
            <Card key={id} data={data} id={id} type="time" onDelete={deleteSentinel}>
              <div className="flex items-baseline gap-1 mb-2">
                <span className="text-3xl font-bold text-slate-700">{data.interval}</span>
                <span className="text-sm font-medium text-slate-400 uppercase">{data.unit}</span>
              </div>
            </Card>
          ))}
        </Section>

        <Section title="File Watchers" icon={FileText} color="text-emerald-500" bg="bg-emerald-50">
          {Object.entries(sentinels.file || {}).map(([id, data]) => (
             <Card key={id} data={data} id={id} type="file" onDelete={deleteSentinel}>
                <div className="font-mono text-[10px] text-slate-500 break-all bg-slate-100 p-2 rounded mb-3 border border-slate-200">
                  {data.path}
                </div>
             </Card>
          ))}
        </Section>

        <Section title="Behavior Hooks" icon={Activity} color="text-purple-500" bg="bg-purple-50">
          {Object.entries(sentinels.behavior || {}).map(([id, data]) => (
             <Card key={id} data={data} id={id} type="behavior" onDelete={deleteSentinel}>
                <div className="flex items-center gap-2 mb-3">
                   <kbd className="px-2 py-1 bg-slate-800 text-white rounded text-xs font-mono shadow-sm">{data.key_combo}</kbd>
                </div>
             </Card>
          ))}
        </Section>
      </div>
    </div>
  );
}

const Section = ({ title, icon: Icon, children, color, bg }) => (
  <div className="space-y-4">
    <div className={`flex items-center gap-2 ${color} font-bold uppercase text-xs tracking-wider mb-2`}>
      <div className={`p-1.5 rounded-md ${bg}`}><Icon size={14} /></div>
      {title}
    </div>
    {children.length === 0 ? (
      <div className="h-32 border-2 border-dashed border-slate-100 rounded-xl flex items-center justify-center text-slate-300 text-sm italic">
        No active sentinels
      </div>
    ) : children}
  </div>
);

const Card = ({ data, id, type, onDelete, children }) => (
  <div className="bg-white border border-slate-200 rounded-xl p-5 hover:shadow-lg hover:-translate-y-1 transition-all duration-300 group relative">
    {children}
    <p className="text-slate-600 text-sm leading-snug">{data.description}</p>
    <button 
      onClick={() => onDelete(type, id)}
      className="absolute top-3 right-3 text-slate-300 hover:text-red-500 hover:bg-red-50 p-1.5 rounded-lg transition opacity-0 group-hover:opacity-100"
    >
      <Trash2 size={16} />
    </button>
  </div>
);